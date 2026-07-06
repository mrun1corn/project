from telegram.ext import CommandHandler
from .handlers import bot_start, jaan

def register(application):
    application.add_handler(CommandHandler("start", bot_start))
    application.add_handler(CommandHandler("jaan", jaan))
