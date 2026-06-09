# Telegram publisher local

Ce petit bot permet de publier une photo Telegram dans le site statique, puis de pousser le changement sur GitHub.

## 1. Creer le bot Telegram

1. Ouvre Telegram et parle a `@BotFather`.
2. Lance `/newbot`.
3. Donne un nom au bot.
4. Copie le token donne par BotFather.

## 2. Configurer le projet

Dans ce dossier, copie `.env.example` vers `.env`, puis remplace le token :

```powershell
Copy-Item .env.example .env
notepad .env
```

Optionnel : pour bloquer le bot a ton compte Telegram, ajoute `TELEGRAM_ALLOWED_CHAT_ID`.
Pour connaitre ton chat id, lance le bot une premiere fois, envoie `/start`, puis regarde le fichier `.telegram-bot-state.json`.

## 3. Lancer le bot

```powershell
python scripts/telegram_publisher.py
```

Garde cette fenetre ouverte. Tant que le script tourne et que le PC est connecte, le bot peut publier.

## 4. Utilisation

Tu peux envoyer une photo avec une legende :

```text
remplace hero
```

```text
ajoute dans outils
```

```text
ajoute dans supports
```

Tu peux aussi envoyer la photo sans legende, puis envoyer la consigne juste apres.

Sections reconnues : `hero`, `news`, `idee`, `reperes`, `usages`, `outils`, `prompt`, `enfants`, `mini-defi`, `glossaire`, `supports`.

## 5. Retirer la derniere photo

Si la derniere publication faite par le bot ne te plait pas, envoie simplement :

```text
annule
```

ou :

```text
retire la derniere photo
```

Le bot cree alors un commit de revert, supprime la photo ajoutee par le dernier commit Telegram, puis repousse sur GitHub.

## 6. Publication

A chaque photo traitee, le script fait automatiquement :

```powershell
git add
git commit
git push origin main
```

Les photos sont sauvegardees dans `uploads/telegram/` et publiees avec le site.
