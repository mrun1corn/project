import html
import os
import platform
import subprocess
import sys
import time

import psutil
import speedtest as speedtest_lib
from telegram import Update
from telegram.ext import ContextTypes

from src.core.guard import CommandSpec, guard_command


bot_start_time = time.time()


def _truncate_output(text: str, limit: int = 3500) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (output truncated)"


async def bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        uptime = time.time() - bot_start_time
        uptime_str = time.strftime("%Hh %Mm %Ss", time.gmtime(uptime))
        response = (
            "<b>Bot Status</b>\n"
            f"⏱️ Uptime: <code>{html.escape(uptime_str)}</code>\n"
            f"💻 System: <code>{html.escape(platform.system())} {html.escape(platform.release())}</code>\n"
            "💚 Health: <b>Running and responsive</b>"
        )
        await update.message.reply_text(response, parse_mode="HTML")
    except Exception:
        await update.message.reply_text("⚠️ I couldn't retrieve the bot status right now.")


async def system_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard_command(update, CommandSpec(name="sysinfo")):
        return

    try:
        cpu_usage = psutil.cpu_percent(interval=1)
        memory_info = psutil.virtual_memory()
        swap_info = psutil.swap_memory()
        disk_target = os.path.abspath(os.sep)
        disk_info = psutil.disk_usage(disk_target)
        cpu_count = psutil.cpu_count(logical=False)
        cpu_count_logical = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        cpu_freq_current = cpu_freq.current if cpu_freq else 0.0

        cpu_model = platform.processor()
        if not cpu_model:
            try:
                with open("/proc/cpuinfo", encoding="utf-8") as cpuinfo:
                    for line in cpuinfo:
                        if line.startswith("Hardware") or line.startswith("Model"):
                            cpu_model = line.split(":", 1)[1].strip()
                            break
            except Exception:
                cpu_model = "Unknown"

        response = (
            "<b>System Status</b>\n"
            f"🖥️ System: {html.escape(platform.system())} {html.escape(platform.release())} ({html.escape(platform.architecture()[0])})\n"
            f"🏷️ Hostname: <code>{html.escape(platform.node())}</code>\n"
            f"🧠 CPU Model: <code>{html.escape(cpu_model)}</code>\n"
            f"⚙️ Physical Cores: <code>{cpu_count}</code>\n"
            f"🧵 Logical CPUs: <code>{cpu_count_logical}</code>\n"
            f"📡 CPU Frequency: <code>{cpu_freq_current:.2f} MHz</code>\n"
            f"🔥 CPU Usage: <code>{cpu_usage}%</code>\n"
            f"🧮 Memory Usage: <code>{memory_info.percent}%</code> ({memory_info.used / (1024 ** 2):.2f} MB used of {memory_info.total / (1024 ** 2):.2f} MB)\n"
            f"💾 Swap Usage: <code>{swap_info.percent}%</code> ({swap_info.used / (1024 ** 2):.2f} MB used of {swap_info.total / (1024 ** 2):.2f} MB)\n"
            f"📦 Disk Usage: <code>{disk_info.percent}%</code> ({disk_info.used / (1024 ** 3):.2f} GB used of {disk_info.total / (1024 ** 3):.2f} GB)\n"
        )

        battery = psutil.sensors_battery()
        if battery:
            charging_state = "Charging" if battery.power_plugged else "On battery"
            response += f"🔋 Battery: <code>{battery.percent}%</code> ({html.escape(charging_state)})\n"

        await context.bot.send_message(chat_id=update.effective_chat.id, text=response, parse_mode="HTML")
    except Exception as exc:
        await update.message.reply_text(
            f"<b>System Status Failed</b>\n<code>{html.escape(str(exc))}</code>",
            parse_mode="HTML",
        )


async def speedtest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard_command(update, CommandSpec(name="speedtest", disabled_message="Speedtest command is disabled.")):
        return

    msg = await update.message.reply_text(
        "<b>Speed Test</b>\n🌐 Finding the best nearby server.",
        parse_mode="HTML",
    )
    try:
        st = speedtest_lib.Speedtest()
        st.get_best_server()

        await msg.edit_text(
            "<b>Speed Test</b>\n⬇️ Measuring download speed.",
            parse_mode="HTML",
        )
        download = st.download() / 10**6

        await msg.edit_text(
            "<b>Speed Test</b>\n⬆️ Measuring upload speed.",
            parse_mode="HTML",
        )
        upload = st.upload() / 10**6

        await msg.edit_text(
            f"<b>Speed Test Results</b>\n"
            f"⬇️ Download: <code>{download:.2f} Mbps</code>\n"
            f"⬆️ Upload: <code>{upload:.2f} Mbps</code>\n"
            "✅ Network check completed.",
            parse_mode="HTML",
        )
    except speedtest_lib.ConfigRetrievalError:
        await msg.edit_text("⚠️ I couldn't reach the speedtest servers right now.")
    except Exception as exc:
        await msg.edit_text(
            f"<b>Speed Test Failed</b>\n<code>{html.escape(str(exc))}</code>",
            parse_mode="HTML",
        )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard_command(update, CommandSpec(name="ping", usage="Usage: /ping <hostname>"), require_args=True):
        return

    host = context.args[0]
    msg = await update.message.reply_text(
        f"<b>Ping Test</b>\n🎯 Target: <code>{html.escape(host)}</code>",
        parse_mode="HTML",
    )

    try:
        count = 4 if os.name == "posix" else 2
        result = subprocess.run(
            ["ping", "-c", str(count), host] if os.name == "posix" else ["ping", "-n", str(count), host],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode == 0:
            await msg.edit_text(
                f"<b>Ping Succeeded</b>\n🎯 Target: <code>{html.escape(host)}</code>\n\n<pre>{html.escape(_truncate_output(result.stdout.strip()))}</pre>",
                parse_mode="HTML",
            )
        else:
            details = result.stderr.strip() or result.stdout.strip() or "No error output."
            await msg.edit_text(
                f"<b>Ping Failed</b>\n🎯 Target: <code>{html.escape(host)}</code>\n\n<pre>{html.escape(_truncate_output(details))}</pre>",
                parse_mode="HTML",
            )
    except subprocess.TimeoutExpired:
        await msg.edit_text(
            f"<b>Ping Timed Out</b>\n🎯 Target: <code>{html.escape(host)}</code>\n⏱️ The host did not respond in time.",
            parse_mode="HTML",
        )
    except Exception as exc:
        await msg.edit_text(
            f"<b>Ping Failed</b>\n🎯 Target: <code>{html.escape(host)}</code>\n<code>{html.escape(str(exc))}</code>",
            parse_mode="HTML",
        )


async def reboot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard_command(
        update,
        CommandSpec(
            name="reboot",
            admin_only=True,
            admin_message="Admin permission required.",
            disabled_message="Reboot command is disabled.",
        ),
    ):
        return

    try:
        await update.message.reply_text(
            "<b>Rebooting Bot</b>\n♻️ Restart sequence started. Please wait a moment.",
            parse_mode="HTML",
        )
        python = sys.executable
        os.execl(python, python, *sys.argv)
    except Exception as exc:
        await update.message.reply_text(
            f"<b>Reboot Failed</b>\n<code>{html.escape(str(exc))}</code>",
            parse_mode="HTML",
        )
