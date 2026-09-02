# handlers/new_post.py
import logging
from pyrogram import Client, filters
from database.db import find_owner_by_index_channel
from utils.helpers import notify_and_remove_invalid_channel
import asyncio
from config import Config

logger = logging.getLogger(__name__)

@Client.on_message(filters.channel & (filters.document | filters.video | filters.audio), group=2)
async def new_file_handler(client, message):
    """
    This handler listens for new files, finds the owner, and now directly
    creates an asyncio task to process the file immediately, replacing the old
    queueing system.
    """
    try:
        user_id = await find_owner_by_index_channel(message.chat.id)
        if not user_id: 
            return

        if not await notify_and_remove_invalid_channel(client, user_id, message.chat.id, "Index DB"):
            logger.warning(f"Aborted processing from inaccessible channel {message.chat.id} for user {user_id}")
            return

        media = getattr(message, message.media.value, None)
        if not media or not getattr(media, 'file_name', None):
            return
        
        if not client.owner_db_channel:
            logger.warning("Owner Database Channel not set by admin. Ignoring file.")
            # Optionally, notify the admin that the bot is not fully configured
            try:
                await client.send_message(Config.ADMIN_ID, "⚠️ **Configuration Alert**\n\nA file was received, but I cannot process it because the `OWNER_DB_CHANNEL` is not set in my configuration.")
            except Exception as e:
                logger.error(f"Failed to send configuration alert to admin: {e}")
            return
        
        # --- THE NEW PARADIGM: DIRECT TASK CREATION ---
        # Instead of putting the message in a queue, create a dedicated task
        # for this specific file. This ensures processing is immediate and isolated.
        asyncio.create_task(client.process_new_file(message, user_id))
        
        logger.info(f"Created a direct processing task for file '{media.file_name}' for user {user_id}.")

    except Exception as e:
        logger.exception(f"Error in new_file_handler before task creation: {e}")
