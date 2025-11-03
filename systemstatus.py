from telegram import Update
from telegram.ext import ContextTypes
import psutil
import time
import speedtest as speedtest_lib
import subprocess
import os
import sys
import platform
import re
from comm_checker import check_user_approval, check_command_enabled
from settings import settings

# Global variable to track bot uptime
bot_start_time = time.time()

def escape_markdown_v2(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

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
    except Exception:
        await update.message.reply_text("❌ Failed to retrieve bot status.")

async def system_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the current system status including CPU, memory, and disk usage."""
    if not await check_user_approval(update.effective_user.id):  # Check if the user is approved
        await update.message.reply_text("You are not approved to use this command.")
        return

    try:
        cpu_usage = psutil.cpu_percent(interval=1)
        memory_info = psutil.virtual_memory()
        swap_info = psutil.swap_memory()
        disk_info = psutil.disk_usage('/')
        cpu_count = psutil.cpu_count(logical=False)
        cpu_count_logical = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        cpu_freq_current = cpu_freq.current if cpu_freq else 0.0

        cpu_model = platform.processor()
        if not cpu_model:
            try:
                with open('/proc/cpuinfo') as f:
                    for line in f:
                        if line.startswith('Hardware') or line.startswith('Model'):
                            cpu_model = line.split(':')[1].strip()
                            break
            except Exception:
                cpu_model = "Unknown"

        system = platform.system()
        node = platform.node()
        release = platform.release()
        architecture = platform.architecture()[0]

        response = (
            f"*System Status*\n"
            f"🖥️ *System:* {system} {release} ({architecture})\n"
            f"🔧 *Hostname:* {node}\n"
            f"⚙️ *CPU Model:* `{cpu_model}`\n"
            f"🧮 *Physical Cores:* {cpu_count}\n"
            f"🔢 *Logical CPUs:* {cpu_count_logical}\n"
            f"🔄 *CPU Frequency:* {cpu_freq_current:.2f} MHz\n"
            f"📊 *CPU Usage:* {cpu_usage}%\n"
            f"🧠 *Memory Usage:* {memory_info.percent}% "
            f"({memory_info.used / (1024 ** 2):.2f} MB used of {memory_info.total / (1024 ** 2):.2f} MB)\n"
            f"🔄 *Swap Memory Usage:* {swap_info.percent}% "
            f"({swap_info.used / (1024 ** 2):.2f} MB used of {swap_info.total / (1024 ** 2):.2f} MB)\n"
            f"💾 *Disk Usage:* {disk_info.percent}% "
            f"({disk_info.used / (1024 ** 3):.2f} GB used of {disk_info.total / (1024 ** 3):.2f} GB)\n"
        )

        battery = psutil.sensors_battery()
        if battery:
            battery_status = f"🔋 *Battery Status:* {battery.percent}% {'🔌' if battery.power_plugged else '⚡'}\n"
            response += battery_status

        response_escaped = escape_markdown_v2(response)

        await context.bot.send_message(chat_id=update.effective_chat.id,
                                       text=response_escaped,
                                       parse_mode='MarkdownV2')
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to retrieve system status:\n`{str(e)}`", parse_mode='MarkdownV2')

async def speedtest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run a speed test with progress updates."""
    if not await check_user_approval(update.effective_user.id):
        await update.message.reply_text("🔒 You are not approved to use this command.")
        return
        
    if not await check_command_enabled('speedtest') and update.effective_user.id != settings.admin_chat_id:
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
    except Exception:
        await msg.edit_text("❌ Speed test failed.")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ping a host with error handling."""
    if not await check_user_approval(update.effective_user.id):
        await update.message.reply_text("🔒 You are not approved to use this command.")
        return
        
    if not await check_command_enabled('ping') and update.effective_user.id != settings.admin_chat_id:
        await update.message.reply_text("❌ Ping command is disabled.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /ping <hostname>")
        return

    host = context.args[0]
    msg = await update.message.reply_text(f"🔄 Pinging {host}")

    try:
        count = 4 if os.name == 'posix' else 2  # Fewer pings on Windows
        result = subprocess.run(
            ['ping', '-c', str(count), host] if os.name == 'posix' else ['ping', '-n', str(count), host],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        if result.returncode == 0:
            await msg.edit_text(f"✅ Ping to {host} successful!\n\n{result.stdout}\n")
        else:
            await msg.edit_text(f"❌ Ping to {host} failed:\n\n{result.stderr}\n")
    except subprocess.TimeoutExpired:
        await msg.edit_text(f"⌛ Ping to {host} timed out.")
    except Exception:
        await msg.edit_text(f"❌ Error pinging {host}.")

async def reboot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Safely reboot the bot with admin checks."""
    user_id = update.effective_user.id
    
    if user_id != settings.admin_chat_id:
        await update.message.reply_text("🔒 Admin permission required.")
        return
        
    if not await check_command_enabled('reboot'):
        await update.message.reply_text("❌ Reboot command is disabled.")
        return

    try:
        await update.message.reply_text("🔄 Rebooting bot...")
        
        # Graceful restart
        python = sys.executable
        os.execl(python, python, *sys.argv)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Reboot failed: {str(e)}")
