from telegram.ext import CommandHandler
from .handlers import remove_bg

def register(application):
    application.add_handler(CommandHandler("bgremove", remove_bg))
