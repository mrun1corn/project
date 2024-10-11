from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from hello import bot_start
from subcal import subnet
from help import help
from systemstatus import bot_status, system_status, speedtest, ping, shell, reboot
from comm_checker import enable_command, disable_command, approve_user, revoke_user
from player import play_audio, play_video
#from ttt import ttt, make_move
#from ttt import register_ttt_handlers

from config import BOT_TOKEN, ADMIN_CHAT_ID

def main() -> None:
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Register commands
    application.add_handler(CommandHandler('start', bot_start))
    application.add_handler(CommandHandler('subnet', subnet))
    application.add_handler(CommandHandler('help', help))
    application.add_handler(CommandHandler('status', bot_status))
    application.add_handler(CommandHandler('sysinfo', system_status))
    application.add_handler(CommandHandler('speedtest', speedtest))
    application.add_handler(CommandHandler('ping', ping))
    application.add_handler(CommandHandler('reboot', reboot))
    application.add_handler(CommandHandler('music', play_audio))
    application.add_handler(CommandHandler('video', play_video))
    application.add_handler(CommandHandler("enable", enable_command))
    application.add_handler(CommandHandler("disable", disable_command))
    application.add_handler(CommandHandler("approve", approve_user))
    application.add_handler(CommandHandler("revoke", revoke_user))
    application.add_handler(CommandHandler("shell", shell))
    
    # Register commands
#    application.add_handler(CommandHandler('ttt', ttt))
#    application.add_handler(CallbackQueryHandler(make_move))  # Handle button presses

    # Register Tic Tac Toe handlers
#    register_ttt_handlers(application)

    # Run the bot
    application.run_polling()

if __name__ == '__main__':
    main()
