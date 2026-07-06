import ipaddress

from telegram import Update
from telegram.ext import ContextTypes


def calculate_subnet(ip, subnet_mask):
    try:
        network = ipaddress.ip_network(f"{ip}/{subnet_mask}", strict=False)
        return {
            "network_address": str(network.network_address),
            "broadcast_address": str(network.broadcast_address),
            "host_range": f"{network.network_address + 1} - {network.broadcast_address - 1}",
            "total_hosts": network.num_addresses - 2,
        }
    except ValueError as exc:
        return str(exc)


async def subnet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        if len(context.args) not in {1, 2}:
            await update.message.reply_text(
                "<b>Subnet Calculator</b>\nUse <code>/subnet &lt;ip&gt; &lt;subnet_mask&gt;</code> or <code>/subnet &lt;ip/cidr&gt;</code>.",
                parse_mode="HTML",
            )
            return

        if len(context.args) == 1:
            ip = context.args[0].split('/')[0]
            subnet_mask = context.args[0].split('/')[1] if '/' in context.args[0] else None
        else:
            ip = context.args[0]
            subnet_mask = context.args[1]

        result = calculate_subnet(ip, subnet_mask)

        if isinstance(result, dict):
            response = (
                "<b>Subnet Result</b>\n"
                f"🌐 Network Address: <code>{result['network_address']}</code>\n"
                f"📡 Broadcast Address: <code>{result['broadcast_address']}</code>\n"
                f"🧭 Host Range: <code>{result['host_range']}</code>\n"
                f"👥 Total Hosts: <code>{result['total_hosts']}</code>"
            )
            await update.message.reply_text(response, parse_mode="HTML")
        else:
            await update.message.reply_text(
                f"<b>Subnet Calculation Failed</b>\n<code>{result}</code>",
                parse_mode="HTML",
            )
    except Exception as exc:
        print(f"Error in subnet_command: {exc}")
