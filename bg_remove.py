import requests
import os
from telegram import Update
from telegram.ext import ContextTypes
from config import BOT_TOKEN, ADMIN_CHAT_ID  # Ensure your BOT_TOKEN, ADMIN_CHAT_ID, and other configurations are properly managed.
from comm_checker import check_user_approval, command_states  # Import user approval checker

REMOVE_BG_API_KEY = "B1L9Ed7WzQxrub2R5Y4vDLnC"  # Replace this with your API key

async def remove_bg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if user_id != ADMIN_CHAT_ID and not command_states.get('bgremove', True):
        await update.message.reply_text("❌ Background removal command is disabled.")
        return

    # Allow admins to bypass approval checks
    if user_id != ADMIN_CHAT_ID and not await check_user_approval(user_id):
        await update.message.reply_text("You are not approved to use this command.")
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text("Please reply to an image with /bgremove to remove its background.")
        return

    # Get the largest resolution photo
    photo_file = await update.message.reply_to_message.photo[-1].get_file()
    photo_path = f"downloads/{photo_file.file_id}.jpg"  # Define a unique path for the photo
    await photo_file.download_to_drive(photo_path)

    try:
        # Send the image to the Remove.bg API
        with open(photo_path, 'rb') as image_file:
            response = requests.post(
                "https://api.remove.bg/v1.0/removebg",
                files={"image_file": image_file},
                data={"size": "auto"},
                headers={"X-Api-Key": REMOVE_BG_API_KEY},
            )

        if response.status_code == 200:
            output_file = f"downloads/{photo_file.file_id}_removed_bg.png"

            # Save the result
            with open(output_file, "wb") as out_file:
                out_file.write(response.content)

            # Send the processed image back to the user
            await context.bot.send_photo(
                chat_id=update.effective_chat.id, photo=open(output_file, "rb")
            )
        else:
            error_message = response.json().get("errors", [{}])[0].get("title", "An error occurred.")
            await update.message.reply_text(f"Background removal failed: {error_message}")

    except Exception as e:
        await update.message.reply_text(f"An error occurred while processing the image: {e}")

    finally:
        # Clean up the downloaded image if needed
        try:
            if os.path.exists(photo_path):
                os.remove(photo_path)
            if os.path.exists(output_file):
                os.remove(output_file)
        except OSError as cleanup_error:
            print(f"Cleanup error: {cleanup_error}")

# Add a handler for this command in your bot's main file:
# application.add_handler(CommandHandler('bgremove', remove_bg))
