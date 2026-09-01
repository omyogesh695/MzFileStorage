# mzbotz/mz-file-store/handlers/start.py

import logging
import re
import asyncio
import time
import hmac
import hashlib
import random
import string
from pyrogram import Client, filters, enums
from pyrogram.errors import (
    UserNotParticipant,
    MessageNotModified,
    ChatAdminRequired,
    ChannelInvalid,
    PeerIdInvalid,
    ChannelPrivate,
    MessageDeleteForbidden,
    UserIsBlocked
)
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from config import Config
from database.db import (
    add_user,
    get_file_by_unique_id,
    get_user,
    is_user_verified,
    claim_verification_for_file,
    update_user,
    record_daily_view
)
from utils.helpers import get_main_menu
from features.shortener import get_shortlink

logger = logging.getLogger(__name__)


@Client.on_message(filters.private & ~filters.command("start") & (filters.document | filters.video | filters.audio))
async def handle_private_file(client, message):
    if not client.owner_db_channel:
        return await message.reply_text("The bot is not yet configured by the admin. Please try again later.")
    
    if not Config.APP_URL:
        return await message.reply_text("The bot's streaming service is not configured by the admin. Please try again later.")
    
    processing_msg = await message.reply_text("⏳ Processing your file...", reply_to_message_id=message.id)
    try:
        media = getattr(message, message.media.value, None)
        if not media:
            return await processing_msg.edit_text("Could not find media in the message.")

        copied_message = await message.copy(client.owner_db_channel)
        
        from database.db import save_file_data
        await save_file_data(message.from_user.id, message, copied_message, copied_message)

        buttons = [
            [InlineKeyboardButton("📺 Stream / Download", url=f"{Config.APP_URL.rstrip('/')}/watch/{copied_message.id}")]
        ]
        keyboard = InlineKeyboardMarkup(buttons)
        
        file_name = getattr(media, "file_name", "unknown.file")
        
        await client.send_cached_media(
            chat_id=message.chat.id,
            file_id=media.file_id,
            caption=f"`{file_name}`",
            reply_markup=keyboard,
            reply_to_message_id=message.id
        )
        await processing_msg.delete()
    except UserIsBlocked:
        logger.warning(f"Could not send private file to user {message.from_user.id} as they blocked the bot.")
        await processing_msg.delete()
    except Exception as e:
        logger.exception("Error in handle_private_file")
        await processing_msg.edit_text(f"An error occurred: {e}")


async def send_file(client, requester_id, owner_id, file_unique_id):
    try:
        if not Config.APP_URL:
            await client.send_message(
                requester_id,
                "Sorry, the bot's streaming service is not configured by the admin."
            )
            return

        file_data = await get_file_by_unique_id(owner_id, file_unique_id)
        if not file_data:
            await client.send_message(
                requester_id,
                "Sorry, this file is no longer available or the link is invalid."
            )
            return

        owner_settings = await get_user(file_data['owner_id'])
        if not owner_settings:
            await client.send_message(
                requester_id,
                "A configuration error occurred on the bot."
            )
            return

        await record_daily_view(owner_id, requester_id)

        stream_message_id = file_data.get('file_id') or file_data.get('stream_id')

        buttons = [
            [InlineKeyboardButton(
                "📺 Stream / Download",
                url=f"{Config.APP_URL.rstrip('/')}/watch/{stream_message_id}"
            )]
        ]
        keyboard = InlineKeyboardMarkup(buttons)

        # Clean filename
        file_name_raw = file_data.get('file_name', 'N/A')
        file_name_semi_cleaned = re.sub(r'@[a-zA-Z0-9_]+', '', file_name_raw).strip()
        file_name_semi_cleaned = re.sub(r'(www\.|https?://)\S+', '', file_name_semi_cleaned).strip()
        file_name_semi_cleaned = file_name_semi_cleaned.replace('_', ' ')
        file_name_semi_cleaned = re.sub(r'join\s*us', '', file_name_semi_cleaned, flags=re.IGNORECASE)
        
        filename_url = owner_settings.get("filename_url")

        if filename_url:
            filename_part = f"[{file_name_semi_cleaned}]({filename_url})"
        else:
            filename_part = f"`{file_name_semi_cleaned}`"

        caption = (
            f"✅ **Here is your file!**\n\n"
            f"{filename_part}\n\n"
            f"━━━━━━━━━━━━━━\n"
            f"🗑 **File automatically deleted after 10 minutes.**"
        )

        sent_message = await client.copy_message(
            chat_id=requester_id,
            from_chat_id=client.owner_db_channel,
            message_id=file_data['file_id'],
            caption=caption,
            reply_markup=keyboard,
            parse_mode=enums.ParseMode.MARKDOWN
        )

        # Null check for safety against crashes
        if sent_message and hasattr(sent_message, 'id'):
            asyncio.create_task(
                auto_delete_message(client, requester_id, sent_message.id)
            )

    except UserIsBlocked:
        logger.warning(f"Could not send file to user {requester_id} as they blocked the bot.")

    except ValueError as e:
        logger.critical(
            f"FATAL ERROR in send_file: Peer ID '{client.owner_db_channel}' is invalid. Error: {e}"
        )
        try:
            await client.send_message(requester_id, "Sorry, the bot is facing a configuration issue...")
            await client.send_message(
                Config.ADMIN_ID,
                "🚨 **CRITICAL ERROR** 🚨\n\nOWNER_DB_CHANNEL is inaccessible."
            )
        except Exception:
            pass

    except Exception as e:
        logger.exception("Error in send_file function")
        try:
            await client.send_message(
                requester_id,
                "Something went wrong while sending the file."
            )
        except Exception:
            pass


async def auto_delete_message(client, chat_id, message_id):
    await asyncio.sleep(600)  # 10 minutes

    try:
        await client.delete_messages(chat_id, message_id)
    except Exception:
        pass


@Client.on_message(filters.command("start") & filters.private)
async def start_command(client, message):

    if message.from_user.is_bot:
        return

    requester_id = message.from_user.id
    await add_user(requester_id)

    if len(message.command) > 1:
        payload = message.command[1]

        try:
            # ================= VERIFY HANDLER =================
            if payload.startswith("verify_"):
                _, owner_id_str, file_unique_id = payload.split("_", 2)
                owner_id = int(owner_id_str)

                # Mark user verified (24hr expiry handled in DB)
                await claim_verification_for_file(owner_id, file_unique_id, requester_id)

                await message.reply_text(
                    "✅ <b>Verification Successful!</b>\n\n"
                    "⏳ Your access is now valid for <b>24 Hours</b>.\n"
                    "After that, you will need to verify again.\n\n"
                    "Enjoy your file 🎉",
                    parse_mode=enums.ParseMode.HTML
                )

                await send_file(client, requester_id, owner_id, file_unique_id)
                return

            # ================= PUBLIC FILE =================
            if payload.startswith("get_"):
                if not Config.APP_URL:
                    return await message.reply_text("Streaming service not configured.")

                await handle_public_file_request(client, message, requester_id, payload)
                return

            # ================= OWNER LINK =================
            if payload.startswith("ownerget_"):
                if not Config.APP_URL:
                    return await message.reply_text("Streaming service not configured.")

                _, owner_id_str, file_unique_id = payload.split("_", 2)
                owner_id = int(owner_id_str)

                if requester_id == owner_id:
                    await send_file(client, requester_id, owner_id, file_unique_id)
                else:
                    await message.reply_text("This link is only for the file owner.")
                return

        except Exception:
            logger.exception("Deep link error")
            return await message.reply_text("Invalid or expired link.")

    # ================= NORMAL START MESSAGE =================
    text = (
        f"Hello {message.from_user.mention}! 👋\n\n"
        "Welcome to your advanced **File Management Assistant**.\n\n"
        "I can help you store, manage, and share your files effortlessly.\n\n"
        "**Here's what I can do:**\n"
        "🗂️ Save unlimited files\n"
        "📺 Instant streaming links\n"
        "📢 Auto channel posting\n"
        "⚙️ Full customization system\n\n"
        "Click **Let's Go 🚀** to open your settings menu!"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Let's Go 🚀", callback_data=f"go_back_{requester_id}"),
            InlineKeyboardButton("Tutorial 🎬", url=Config.TUTORIAL_URL)
        ],
        [
            InlineKeyboardButton("📢 Update Channel", url="https://t.me/mzbotz"),
            InlineKeyboardButton("👑 Owner", url="https://t.me/aonemarathi")
        ]
    ])

    await message.reply_text(
        text,
        reply_markup=keyboard,
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True
    )


async def handle_public_file_request(client, message, requester_id, payload):
    try:
        _, owner_id_str, file_unique_id = payload.split("_", 2)
        owner_id = int(owner_id_str)
    except (ValueError, IndexError):
        return await message.reply_text("The link is invalid or corrupted.")

    file_data = await get_file_by_unique_id(owner_id, file_unique_id)
    if not file_data:
        return await message.reply_text("File not found or link has expired.")

    owner_settings = await get_user(owner_id)

    # ===============================
    # FSUB CHECK
    # ===============================
    fsub_channel = owner_settings.get('fsub_channel') if owner_settings else None

    if fsub_channel:
        try:
            await client.get_chat_member(chat_id=fsub_channel, user_id="me")
            try:
                await client.get_chat_member(chat_id=fsub_channel, user_id=requester_id)
            except UserNotParticipant:
                try:
                    invite_link = await client.export_chat_invite_link(fsub_channel)
                except Exception:
                    invite_link = None

                buttons = []
                if invite_link:
                    buttons.append([InlineKeyboardButton("📢 Join Channel", url=invite_link)])

                buttons.append([InlineKeyboardButton("🔄 Retry", callback_data=f"retry_{payload}")])

                return await message.reply_text(
                    "You must join the channel to continue.",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )

        except (ChatAdminRequired, ChannelInvalid, PeerIdInvalid, ChannelPrivate, UserNotParticipant) as e:
            logger.error(f"FSub channel error for owner {owner_id} (Channel: {fsub_channel}): {e}")
            try:
                await client.send_message(
                    chat_id=owner_id,
                    text=(
                        "⚠️ **FSub Channel Error**\n\n"
                        f"Your FSub channel (`{fsub_channel}`) is no longer valid.\n\n"
                        "It has been automatically disabled."
                    ),
                    parse_mode=enums.ParseMode.MARKDOWN
                )
                await update_user(owner_id, "fsub_channel", None)
            except Exception:
                pass

    # ===============================
    # VERIFY CHECK (SHORTENER ON / OFF + ANTI-BYPASS)
    # ===============================
    if requester_id == owner_id or requester_id == Config.ADMIN_ID:
        verified = True
    else:
        verified = await is_user_verified(owner_id, requester_id)

    if not verified:
        shortener_enabled = owner_settings.get("shortener_enabled", True) if owner_settings else False
        shortener_api = owner_settings.get("shortener_api") if owner_settings else None
        shortener_url = owner_settings.get("shortener_url") if owner_settings else None

        has_active_shortener = bool(shortener_enabled and shortener_api and shortener_url)
        bot_username = client.me.username if hasattr(client, "me") and client.me else "Mzfilestorage_bot"

        if not has_active_shortener:
            # 🟢 SHORTENER OFF: Direct Telegram Bot Deep Link
            verify_url = f"https://t.me/{bot_username}?start=verify_{owner_id}_{file_unique_id}"
        else:
            # 🔴 SHORTENER ON: Short Random Session ID + HMAC-SHA256 Signature
            short_id = ''.join(random.choices(string.ascii_letters + string.digits, k=7))
            ts = int(time.time())
            secret_key = getattr(Config, "SECRET_KEY", "mz_super_secret_anti_bypass_key_2026")
            
            raw_data = f"{short_id}_{ts}"
            sig = hmac.new(secret_key.encode(), raw_data.encode(), hashlib.sha256).hexdigest()
            
            # Register Session directly in stream_routes memory store
            from server.stream_routes import register_short_session
            register_short_session(short_id, owner_id, file_unique_id, requester_id, ts)

            koyeb_destination = f"{Config.APP_URL.rstrip('/')}/v/{short_id}?sig={sig}___{ts}"
            verify_url = await get_shortlink(koyeb_destination, owner_id)

        tutorial_link = None
        if owner_settings:
            tutorial_link = owner_settings.get("how_to_download_link")

        if not tutorial_link:
            tutorial_link = Config.TUTORIAL_URL

        buttons = [
            [InlineKeyboardButton("🔐 Verify Now", url=verify_url)],
            [InlineKeyboardButton("📖 How To Verify", url=tutorial_link)]
        ]

        return await message.reply_text(
            "🔒 **Access Restricted**\n\n"
            "To unlock this file, you must complete a quick verification.\n\n"
            "👇 Click below to continue:",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=enums.ParseMode.MARKDOWN
        )

    # ===============================
    # VERIFIED → RECORD STATS + SEND FILE
    # ===============================
    await record_daily_view(owner_id, requester_id)
    await send_file(client, requester_id, owner_id, file_unique_id)


@Client.on_callback_query(filters.regex(r"^retry_"))
async def retry_handler(client, query):
    try:
        await query.message.delete()
    except (MessageDeleteForbidden, MessageNotModified):
        await query.answer("Retrying...", show_alert=False)
    except Exception as e:
        logger.warning(f"Could not delete message in retry_handler: {e}")
    
    try:
        await handle_public_file_request(client, query.message, query.from_user.id, query.data.split("_", 1)[1])
    except UserIsBlocked:
        logger.warning(f"User {query.from_user.id} blocked the bot during retry.")
        await query.answer("Could not retry because you have blocked the bot.", show_alert=True)


@Client.on_callback_query(filters.regex(r"go_back_"))
async def go_back_callback(client, query):
    user_id = int(query.data.split("_")[-1])
    if query.from_user.id != user_id:
        return await query.answer("This is not for you!", show_alert=True)
    try:
        menu_text, menu_markup = await get_main_menu(user_id)
        await query.message.edit_text(
            text=menu_text,
            reply_markup=menu_markup,
            parse_mode=enums.ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
    except MessageNotModified:
        await query.answer()
    except Exception as e:
        logger.error(f"Error in go_back_callback: {e}")
        await query.answer("An error occurred while loading the menu.", show_alert=True)
      
