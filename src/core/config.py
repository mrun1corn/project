import os
from dataclasses import dataclass
from dotenv import load_dotenv
from typing import Tuple


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
    upload_targets: Tuple[str, ...] = ()
    upload_targets_defined: bool = False
    pixeldrain_key: str = os.getenv("PIXELDRAIN_KEY", "")
    gofile_token: str = os.getenv("GOFILE_TOKEN", "")
    gofile_folder_id: str = os.getenv("GOFILE_FOLDER_ID", "")
    gofile_upload_endpoints: Tuple[str, ...] = ()
    cloudflare_api_token: str = os.getenv("CLOUDFLARE_API_TOKEN", "") or os.getenv("CLOUDFLARE_TOKEN", "")
    cloudflare_account_id: str = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    cloudflare_r2_bucket: str = os.getenv("CLOUDFLARE_R2_BUCKET", "mirror")
    cloudflare_r2_public_url: str = os.getenv("CLOUDFLARE_R2_PUBLIC_URL", "")
    cloudflare_r2_access_key_id: str = os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID", "")
    cloudflare_r2_secret_access_key: str = os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "")
    qbittorrent_host: str = os.getenv("QBITTORRENT_HOST", "http://localhost")
    qbittorrent_port: int = int(os.getenv("QBITTORRENT_PORT", "8080") or 0)
    qbittorrent_username: str = os.getenv("QBITTORRENT_USERNAME", "admin")
    qbittorrent_password: str = os.getenv("QBITTORRENT_PASSWORD", "adminadmin")
    qbittorrent_category: str = os.getenv("QBITTORRENT_CATEGORY", "")
    mirror_status_interval: int = int(os.getenv("MIRROR_STATUS_INTERVAL", "5") or 5)
    mirror_download_dir: str = os.getenv("MIRROR_DOWNLOAD_DIR", os.path.join(os.getcwd(), "downloads", "mirror"))

    def __post_init__(self) -> None:
        raw_targets = os.getenv("UPLOAD_TARGETS", "")
        self.upload_targets_defined = bool(raw_targets.strip())
        if raw_targets:
            targets = tuple(
                target.strip().lower()
                for target in raw_targets.split(",")
                if target.strip()
            )
        else:
            fallback = self.upload_target or "pixeldrain"
            targets = (fallback,)

        if not targets:
            targets = ("pixeldrain",)

        self.upload_targets = targets

        if self.upload_target not in self.upload_targets:
            self.upload_target = self.upload_targets[0]

        raw_gofile_endpoints = os.getenv("GOFILE_UPLOAD_ENDPOINTS", "")
        if raw_gofile_endpoints.strip():
            endpoints = tuple(
                endpoint.strip()
                for endpoint in raw_gofile_endpoints.split(",")
                if endpoint.strip()
            )
        else:
            endpoints = ("https://upload.gofile.io/uploadfile",)
        self.gofile_upload_endpoints = endpoints


settings = Settings()
