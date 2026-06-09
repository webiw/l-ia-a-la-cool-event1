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

Optionnel : pour activer la redaction IA, ajoute aussi `OPENAI_API_KEY` dans `.env`.

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

## 5. Ajouter une section ou une page

Tu peux aussi envoyer une consigne texte sans photo :

```text
ajoute une section sur Programme de la soiree : accueil, demos, questions, apero.
```

La section sera ajoutee dans `index.html`, juste avant les supports visuels.

Pour creer une page separee :

```text
ajoute une page sur Sponsors : merci aux partenaires de l'evenement.
```

Le bot cree alors un fichier HTML dedie, ajoute un lien dans la navigation, commit et push.

Astuce : tout ce qui est apres `:` devient le contenu de la section ou de la page.

## 6. Rediger un texte automatiquement

Avec `OPENAI_API_KEY` configure dans `.env`, tu peux demander :

```text
redige un texte de 300 mots sur l'IA pour les artisans
```

Par defaut, le bot ajoute le texte dans une nouvelle section de `index.html`.

Pour creer une page dediee :

```text
redige une page de 600 mots sur comment utiliser ChatGPT en association
```

Le bot redige le texte, cree la section ou la page, commit et push.

## 7. Retirer le dernier ajout

Si la derniere publication faite par le bot ne te plait pas, photo, section ou page, envoie simplement :

```text
annule
```

ou :

```text
retire la derniere photo
```

Le bot cree alors un commit de revert, retire le dernier ajout Telegram, puis repousse sur GitHub.

## 8. Publication

A chaque photo traitee, le script fait automatiquement :

```powershell
git add
git commit
git push origin main
```

Les photos sont sauvegardees dans `uploads/telegram/` et publiees avec le site.
