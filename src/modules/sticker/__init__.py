from telegram.ext import CommandHandler
from .handlers import kang

def register(application):
    application.add_handler(CommandHandler("kang", kang))
