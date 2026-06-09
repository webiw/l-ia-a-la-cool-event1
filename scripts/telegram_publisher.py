#!/usr/bin/env python
"""Telegram photo publisher for the local Event1 static site.

Run this script on the Windows PC that has the OneDrive project folder.
It listens to a Telegram bot, saves received photos, edits index.html,
then commits and pushes the change to GitHub.
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INDEX_FILE = ROOT / "index.html"
UPLOAD_DIR = ROOT / "uploads" / "telegram"
STATE_FILE = ROOT / ".telegram-bot-state.json"
ENV_FILE = ROOT / ".env"
GIT_EXE = os.environ.get("GIT_EXE", r"C:\Program Files\Git\cmd\git.exe")

SECTION_ALIASES = {
    "news": "news",
    "actu": "news",
    "actualite": "news",
    "actualites": "news",
    "idee": "idee",
    "reperes": "reperes",
    "usages": "usages",
    "usage": "usages",
    "outils": "outils",
    "outil": "outils",
    "prompt": "prompt",
    "enfants": "enfants",
    "mini-defi": "mini-defi",
    "mini defi": "mini-defi",
    "defi": "mini-defi",
    "glossaire": "glossaire",
    "supports": "supports",
    "infographies": "supports",
    "infographie": "supports",
}

UNDO_WORDS = (
    "annule",
    "annuler",
    "retire",
    "retirer",
    "enleve",
    "enlever",
    "supprime",
    "supprimer",
    "delete",
    "remove",
    "undo",
    "revert",
    "comme c'etait",
    "comme cetait",
    "juste avant",
)


def load_env_file() -> None:
    if not ENV_FILE.exists():
        return
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"offset": 0, "pending": {}}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"offset": 0, "pending": {}}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def telegram_api(token: str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = None
    if params is not None:
        data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(request, timeout=65) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error on {method}: {payload}")
    return payload


def send_message(token: str, chat_id: int, text: str) -> None:
    telegram_api(token, "sendMessage", {"chat_id": chat_id, "text": text})


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def slugify(value: str) -> str:
    normalized = normalize_text(value)
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized[:44] or "photo"


def download_photo(token: str, photo: dict[str, Any], instruction: str) -> Path:
    file_id = photo["file_id"]
    file_info = telegram_api(token, "getFile", {"file_id": file_id})["result"]
    file_path = file_info["file_path"]
    suffix = Path(file_path).suffix or ".jpg"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{stamp}-{slugify(instruction)}{suffix}"
    target = UPLOAD_DIR / filename
    url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    with urllib.request.urlopen(url, timeout=65) as response:
        target.write_bytes(response.read())
    return target


def ensure_telegram_css(document: str) -> str:
    if ".telegram-photo" in document:
        return document
    css = """

    .telegram-photo {
      margin: 24px 0 0;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--paper);
    }

    .telegram-photo img {
      width: 100%;
      max-height: 620px;
      border-radius: 6px;
      object-fit: cover;
    }
"""
    marker = "\n    figcaption {"
    if marker not in document:
        raise RuntimeError("Could not find a safe place to insert Telegram photo CSS.")
    return document.replace(marker, css + marker, 1)


def build_figure(image_path: Path, instruction: str) -> str:
    relative = image_path.relative_to(ROOT).as_posix()
    caption = html.escape(instruction.strip() or "Photo ajoutee via Telegram", quote=True)
    alt = caption
    return (
        '      <figure class="telegram-photo">\n'
        f'        <img src="{relative}" alt="{alt}">\n'
        f"        <figcaption>{caption}</figcaption>\n"
        "      </figure>\n"
    )


def replace_hero_image(document: str, image_path: Path, instruction: str) -> str:
    relative = image_path.relative_to(ROOT).as_posix()
    alt = html.escape(instruction.strip() or "Photo principale ajoutee via Telegram", quote=True)
    pattern = (
        r'(<div class="hero-media">\s*'
        r'<img src=")[^"]+(" alt=")[^"]+(">\s*</div>)'
    )
    def replacement(match: re.Match[str]) -> str:
        return f"{match.group(1)}{relative}{match.group(2)}{alt}{match.group(3)}"

    updated, count = re.subn(pattern, replacement, document, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError("Could not find the hero image to replace.")
    return updated


def section_id_from_instruction(instruction: str) -> str:
    normalized = normalize_text(instruction)
    if "hero" in normalized or "image principale" in normalized or "photo principale" in normalized:
        return "hero"
    for key, section_id in SECTION_ALIASES.items():
        if normalize_text(key) in normalized:
            return section_id
    return "supports"


def insert_in_section(document: str, section_id: str, figure: str) -> str:
    pattern = rf'(<section id="{re.escape(section_id)}"[^>]*>.*?)(\n    </section>)'
    def replacement(match: re.Match[str]) -> str:
        return f"{match.group(1)}\n{figure}{match.group(2)}"

    updated, count = re.subn(pattern, replacement, document, count=1, flags=re.S)
    if count == 1:
        return updated
    raise RuntimeError(f'Could not find section id="{section_id}".')


def update_index(image_path: Path, instruction: str) -> str:
    document = INDEX_FILE.read_text(encoding="utf-8")
    target = section_id_from_instruction(instruction)
    if target == "hero":
        updated = replace_hero_image(document, image_path, instruction)
        action = "Hero image replaced"
    else:
        updated = ensure_telegram_css(document)
        updated = insert_in_section(updated, target, build_figure(image_path, instruction))
        action = f'Photo inserted in section "{target}"'
    INDEX_FILE.write_text(updated, encoding="utf-8", newline="\n")
    return action


def run_git(*args: str) -> str:
    command = [GIT_EXE, *args]
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def publish_changes(image_path: Path, instruction: str) -> str:
    run_git("add", "--", "index.html", image_path.relative_to(ROOT).as_posix())
    message = f"Add Telegram photo: {slugify(instruction)}"
    commit_output = run_git("commit", "-m", message)
    run_git("push", "origin", "main")
    first_line = commit_output.splitlines()[0] if commit_output else "commit created"
    return first_line


def is_undo_request(text: str) -> bool:
    normalized = normalize_text(text)
    return any(word in normalized for word in UNDO_WORDS)


def undo_last_telegram_publish() -> str:
    subject = run_git("log", "-1", "--format=%s")
    if not subject.startswith("Add Telegram photo:"):
        raise RuntimeError(
            "Le dernier commit n'est pas une photo Telegram. Je n'annule rien automatiquement."
        )
    commit_output = run_git("revert", "--no-edit", "HEAD")
    run_git("push", "origin", "main")
    first_line = commit_output.splitlines()[0] if commit_output else "revert created"
    return first_line


def is_allowed(chat_id: int) -> bool:
    allowed = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
    return not allowed or str(chat_id) == allowed


def handle_photo(token: str, state: dict[str, Any], message: dict[str, Any]) -> None:
    chat_id = message["chat"]["id"]
    if not is_allowed(chat_id):
        return
    photos = message.get("photo") or []
    if not photos:
        return
    instruction = (message.get("caption") or "").strip()
    photo = photos[-1]
    if not instruction:
        state.setdefault("pending", {})[str(chat_id)] = photo
        save_state(state)
        send_message(token, chat_id, "Photo recue. Envoie maintenant la consigne: hero, news, outils, supports...")
        return
    process_photo_instruction(token, chat_id, photo, instruction)


def handle_text(token: str, state: dict[str, Any], message: dict[str, Any]) -> None:
    chat_id = message["chat"]["id"]
    if not is_allowed(chat_id):
        return
    text = (message.get("text") or "").strip()
    if text == "/start":
        send_message(
            token,
            chat_id,
            "Envoie une photo avec une legende comme: 'ajoute dans outils' ou 'remplace hero'. Pour enlever la derniere photo publiee: 'annule' ou 'retire la derniere photo'.",
        )
        return
    pending = state.setdefault("pending", {}).pop(str(chat_id), None)
    save_state(state)
    if not pending:
        if is_undo_request(text):
            try:
                send_message(token, chat_id, "J'annule la derniere photo Telegram et je republie...")
                revert = undo_last_telegram_publish()
                send_message(token, chat_id, f"C'est retire et publie sur GitHub. {revert}")
            except Exception as exc:
                send_message(token, chat_id, f"Impossible d'annuler: {exc}")
                raise
            return
        send_message(
            token,
            chat_id,
            "Envoie d'abord une photo, ou ecris 'annule' pour retirer la derniere photo Telegram.",
        )
        return
    process_photo_instruction(token, chat_id, pending, text)


def process_photo_instruction(token: str, chat_id: int, photo: dict[str, Any], instruction: str) -> None:
    try:
        send_message(token, chat_id, "Je telecharge la photo et je mets a jour le site...")
        image_path = download_photo(token, photo, instruction)
        action = update_index(image_path, instruction)
        commit = publish_changes(image_path, instruction)
        send_message(token, chat_id, f"Publie sur GitHub. {action}. {commit}")
    except Exception as exc:
        send_message(token, chat_id, f"Erreur: {exc}")
        raise


def poll(token: str) -> None:
    state = load_state()
    print("Telegram publisher is running. Press Ctrl+C to stop.")
    while True:
        try:
            offset = int(state.get("offset", 0))
            payload = telegram_api(token, "getUpdates", {"timeout": 55, "offset": offset})
            for update in payload.get("result", []):
                state["offset"] = update["update_id"] + 1
                message = update.get("message") or update.get("edited_message") or {}
                if message.get("photo"):
                    handle_photo(token, state, message)
                elif message.get("text"):
                    handle_text(token, state, message)
                save_state(state)
        except KeyboardInterrupt:
            print("Stopped.")
            return
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"Network error, retrying: {exc}", file=sys.stderr)
            time.sleep(5)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            time.sleep(5)


def main() -> int:
    load_env_file()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Missing TELEGRAM_BOT_TOKEN. Copy .env.example to .env and add your bot token.", file=sys.stderr)
        return 1
    if not INDEX_FILE.exists():
        print(f"Cannot find {INDEX_FILE}", file=sys.stderr)
        return 1
    poll(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
