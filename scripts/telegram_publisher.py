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
    return normalized[:44].strip("-") or "photo"


def title_from_slug(value: str) -> str:
    words = re.sub(r"[-_]+", " ", value).strip()
    return words[:1].upper() + words[1:] if words else "Nouveau sujet"


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


def paragraph_html(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "<p>Contenu ajoute depuis Telegram, a completer selon les besoins.</p>"
    return "\n".join(f"<p>{html.escape(line)}</p>" for line in lines)


def extract_topic_command(text: str) -> tuple[str, str, str] | None:
    normalized = normalize_text(text)
    patterns = (
        ("page", r"\b(?:ajoute|cree|cr[eé]e|nouvelle|fais)\s+(?:une\s+)?page\s+(?:sur|pour|a propos de|à propos de)?\s*"),
        ("section", r"\b(?:ajoute|cree|cr[eé]e|nouvelle|fais)\s+(?:une\s+)?section\s+(?:sur|pour|a propos de|à propos de)?\s*"),
    )
    for kind, pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        original_tail = text[match.end():].strip(" :-\n\t")
        if not original_tail:
            return kind, "Nouveau sujet", ""
        first_line, _, rest = original_tail.partition("\n")
        title, sep, inline_body = first_line.partition(":")
        body = "\n".join(part.strip() for part in (inline_body, rest) if part.strip())
        return kind, title.strip() or "Nouveau sujet", body
    return None


def add_nav_link(document: str, href: str, label: str) -> str:
    link = f'        <a href="{html.escape(href, quote=True)}">{html.escape(label)}</a>\n'
    if link.strip() in document:
        return document
    marker = "      </div>\n    </div>\n  </nav>"
    if marker not in document:
        raise RuntimeError("Could not find the navigation block.")
    return document.replace(marker, link + marker, 1)


def build_topic_section(section_id: str, title: str, body: str) -> str:
    return (
        f'    <section id="{html.escape(section_id, quote=True)}">\n'
        '      <div class="section-head">\n'
        "        <div>\n"
        '          <span class="eyebrow">Ajout Telegram</span>\n'
        f"          <h2>{html.escape(title)}</h2>\n"
        "        </div>\n"
        f'        <p class="lead">Sujet ajoute depuis Telegram le {datetime.now().strftime("%d/%m/%Y")}.</p>\n'
        "      </div>\n"
        '      <article class="card">\n'
        f"        {paragraph_html(body)}\n"
        "      </article>\n"
        "    </section>\n"
    )


def create_topic_section(title: str, body: str) -> list[Path]:
    slug = slugify(title)
    section_id = f"telegram-{slug}"
    document = INDEX_FILE.read_text(encoding="utf-8")
    section = build_topic_section(section_id, title_from_slug(title) if title == slug else title, body)
    marker = '    <section id="supports">'
    if marker in document:
        document = document.replace(marker, section + "\n" + marker, 1)
    else:
        document = document.replace("  </main>", section + "\n  </main>", 1)
    INDEX_FILE.write_text(document, encoding="utf-8", newline="\n")
    return [INDEX_FILE]


def build_topic_page(slug: str, title: str, body: str) -> str:
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} - IAcool</title>
  <meta name="description" content="{safe_title}">
  <style>
    :root {{
      --canvas: #fffdf8;
      --paper: #ffffff;
      --ink: #111827;
      --muted: #697076;
      --line: #e6dfd3;
      --orange: #ee6043;
      --teal: #087f83;
      --radius: 8px;
      --max: 920px;
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--canvas);
      line-height: 1.6;
    }}

    main {{
      width: min(var(--max), calc(100% - 32px));
      margin: 0 auto;
      padding: 42px 0 72px;
    }}

    a {{ color: #b43f2c; font-weight: 750; }}

    .eyebrow {{
      display: inline-flex;
      min-height: 30px;
      align-items: center;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--paper);
      color: var(--teal);
      font-size: 0.78rem;
      font-weight: 850;
      text-transform: uppercase;
    }}

    h1 {{
      max-width: 820px;
      margin: 18px 0 18px;
      font-size: clamp(2.6rem, 8vw, 5.5rem);
      line-height: 1.04;
      letter-spacing: 0;
    }}

    .card {{
      margin-top: 28px;
      padding: 24px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--paper);
    }}

    p {{ color: var(--muted); font-size: 1.06rem; }}
  </style>
</head>
<body>
  <main>
    <a href="index.html">Retour a l'accueil</a>
    <header>
      <span class="eyebrow">Ajout Telegram</span>
      <h1>{safe_title}</h1>
      <p>Page ajoutee depuis Telegram le {datetime.now().strftime("%d/%m/%Y")}.</p>
    </header>
    <article class="card">
      {paragraph_html(body)}
    </article>
  </main>
</body>
</html>
"""


def create_topic_page(title: str, body: str) -> list[Path]:
    slug = slugify(title)
    page_path = ROOT / f"{slug}.html"
    if page_path.exists():
        stamp = datetime.now().strftime("%H%M%S")
        page_path = ROOT / f"{slug}-{stamp}.html"
    page_path.write_text(build_topic_page(page_path.stem, title, body), encoding="utf-8", newline="\n")
    document = INDEX_FILE.read_text(encoding="utf-8")
    document = add_nav_link(document, page_path.name, title[:18])
    INDEX_FILE.write_text(document, encoding="utf-8", newline="\n")
    return [INDEX_FILE, page_path]


def publish_paths(paths: list[Path], message: str) -> str:
    relative_paths = [path.relative_to(ROOT).as_posix() for path in paths]
    run_git("add", "--", *relative_paths)
    commit_output = run_git("commit", "-m", message)
    run_git("push", "origin", "main")
    first_line = commit_output.splitlines()[0] if commit_output else "commit created"
    return first_line


def process_topic_command(text: str) -> tuple[str, str] | None:
    command = extract_topic_command(text)
    if not command:
        return None
    kind, title, body = command
    if kind == "page":
        paths = create_topic_page(title, body)
        commit = publish_paths(paths, f"Add Telegram page: {slugify(title)}")
        return "Page ajoutee", commit
    paths = create_topic_section(title, body)
    commit = publish_paths(paths, f"Add Telegram section: {slugify(title)}")
    return "Section ajoutee", commit


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
    if not subject.startswith("Add Telegram "):
        raise RuntimeError(
            "Le dernier commit n'est pas un ajout Telegram. Je n'annule rien automatiquement."
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
            "Envoie une photo avec une legende comme: 'ajoute dans outils' ou 'remplace hero'. Tu peux aussi ecrire: 'ajoute une section sur ...' ou 'ajoute une page sur ...'. Pour enlever le dernier ajout: 'annule'.",
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
        topic_result = process_topic_command(text)
        if topic_result:
            action, commit = topic_result
            send_message(token, chat_id, f"{action} et publiee sur GitHub. {commit}")
            return
        send_message(
            token,
            chat_id,
            "Envoie une photo, ecris 'ajoute une section sur ...', 'ajoute une page sur ...', ou 'annule'.",
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
