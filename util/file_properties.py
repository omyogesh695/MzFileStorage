# util/file_properties.py

import logging
from pyrogram import Client
from typing import Any
from pyrogram.types import Message
from pyrogram.file_id import FileId
from config import Config

logger = logging.getLogger(__name__)

class FileIdError(Exception):
    pass

def get_media_from_message(message: "Message") -> Any:
    media_types = (
        "audio", "document", "photo", "sticker", "animation", 
        "video", "voice", "video_note",
    )
    for attr in media_types:
        media = getattr(message, attr, None)
        if media:
            return media
    return None

async def get_message_with_properties(client: Client, message_id: int) -> Message:
    """
    Fetches the message directly from OWNER_DB_CHANNEL to ensure accurate streaming.
    """
    channel_id = getattr(client, "owner_db_channel", None) or Config.OWNER_DB_CHANNEL
    if not channel_id:
        raise ValueError("OWNER_DB_CHANNEL is not configured.")

    try:
        message = await client.get_messages(chat_id=channel_id, message_ids=message_id)
    except Exception as e:
        logger.error(f"Error fetching message {message_id} from {channel_id}: {e}")
        raise FileIdError(f"Could not fetch message {message_id} from storage channel.")

    if not message or not message.media:
        raise FileIdError(f"Message {message_id} not found or contains no media in channel {channel_id}.")
        
    return message

