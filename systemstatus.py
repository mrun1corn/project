from telegram import Update
from telegram.ext import ContextTypes
import psutil
import time
import speedtest as speedtest_lib
import subprocess
import os
import sys
import platform
from comm_checker import command_states, check_user_approval
from config import ADMIN_CHAT_ID

# Global variable to track bot uptime
bot_start_time = time.time()

async def bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send bot uptime and basic status."""
    try:
        uptime = time.time() - bot_start_time
        uptime_str = time.strftime("%Hh %Mm %Ss", time.gmtime(uptime))
        
        response = (
            f"🤖 *Bot Status*\n"
            f"• Uptime: `{uptime_str}`\n"
            f"• System: `{platform.system()} {platform.release()}`"
        )
        
        await update.message.reply_text(response, parse_mode="MarkdownV2")
    except Exception as e:
        await update.message.reply_text("❌ Failed to retrieve bot status.")

async def system_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send detailed system metrics."""
    if not await check_user_approval(update.effective_user.id):
        await update.message.reply_text("🔒 You are not approved to use this command.")
        return

    try:
        # System metrics
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        swap = psutil.swap_memory()
        
        # Formatting helper
        def format_bytes(size):
            return f"{size / (1024**3):.2f} GB"

        response = (
            f"🖥️ *System Status*\n"
            f"• CPU Usage: `{cpu}%`\n"
            f"• Memory: `{mem.percent}%` ({format_bytes(mem.used)} used)\n"
            f"• Swap: `{swap.percent}%` ({format_bytes(swap.used)} used)\n"
            f"• Disk: `{disk.percent}%` ({format_bytes(disk.used)} used)"
        )

        # Battery status (if available)
        if hasattr(psutil, "sensors_battery"):
            battery = psutil.sensors_battery()
            if battery:
                status = "🔌 Charging" if battery.power_plugged else "🔋 Discharging"
                response += f"\n• Battery: `{battery.percent}%` ({status})"

        await update.message.reply_text(response, parse_mode="MarkdownV2")
    except Exception as e:
        await update.message.reply_text("❌ Failed to retrieve system status.")

async def speedtest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run a speed test with progress updates."""
    if not await check_user_approval(update.effective_user.id):
        await update.message.reply_text("🔒 You are not approved to use this command.")
        return
        
    if not command_states.get('speedtest', True) and update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ Speedtest command is disabled.")
        return

    try:
        msg = await update.message.reply_text("⏳ Finding optimal server...")
        
        st = speedtest_lib.Speedtest()
        st.get_best_server()
        
        await msg.edit_text("📥 Testing download speed...")
        download = st.download() / 10**6  # Convert to Mbps
        
        await msg.edit_text("📤 Testing upload speed...")
        upload = st.upload() / 10**6
        
        await msg.edit_text(
            f"🚀 *Speed Test Results*\n"
            f"• Download: `{download:.2f} Mbps`\n"
            f"• Upload: `{upload:.2f} Mbps`",
            parse_mode="MarkdownV2"
        )
    except speedtest_lib.ConfigRetrievalError:
        await msg.edit_text("❌ Could not connect to speedtest servers.")
    except Exception as e:
        await msg.edit_text("❌ Speed test failed.")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ping a host with error handling."""
    if not await check_user_approval(update.effective_user.id):
        await update.message.reply_text("🔒 You are not approved to use this command.")
        return
        
    if not command_states.get('ping', True) and update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ Ping command is disabled.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /ping <hostname>")
        return

    host = context.args[0]
    msg = await update.message.reply_text(f"🔄 Pinging `{host}`...", parse_mode="MarkdownV2")

    try:
        count = 4 if os.name == 'posix' else 2  # Fewer pings on Windows
        result = subprocess.run(
            ['ping', '-c', str(count), host] if os.name == 'posix' else ['ping', '-n', str(count), host],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        if result.returncode == 0:
            await msg.edit_text(f"✅ Ping to `{host}` successful!\n```\n{result.stdout}\n```", parse_mode="MarkdownV2")
        else:
            await msg.edit_text(f"❌ Ping to `{host}` failed:\n```\n{result.stderr}\n```", parse_mode="MarkdownV2")
    except subprocess.TimeoutExpired:
        await msg.edit_text(f"⌛ Ping to `{host}` timed out.")
    except Exception as e:
        await msg.edit_text(f"❌ Error pinging `{host}`.")

async def reboot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Safely reboot the bot with admin checks."""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("🔒 Admin permission required.")
        return
        
    if not command_states.get('reboot', True):
        await update.message.reply_text("❌ Reboot command is disabled.")
        return

    try:
        await update.message.reply_text("🔄 Rebooting bot...")
        
        # Graceful restart
        python = sys.executable
        os.execl(python, python, *sys.argv)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Reboot failed: {str(e)}")