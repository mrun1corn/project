import os
from dataclasses import dataclass
from dotenv import load_dotenv


load_dotenv()


@dataclass
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    admin_chat_id: int = int(os.getenv("ADMIN_CHAT_ID", "0") or "0")
    yt_api_key: str = os.getenv("YT_API", "")
    bot_username: str = os.getenv("BOT_USERNAME", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    remove_bg_api_key: str = os.getenv("REMOVE_BG_API_KEY", "")
    mongodb_uri: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    mongodb_db_name: str = os.getenv("MONGODB_DB_NAME", "telegram_bot")
    upload_target: str = os.getenv("UPLOAD_TARGET", "pixeldrain").lower()
    pixeldrain_key: str = os.getenv("PIXELDRAIN_KEY", "")
    gofile_token: str = os.getenv("GOFILE_TOKEN", "")
    gofile_folder_id: str = os.getenv("GOFILE_FOLDER_ID", "")
    qbittorrent_host: str = os.getenv("QBITTORRENT_HOST", "http://localhost")
    qbittorrent_port: int = int(os.getenv("QBITTORRENT_PORT", "8080") or 0)
    qbittorrent_username: str = os.getenv("QBITTORRENT_USERNAME", "admin")
    qbittorrent_password: str = os.getenv("QBITTORRENT_PASSWORD", "adminadmin")
    qbittorrent_category: str = os.getenv("QBITTORRENT_CATEGORY", "")
    mirror_status_interval: int = int(os.getenv("MIRROR_STATUS_INTERVAL", "5") or 5)
    mirror_download_dir: str = os.getenv("MIRROR_DOWNLOAD_DIR", os.path.join(os.getcwd(), "downloads", "mirror"))


settings = Settings()
