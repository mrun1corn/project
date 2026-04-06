# Telegram Bot Deployment Guide

## 1. Prerequisites

- Python 3.10+
- MongoDB Atlas cluster or self-hosted MongoDB
- Telegram bot token
- Optional API keys for remove.bg and Gemini
- Optional qBittorrent for torrent-based mirroring
- Optional Keepalived plus Tailscale for active/passive failover

---

## 2. Clone and Install Dependencies

```bash
git clone <repo-url> telegram-bot
cd telegram-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 3. Environment Configuration

Create a `.env` file at the project root or copy `.env.example`.

```ini
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
ADMIN_CHAT_ID=123456789
YT_API=YOUR_YOUTUBE_API_KEY
BOT_USERNAME=your_bot_username
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
REMOVE_BG_API_KEY=YOUR_REMOVE_BG_API_KEY
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=telegram_bot
UPLOAD_TARGET=pixeldrain
UPLOAD_TARGETS=
PIXELDRAIN_KEY=
GOFILE_TOKEN=
GOFILE_FOLDER_ID=
GOFILE_UPLOAD_ENDPOINTS=
QBITTORRENT_HOST=http://localhost
QBITTORRENT_PORT=8080
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=adminadmin
QBITTORRENT_CATEGORY=
MIRROR_STATUS_INTERVAL=5
MIRROR_DOWNLOAD_DIR=downloads/mirror
```

Security tip: never commit `.env` to Git, and rotate credentials periodically.

---

## 4. Optional Legacy Migration

If you are upgrading from an older JSON-backed deployment, you can run:

```bash
python migrate_to_mongo.py
```

The migration script only imports legacy files if they exist, for example `command_states.json`, `approved_users.json`, `group_management_command_states.json`, and `notes_command_states.json`.

---

## 5. Run the Bot

Run a single polling instance:

```bash
python bot.py
```

If `BOT_TOKEN` is missing, startup fails immediately. If `ADMIN_CHAT_ID` is missing, the bot still starts but admin approvals and notifications will not work correctly.

---

## 6. Docker Compose

Use Docker Compose only for a single polling instance:

```bash
docker-compose up -d
```

The checked-in Compose file intentionally runs one bot container because Telegram long polling should not be scaled horizontally with multiple replicas on the same bot token.

---

## 7. Keepalived High Availability

This repo uses an active/passive design. Only one node should run `telegram-bot` at a time.

### Example `keepalived.conf`

Each node uses the same structure and changes only its `state`, `priority`, and `unicast_src_ip`.

```conf
global_defs {
  router_id BOT_NODE
  script_user root
  enable_script_security
}

vrrp_script check_bot {
  script "/bin/systemctl is-active --quiet telegram-bot"
  interval 3
  weight -40
  fall 2
  rise 2
}

vrrp_instance VI_1 {
  state BACKUP
  interface tailscale0
  virtual_router_id 51
  priority 100
  advert_int 1

  unicast_src_ip 100.89.244.74
  unicast_peer {
    100.106.162.6
    100.90.27.12
  }

  track_script {
    check_bot
  }

  notify_master "/etc/keepalived/bot_ha.sh master"
  notify_backup "/etc/keepalived/bot_ha.sh backup"
  notify_fault "/etc/keepalived/bot_ha.sh fault"
}
```

Notes:
- There is no floating VIP in this setup.
- Keepalived only manages service leadership.
- The helper script starts and stops the `telegram-bot` systemd service.

### Example systemd service

Create `/etc/systemd/system/telegram-bot.service`:

```ini
[Unit]
Description=Telegram Bot
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=root
WorkingDirectory=/root/telegram-bot
ExecStart=/usr/bin/python3 /root/telegram-bot/bot.py
Restart=always
RestartSec=2
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable telegram-bot
sudo systemctl restart telegram-bot
```

---

## 8. Useful Commands

Bot management commands in Telegram:
- `/approve`, `/revoke`, `/listcommands`
- `/mirror`, `/cancel`, `/enable`, `/disable`
- `/group_manage`, `/notes_manage`

---

## 9. Maintenance Tips

- Back up MongoDB regularly.
- Rotate API keys periodically.
- Keep only one polling bot active for a given token.
- If Tailscale IPs change, update all Keepalived peer definitions.
- Keepalived helper logs go to `/var/log/bot_ha.log`.
