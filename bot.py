from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from hello import bot_start, jaan
from subcal import subnet
from help import help
from systemstatus import bot_status, system_status, speedtest, ping, reboot
from comm_checker import enable_command, disable_command, approve_user, revoke_user
from player import play_audio, play_video
from config import BOT_TOKEN, ADMIN_CHAT_ID
from shell import register_shell_handlers
from bg_remove import remove_bg
from gemini import ai_command
from reel import handle_video_link

async def post_init(application):
    try:
        await application.bot.send_message(chat_id=ADMIN_CHAT_ID, text="🤖 Bot has started and is now online.")
    except Exception as e:
        print(f"Failed to send startup message to admin: {e}")


def main() -> None:
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .connection_pool_size(20)
        .build()
    )

    # Register commands
    application.add_handler(CommandHandler('start', bot_start))
    application.add_handler(CommandHandler('jaan', jaan))
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
    application.add_handler(CommandHandler('bgremove', remove_bg))
    application.add_handler(CommandHandler('ai', ai_command))

     # Register video/reel link handler
    video_url_pattern = r'https?://(www\.)?(fb\.watch/[\w\-]+/?|facebook\.com/reel/\d+/?|facebook\.com/share/v/[\w\-]+/?|facebook\.com/share/r/[\w\-]+/?|facebook\.com/[^/]+/videos/\d+/?|instagram\.com/reel/[\w\-]+/?)'
    application.add_handler(MessageHandler(filters.Regex(video_url_pattern) & ~filters.COMMAND, handle_video_link))

    register_shell_handlers(application)


    application.post_init = post_init

    print("Starting bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == '__main__':
    main()
