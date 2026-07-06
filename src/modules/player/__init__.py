from telegram.ext import CommandHandler, MessageHandler, filters
from .music_video import play_audio, play_video
from .reels import VIDEO_URL_REGEX, handle_video_link

def register(application):
    application.add_handler(CommandHandler("music", play_audio))
    application.add_handler(CommandHandler("video", play_video))
    application.add_handler(MessageHandler(filters.Regex(VIDEO_URL_REGEX) & ~filters.COMMAND, handle_video_link))
