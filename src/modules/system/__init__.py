from telegram.ext import CommandHandler
from .status import bot_status, system_status, speedtest, ping, reboot
from .subnet import subnet

def register(application):
    application.add_handler(CommandHandler("status", bot_status))
    application.add_handler(CommandHandler("sysinfo", system_status))
    application.add_handler(CommandHandler("speedtest", speedtest))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("reboot", reboot))
    application.add_handler(CommandHandler("subnet", subnet))
