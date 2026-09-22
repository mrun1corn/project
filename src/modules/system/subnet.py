import html
import ipaddress

from telegram import Update
from telegram.ext import ContextTypes

from src.core.guard import CommandSpec, guard_command


def calculate_subnet(ip: str, subnet_mask: str | None = None) -> dict | str:
    try:
        expr = f"{ip}/{subnet_mask}" if subnet_mask else ip
        network = ipaddress.ip_network(expr, strict=False)
        num_addrs = network.num_addresses
        if num_addrs == 1:
            total_hosts = 1
            host_range = str(network.network_address)
        elif num_addrs == 2:
            total_hosts = 2
            host_range = f"{network.network_address} - {network.broadcast_address}"
        else:
            total_hosts = num_addrs - 2
            host_range = f"{network.network_address + 1} - {network.broadcast_address - 1}"

        return {
            "network_address": str(network.network_address),
            "broadcast_address": str(network.broadcast_address),
            "netmask": str(network.netmask),
            "host_range": host_range,
            "total_hosts": total_hosts,
        }
    except ValueError as exc:
        return str(exc)


async def subnet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard_command(
        update,
        CommandSpec(
            name="subnet",
            usage="Usage: <code>/subnet &lt;ip&gt; &lt;subnet_mask&gt;</code> or <code>/subnet &lt;ip/cidr&gt;</code>.",
        ),
        require_args=True,
    ):
        return

    try:
        if len(context.args) == 1:
            ip = context.args[0]
            subnet_mask = None
        elif len(context.args) == 2:
            ip = context.args[0]
            subnet_mask = context.args[1]
        else:
            await update.message.reply_text(
                "<b>Subnet Calculator</b>\nUse <code>/subnet &lt;ip&gt; &lt;subnet_mask&gt;</code> or <code>/subnet &lt;ip/cidr&gt;</code>.",
                parse_mode="HTML",
            )
            return

        result = calculate_subnet(ip, subnet_mask)

        if isinstance(result, dict):
            response = (
                "<b>Subnet Result</b>\n"
                f"🌐 Network Address: <code>{html.escape(result['network_address'])}</code>\n"
                f"🎭 Netmask: <code>{html.escape(result['netmask'])}</code>\n"
                f"📡 Broadcast Address: <code>{html.escape(result['broadcast_address'])}</code>\n"
                f"🧭 Host Range: <code>{html.escape(result['host_range'])}</code>\n"
                f"👥 Total Hosts: <code>{result['total_hosts']}</code>"
            )
            await update.message.reply_text(response, parse_mode="HTML")
        else:
            await update.message.reply_text(
                f"<b>Subnet Calculation Failed</b>\n<code>{html.escape(result)}</code>",
                parse_mode="HTML",
            )
    except Exception as exc:
        print(f"Error in subnet_command: {exc}")
