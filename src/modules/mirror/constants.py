ALLOWED_TARGETS = {"pixeldrain", "gofile", "cloudflare", "r2", "cloudflare_r2"}
TARGET_LABELS = {
    "pixeldrain": "PixelDrain",
    "gofile": "GoFile",
    "cloudflare": "Cloudflare R2",
    "r2": "Cloudflare R2",
    "cloudflare_r2": "Cloudflare R2",
}
CANCEL_CALLBACK_PREFIX = "mirror_cancel"
STATUS_EMOJIS = {
    "queued": "🟡",
    "downloading": "⬇️",
    "uploading": "⬆️",
    "compressing": "🗜️",
    "cancelling": "⏹️",
    "cancelled": "🚫",
    "completed": "✅",
    "error": "❌",
}
