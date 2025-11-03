# Telegram Bot Deployment Guide

## 1. Prerequisites

- Python 3.10+
- MongoDB Atlas cluster (or self-hosted MongoDB)
- Telegram bot token
- Optional: remove.bg API key, Gemini API key, YouTube API key
- Keepalived (for high-availability setup)

## 2. Clone and Install Dependencies

```bash
git clone <repo-url> telegram-bot
cd telegram-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Environment Configuration

Create a `.env` file at the project root (or copy `.env.example`) and set the secrets:

```
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
ADMIN_CHAT_ID=123456789
YT_API=YOUR_YOUTUBE_API_KEY
BOT_USERNAME=your_bot_username
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
REMOVE_BG_API_KEY=your_remove_bg_api_key   # optional
MONGODB_URI=your_mongodb_connection_string
MONGODB_DB_NAME=telegram_bot
UPLOAD_TARGET=pixeldrain  # legacy default; optional when UPLOAD_TARGETS is set
UPLOAD_TARGETS=pixeldrain,gofile  # comma-separated rotation list
PIXELDRAIN_KEY=           # optional API key
GOFILE_TOKEN=             # optional API token
GOFILE_FOLDER_ID=
GOFILE_UPLOAD_ENDPOINTS=  # optional comma separated upload hosts
QBITTORRENT_HOST=http://localhost
QBITTORRENT_PORT=8080
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=adminadmin
QBITTORRENT_CATEGORY=
MIRROR_STATUS_INTERVAL=5
MIRROR_DOWNLOAD_DIR=downloads/mirror
```

> **Security Tip:** Always keep these secret values outside of version control. If credentials have ever been exposed, rotate them immediately and update this file with placeholders only.

## 4. Migrate Legacy Data to MongoDB

If you're upgrading from the previous JSON-based storage:

```bash
python migrate_to_mongo.py
```

This imports the old `command_states.json`, `approved_users.json`, group settings, and notes into MongoDB. The script will skip missing files automatically.

## 5. Run the Bot

```bash
python bot.py
```

The bot requires the `BOT_TOKEN` and `ADMIN_CHAT_ID`. If either is missing, startup will fail with a clear error message.

## 6. Docker Compose (Optional)

`docker-compose.yml` expects the `.env` file. Launch with:

```bash
docker-compose up -d
```

This spins up the Telegram bot inside a lightweight Python Alpine container with your host's files mounted in. MongoDB must be reachable at `MONGODB_URI`.

## 7. Keepalived High-Availability Setup

For active/backup failover using Keepalived:

1. Place `bot_ha.sh` at `/etc/keepalived/bot_ha.sh` (or adjust the path in `notify_master/notify_backup`). Ensure it's executable:
   ```bash
   sudo cp bot_ha.sh /etc/keepalived/bot_ha.sh
   sudo chmod +x /etc/keepalived/bot_ha.sh
   ```

2. Install Keepalived:
   ```bash
   sudo apt-get install keepalived
   ```

3. Copy `keepalived.conf` to `/etc/keepalived/keepalived.conf` and adjust the parameters:
   - `state`: set `MASTER` on the primary node and `BACKUP` on the secondary.
   - `interface`: the network interface hosting the floating IP (e.g., `eth0`, `ens160`).
   - `priority`: higher on the primary (e.g., primary `101`, secondary `100`).
   - `auth_pass`: change `"CHANGE_ME"` to a shared secret, identical on both nodes.
   - `virtual_ipaddress`: the floating IP to be taken over.

4. Enable script security (already in `global_defs`), start Keepalived, and check status:
   ```bash
   sudo systemctl enable keepalived
   sudo systemctl restart keepalived
   sudo systemctl status keepalived
   ```

5. Logs from the `bot_ha.sh` script are written to `/var/log/bot_ha.log`. On master elections, the script starts `python3 bot.py`; on backup, it stops the instance.

## 8. Useful Commands

- Check MongoDB collections:
  ```python
  from settings import settings
  from database import get_collection
  import asyncio

  async def inspect():
      cfg = await get_collection('bot_config').find_one({'_id': 'global'})
      print(cfg)

  asyncio.run(inspect())
  ```

- Update approved users via bot commands:
- `/approve` (reply to user or /approve <user_id>)
- `/revoke`
- `/listcommands` (admin): view toggle states for global commands via `/enable`/`/disable`.
- `/mirror` mirrors media in two ways:
  - Reply to a Telegram document/audio/video/photo.
  - Or run `/mirror <direct-file-url>`.
  The file is downloaded locally, uploaded to PixelDrain or GoFile, and the
  link is returned before the local copy is deleted. Configure the targets with
  `UPLOAD_TARGETS` (comma-separated rotation) or fall back to `UPLOAD_TARGET`,
  and optionally provide API credentials for uploading into
  your own account/folder.
  Torrents and magnets are handled through qBittorrent; set `QBITTORRENT_*`
  variables to point at your Web UI. Progress messages are updated every few
  seconds (`MIRROR_STATUS_INTERVAL`).
- `/cancel [task_id]` lets the task owner (or admin) stop an active mirror job. Reply to
  the status message or provide the task ID shown in the log.

## 9. Maintenance Tips

- Because MongoDB now stores all persistent state, regular backups are recommended (e.g., MongoDB Atlas snapshots or `mongodump`).
- Rotate the API keys periodically and update `.env` accordingly.
- If you change the floating IP or interface, update `keepalived.conf` on both nodes and restart Keepalived.
- When adding new commands that should be toggleable, update `command_registry.py` so they can be controlled via `/enable`/`/disable`.

With this setup, your Telegram bot can run in a redundant environment with all configuration and state centralized in MongoDB. 🎉
