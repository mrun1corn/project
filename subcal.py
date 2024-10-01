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
            "total_hosts": network.num_addresses - 2,  # Exclude network and broadcast addresses
        }
    except ValueError as e:
        return str(e)

async def subnet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        if len(context.args) != 2 and len(context.args) != 1:
            await update.message.reply_text('Usage: /subnet <ip> <subnet_mask> or <ip/cidr>')
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
                f"Network Address: {result['network_address']}\n"
                f"Broadcast Address: {result['broadcast_address']}\n"
                f"Host Range: {result['host_range']}\n"
                f"Total Hosts: {result['total_hosts']}"
            )
        else:
            response = result  # This will be an error message

        await update.message.reply_text(response)
    except Exception as e:
        print(f"Error in subnet_command: {e}")
