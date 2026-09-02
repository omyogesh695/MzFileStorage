# util/logger.py

import time
import logging
from config import Config
from database.db import get_user_log_channel

logger = logging.getLogger(__name__)

async def send_verification_log(bot, requester_id: int, owner_id: int, file_unique_id: str, spent: int, elapsed: int):
    """
    User verification success hone par alert bhejta hai:
    1. Owner ke Personal Log Channel par.
    2. Bot Owner ke Master Log Channel (Config.LOG_CHANNEL) par.
    """
    try:
        user_info = await bot.get_users(requester_id)
        user_name = user_info.first_name if user_info else "User"
        mention = f"[{user_name}](tg://user?id={requester_id})"
        username_str = f"@{user_info.username}" if user_info and user_info.username else "No Username"
    except Exception:
        mention = f"User (`{requester_id}`)"
        username_str = "Unknown"

    log_text = (
        "🔐 **#VERIFICATION_SUCCESSFUL**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Requester:** {mention}\n"
        f"🆔 **User ID:** `{requester_id}`\n"
        f"🌐 **Username:** {username_str}\n"
        f"⏱️ **Time Spent:** `{spent}s` (Elapsed: `{elapsed}s`)\n"
        f"📁 **File Unique ID:** `{file_unique_id}`\n"
        f"👑 **File Owner ID:** `{owner_id}`\n"
        f"📅 **Timestamp:** `{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    # 1. File Owner ke Personal Log Channel par send karein
    try:
        owner_log_channel = await get_user_log_channel(owner_id)
        if owner_log_channel:
            await bot.send_message(
                chat_id=owner_log_channel,
                text=log_text,
                disable_web_page_preview=True
            )
    except Exception as e:
        logger.error(f"Failed to send log to personal log channel ({owner_id}): {e}")

    # 2. Master Admin Log Channel par send karein (Config.LOG_CHANNEL)
    try:
        master_log = getattr(Config, "LOG_CHANNEL", None)
        # Agar owner_log_channel aur master_log alag hain tabhi dubara bhejega
        if master_log and master_log != owner_log_channel:
            await bot.send_message(
                chat_id=master_log,
                text=log_text,
                disable_web_page_preview=True
            )
    except Exception as e:
        logger.error(f"Failed to send verification log to master channel: {e}")


async def send_client_config_log(bot, user, chat_info):
    """
    Master Admin Log Channel Alert:
    Jab koi client / user apna storage channel ya log channel configure kare.
    """
    master_log = getattr(Config, "LOG_CHANNEL", None)
    if not master_log:
        return

    try:
        mention = f"[{user.first_name}](tg://user?id={user.id})"
        username_str = f"@{user.username}" if user.username else "No Username"
        channel_link = f"@{chat_info.username}" if chat_info.username else "Private Channel"
        members_count = getattr(chat_info, "members_count", "N/A")

        text = (
            "⚙️ **#BOT_CLIENT_CONFIGURED**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "👤 **Client Details:**\n"
            f" ▸ **Name:** {mention}\n"
            f" ▸ **User ID:** `{user.id}`\n"
            f" ▸ **Username:** {username_str}\n\n"
            "📢 **Connected Channel Details:**\n"
            f" ▸ **Title:** `{chat_info.title}`\n"
            f" ▸ **Channel ID:** `{chat_info.id}`\n"
            f" ▸ **Link:** {channel_link}\n"
            f" ▸ **Total Members:** `{members_count}`\n\n"
            f"📅 **Configured At:** `{time.strftime('%Y-%m-%d %H:%M:%S')} IST`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        await bot.send_message(
            chat_id=master_log,
            text=text,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Failed to send client config log: {e}")


async def send_new_user_log(bot, user):
    """
    Jab koi naya user pehli baar bot ko `/start` kare.
    """
    master_log = getattr(Config, "LOG_CHANNEL", None)
    if not master_log:
        return

    try:
        mention = f"[{user.first_name}](tg://user?id={user.id})"
        username_str = f"@{user.username}" if user.username else "No Username"

        text = (
            "🆕 **#NEW_USER_STARTED**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Name:** {mention}\n"
            f"🆔 **User ID:** `{user.id}`\n"
            f"🌐 **Username:** {username_str}\n"
            f"📅 **Time:** `{time.strftime('%Y-%m-%d %H:%M:%S')} IST`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        await bot.send_message(
            chat_id=master_log,
            text=text,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Failed to send new user log: {e}")
      
