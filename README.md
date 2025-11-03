# Telegram Bot Deployment Guide

## 1. Prerequisites

- Python 3.10+
- MongoDB Atlas cluster (or self-hosted MongoDB)
- Telegram bot token
- Optional: remove.bg API key, Gemini API key, YouTube API key
- **Keepalived (for multi-node high availability)**
- **Tailscale (for private mesh connectivity between nodes)**

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

Create a `.env` file at the project root (or copy `.env.example`) and set your secrets:

```ini
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
ADMIN_CHAT_ID=123456789
YT_API=YOUR_YOUTUBE_API_KEY
BOT_USERNAME=your_bot_username
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
REMOVE_BG_API_KEY=your_remove_bg_api_key
MONGODB_URI=your_mongodb_connection_string
MONGODB_DB_NAME=telegram_bot

UPLOAD_TARGET=pixeldrain
UPLOAD_TARGETS=pixeldrain,gofile
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

> **Security Tip:** Do **not** commit `.env` to Git.  
> Rotate your tokens and keys periodically for security.

---

## 4. Migrate Legacy Data to MongoDB

If upgrading from an older version that used JSON-based storage:

```bash
python migrate_to_mongo.py
```

This imports your legacy `command_states.json`, `approved_users.json`, and related data into MongoDB.

---

## 5. Run the Bot (Single Instance)

To test locally:

```bash
python bot.py
```

If `BOT_TOKEN` or `ADMIN_CHAT_ID` are missing, startup will fail with an explicit error message.

---

## 6. Docker Compose (Optional)

You can run the bot inside Docker:

```bash
docker-compose up -d
```

Your `.env` file is automatically loaded.  
Ensure MongoDB is reachable via the `MONGODB_URI` specified.

---

## 7. Keepalived High-Availability Setup (Tailscale Mesh Cluster)

Your HA setup runs across three nodes connected with **Tailscale**.  
Keepalived ensures only one node (the MASTER) runs the bot at any time.

| Node | Role | Tailscale IP |
|------|------|--------------|
| Oracle Cloud | **MASTER** | `100.89.244.74` |
| 192.168.5.245 | BACKUP 1 | `100.106.162.6` |
| 192.168.5.239 | BACKUP 2 | `100.90.27.12` |

### Step 1: Install and connect Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh --accept-dns=false
tailscale status
```

Verify connectivity:
```bash
tailscale ping 100.89.244.74
tailscale ping 100.106.162.6
tailscale ping 100.90.27.12
```

### Step 2: Install Keepalived and the control script

```bash
sudo apt-get install -y keepalived
sudo cp bot_ha.sh /etc/keepalived/bot_ha.sh
sudo chmod +x /etc/keepalived/bot_ha.sh
```

### Step 3: Keepalived configuration

Each node uses `/etc/keepalived/keepalived.conf` with its own `state`, `priority`, and `unicast_src_ip`.

#### Oracle (MASTER)

```conf
global_defs {
  router_id BOT_ORACLE
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
  state MASTER
  interface tailscale0
  virtual_router_id 51
  priority 160
  advert_int 1

  unicast_src_ip 100.89.244.74
  unicast_peer {
    100.106.162.6
    100.90.27.12
  }

  track_script { check_bot }

  notify_master "/etc/keepalived/bot_ha.sh master"
  notify_backup "/etc/keepalived/bot_ha.sh backup"
  notify_fault  "/etc/keepalived/bot_ha.sh fault"
}
```

#### 245 (BACKUP 1)

Change to:
```
state BACKUP
priority 120
unicast_src_ip 100.106.162.6
```

#### 239 (BACKUP 2)

Change to:
```
state BACKUP
priority 100
unicast_src_ip 100.90.27.12
```

All share the same peer list.

> **Note:** There is **no VIP** here; Keepalived manages service leadership only.

---

### Step 4: Enable and start Keepalived

```bash
sudo systemctl enable keepalived
sudo systemctl restart keepalived
sudo systemctl status keepalived
```

Check leader:
```bash
journalctl -u keepalived -n 30 --no-pager | grep MASTER
```

---

### Step 5: Systemd service for the bot

Create `/etc/systemd/system/telegram-bot.service`:

```ini
[Unit]
Description=Telegram Bot
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=root
WorkingDirectory=/root/telegram-bot
ExecStart=/usr/local/bin/run-telegram-bot.sh
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
```

---

### Step 6: Failover testing

1. Stop Keepalived on Oracle:
   ```bash
   sudo systemctl stop keepalived
   ```
   Within seconds, node 245 becomes MASTER.

2. Restart Oracle Keepalived to reclaim MASTER:
   ```bash
   sudo systemctl start keepalived
   ```

---

### Step 7: How it works

- Only one node runs `telegram-bot` (the MASTER).  
- Backup nodes stay in sync and take over if the MASTER fails.  
- Health checks use `systemctl is-active telegram-bot`.  
- All communication is over secure Tailscale IPs.

---

## 8. Useful Commands

**Check MongoDB collections:**
```python
from settings import settings
from database import get_collection
import asyncio

async def inspect():
    cfg = await get_collection('bot_config').find_one({'_id': 'global'})
    print(cfg)

asyncio.run(inspect())
```

**Bot management commands (in Telegram):**
- `/approve`, `/revoke`, `/listcommands`
- `/mirror`, `/cancel`, `/enable`, `/disable`

---

## 9. Maintenance Tips

- Back up MongoDB regularly (`mongodump` or Atlas snapshots).
- Rotate API keys periodically.
- If you change Tailscale IPs, update all `keepalived.conf` files.
- Logs from HA scripts appear in `journalctl -u keepalived` and `/var/log/syslog`.

---

With this setup, your Telegram bot runs in a **3-node high-availability cluster** over **Tailscale**, with seamless failover and centralized MongoDB state. 🎯
