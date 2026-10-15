# SaveTrack Bot

Telegram bot for downloading publicly accessible media links supported by `yt-dlp`, with mandatory channel subscription, SQLite-backed user/channel storage, and an admin panel.

## 1. Important security step
The bot token that was previously pasted into chat should be revoked in [@BotFather](https://t.me/BotFather). Create a new token and keep it private. Never commit it into GitHub.

## 2. GitHub files
Upload these files to the root of your repository:
- `main.py`
- `requirements.txt`
- `Dockerfile`
- `render.yaml`

## 3. Render setup
1. Create a new **Web Service** from your GitHub repository.
2. Select Docker runtime (Render can detect the `Dockerfile`).
3. In Environment, add:
   - `BOT_TOKEN` = your newly generated token
   - `ADMIN_ID` = your numeric Telegram user ID
4. Deploy.

`render.yaml` can also be used as a Blueprint. Free services may sleep and local SQLite storage can be lost when the instance is replaced/redeployed. For durable data, attach a persistent disk and set `DB_PATH` to a path on that disk, if your Render plan supports it.

## 4. Admin commands
Send `/admin` to the bot from the account whose ID is in `ADMIN_ID`.
- Statistics
- Add/remove required-subscription channels
- Broadcast a message to users

The bot must be an administrator in each required channel for membership checks to work.

## 5. Notes
- YouTube and other platforms may change their delivery systems; `yt-dlp` cannot guarantee every link will work.
- The bot only downloads media that is publicly accessible and that you have permission to save.
- Telegram Bot API file size limits may prevent sending larger files.
