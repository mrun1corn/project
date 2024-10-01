from telegram import Update
from telegram.ext import ContextTypes
import psutil
import time
import speedtest as speedtest_lib  # Renamed the imported speedtest library
import subprocess
import os
import sys
import platform
from comm_checker import command_states, check_user_approval 
from config import ADMIN_CHAT_ID

# Global variable to keep track of bot start time
bot_start_time = time.time()

async def bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the current status and uptime of the bot."""
    try:
        # Calculate uptime
        uptime = time.time() - bot_start_time
        uptime_str = time.strftime("%H:%M:%S", time.gmtime(uptime))
        
        # Prepare response message
        response = (
            f"Bot Status: Running\n"
            f"Uptime: {uptime_str}\n"
        )

        await context.bot.send_message(chat_id=update.effective_chat.id, text=response)
    except Exception as e:
        print(f"Error in bot_status: {e}")

async def system_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the current system status including CPU, memory, and disk usage."""
    if not await check_user_approval(update.effective_user.id):  # Check if the user is approved
        await update.message.reply_text("You are not approved to use this command.")
        return

    try:
        # Get system information
        cpu_usage = psutil.cpu_percent(interval=1)
        memory_info = psutil.virtual_memory()
        swap_info = psutil.swap_memory()
        disk_info = psutil.disk_usage('/')
        cpu_count = psutil.cpu_count(logical=False)  # Physical cores
        cpu_count_logical = psutil.cpu_count(logical=True)  # Logical CPUs
        cpu_freq = psutil.cpu_freq().current  # CPU frequency
        cpu_model = platform.processor()  # CPU model

        # System information
        system = platform.system()  # Operating System
        node = platform.node()  # System name (hostname)
        release = platform.release()  # OS version
        architecture = platform.architecture()[0]  # Architecture (32-bit/64-bit)

        # Prepare response message
        response = (
            f"*System Status*\n"
            f"🖥️ *System:* {system} {release} ({architecture})\n"
            f"🔧 *Hostname:* {node}\n"
            f"⚙️ *CPU Model:* `{cpu_model}`\n"
            f"🧮 *Physical Cores:* {cpu_count}\n"
            f"🔢 *Logical CPUs:* {cpu_count_logical}\n"
            f"🔄 *CPU Frequency:* {cpu_freq:.2f} MHz\n"
            f"📊 *CPU Usage:* {cpu_usage}%\n"
            f"🧠 *Memory Usage:* {memory_info.percent}% "
            f"({memory_info.used / (1024 ** 2):.2f} MB used of {memory_info.total / (1024 ** 2):.2f} MB)\n"
            f"🔄 *Swap Memory Usage:* {swap_info.percent}% "
            f"({swap_info.used / (1024 ** 2):.2f} MB used of {swap_info.total / (1024 ** 2):.2f} MB)\n"
            f"💾 *Disk Usage:* {disk_info.percent}% "
            f"({disk_info.used / (1024 ** 3):.2f} GB used of {disk_info.total / (1024 ** 3):.2f} GB)\n"
        )

        # Check for battery info and append if available
        battery = psutil.sensors_battery()
        if battery:
            battery_status = f"🔋 *Battery Status:* {battery.percent}% {'🔌' if battery.power_plugged else '⚡'}\n"
            response += battery_status  # Append battery status to response

        # Escape special characters in response for MarkdownV2
        response = response.replace(".", "\\.").replace("-", "\\-").replace("_", "\\_").replace("*", "\\*") \
                           .replace("[", "\\[").replace("]", "\\]").replace("(", "\\(").replace(")", "\\)") \
                           .replace("~", "\\~").replace("`", "\\`")

        # Send the response using MarkdownV2
        await context.bot.send_message(chat_id=update.effective_chat.id, text=response, parse_mode='MarkdownV2')
    except Exception as e:
        print(f"Error in system_status: {e}")

async def speedtest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Conduct a speed test and send the results."""
    if not await check_user_approval(update.effective_user.id):  # Check if the user is approved
        await update.message.reply_text("You are not approved to use this command.")
        return
    if not command_states.get('speedtest', True) and update.effective_user.id != ADMIN_CHAT_ID:  # Check if command is disabled for non-admins
        await update.message.reply_text("The speedtest command is currently disabled.")
        return

    message = await context.bot.send_message(chat_id=update.effective_chat.id, text="Finding the best server...")

    try:
        st = speedtest_lib.Speedtest()
        st.get_best_server()  # Simulate server finding

        await message.edit_text("Testing download speed...")
        download_speed = st.download() / (10**6)  # Convert to Mbps

        await message.edit_text("Testing upload speed...")
        upload_speed = st.upload() / (10**6)  # Convert to Mbps

        response = (
            f"Download Speed: {download_speed:.2f} Mbps\n"
            f"Upload Speed: {upload_speed:.2f} Mbps\n"
        )
        await message.edit_text(response)  # Edit the message with the final results

    except speedtest_lib.ConfigRetrievalError:
        await message.edit_text("Error retrieving speed test configuration. Please try again later.")
        print("ConfigRetrievalError: Unable to access speed test server configuration.")
    except Exception as e:
        await message.edit_text("Error performing speed test. Please check your connection.")
        print(f"Error in speedtest: {e}")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ping a hostname and send the results."""
    if not await check_user_approval(update.effective_user.id):  # Check if the user is approved
        await update.message.reply_text("You are not approved to use this command.")
        return
    if not command_states.get('ping', True) and update.effective_user.id != ADMIN_CHAT_ID:  # Check if command is disabled for non-admins
        await update.message.reply_text("The ping command is currently disabled.")
        return
    
    if len(context.args) == 0:
        await update.message.reply_text('Usage: /ping <hostname>')
        return

    hostname = context.args[0]
    message = await context.bot.send_message(chat_id=update.effective_chat.id, text="Pinging...")

    try:
        # Check the platform and set parameters accordingly
        param = '-n' if os.name == 'nt' else '-c'  # Windows uses -n, Unix/Linux uses -c
        
        result = subprocess.run(['ping', param, '4', hostname], capture_output=True, text=True)

        # Informing user about results
        if result.returncode == 0:
            await message.edit_text(f"Ping successful!\n{result.stdout}")
        else:
            await message.edit_text(f"Ping failed:\n{result.stderr}")
    except Exception as e:
        await message.edit_text("Error performing ping. Please check your hostname.")
        print(f"Error in ping: {e}")

async def reboot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reboot the bot."""
    if not command_states.get('reboot', True) and update.effective_user.id != ADMIN_CHAT_ID:  # Check if command is disabled for non-admins
        await update.message.reply_text("The reboot command is currently disabled.")
        return

    await context.bot.send_message(chat_id=update.effective_chat.id, text="Rebooting bot... Please wait...")

    # Replaces the current process with a new one, ensuring the bot runs with the latest changes
    await context.bot.send_message(chat_id=update.effective_chat.id, text="The bot is restarting with the latest changes! 🎉")
    
    # Restart the bot by replacing the current process with a new one
    os.execv(sys.executable, [sys.executable] + sys.argv)

