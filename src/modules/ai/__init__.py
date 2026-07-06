from telegram.ext import CommandHandler
from .handlers import ai_command

def register(application):
    application.add_handler(CommandHandler("ai", ai_command))
