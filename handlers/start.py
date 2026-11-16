# handlers/start.py

import logging
import re
import asyncio
import time
import hmac
import datetime
import hashlib
import random
import string
import base64
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
    claim_step_verification,
    claim_verification_for_file,
    update_user,
    record_daily_view,
    get_user_verify_step,
    set_user_verify_step,
    get_verify_log_channel,
    files
)
from utils.helpers import get_main_menu
from features.shortener import get_shortlink

logger = logging.getLogger(__name__)


def decode_batch_token(encoded_str: str):
    """Base64 encoded batch token se (owner_id, min_id, max_id) nikalta hai."""
    try:
        clean_enc = encoded_str.strip()
        padding = len(clean_enc) % 4
        if padding:
            clean_enc += "=" * (4 - padding)
        decoded_data = base64.urlsafe_b64decode(clean_enc.encode("ascii")).decode("ascii")
        parts = decoded_data.split("_")
        if len(parts) == 4 and parts[0] == "batch":
            return int(parts[1]), int(parts[2]), int(parts[3])
    except Exception:
        pass
    return None, None, None


async def resolve_batch_display_name(owner_id: int, min_id: int) -> str:
    """Batch ki pehli file ka asli naam database se fetch karta hai."""
    try:
        b_file = await files.find_one({
            "owner_id": {"$in": [owner_id, str(owner_id)]},
            "$or": [
                {"file_id": {"$in": [min_id, str(min_id)]}},
                {"stream_id": {"$in": [min_id, str(min_id)]}}
            ]
        })
        if b_file and b_file.get("file_name"):
            raw_fname = b_file.get("file_name")
            raw_fname = re.sub(r'^\s*\[.*?\][\s\._-]*', '', raw_fname)
            raw_fname = re.sub(r'^[._\-\s]+', '', raw_fname).strip()
            return f"{raw_fname} (Batch)"
    except Exception:
        pass
    return "All Quality Batch Pack"


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


async def send_batch_files(client, requester_id, owner_id, min_id, max_id):
    """Batch ke sabhi messages ko sequential copy karke send karta hai"""
    owner_settings = await get_user(owner_id)
    filename_url = owner_settings.get("filename_url") if owner_settings else None

    total_to_send = max_id - min_id + 1
    if total_to_send > 60:
        max_id = min_id + 59

    sent_count = 0
    for msg_id in range(min_id, max_id + 1):
        try:
            file_entry = await files.find_one({
                "owner_id": {"$in": [owner_id, str(owner_id)]},
                "$or": [
                    {"file_id": {"$in": [msg_id, str(msg_id)]}},
                    {"stream_id": {"$in": [msg_id, str(msg_id)]}}
                ]
            })

            stream_url = f"{Config.APP_URL.rstrip('/')}/watch/{msg_id}" if Config.APP_URL else None
            buttons = [[InlineKeyboardButton("📺 Stream / Download", url=stream_url)]] if stream_url else []
            keyboard = InlineKeyboardMarkup(buttons) if buttons else None

            if file_entry and file_entry.get('file_name'):
                file_name_raw = file_entry.get('file_name', 'N/A')
                file_name_semi_cleaned = re.sub(r'@[a-zA-Z0-9_]+', '', file_name_raw).strip()
                file_name_semi_cleaned = re.sub(r'(www\.|https?://)\S+', '', file_name_semi_cleaned).strip()
                file_name_semi_cleaned = file_name_semi_cleaned.replace('_', ' ')
                file_name_semi_cleaned = re.sub(r'join\s*us', '', file_name_semi_cleaned, flags=re.IGNORECASE).strip()

                filename_part = f"[{file_name_semi_cleaned}]({filename_url})" if filename_url else f"`{file_name_semi_cleaned}`"
                caption = (
                    f"✅ **Here is your file!**\n\n"
                    f"{filename_part}\n\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"🗑 **File automatically deleted after 10 minutes.**"
                )
            else:
                caption = (
                    "✅ **Here is your file!**\n\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"🗑 **File automatically deleted after 10 minutes.**"
                )

            sent_msg = await client.copy_message(
                chat_id=requester_id,
                from_chat_id=client.owner_db_channel,
                message_id=msg_id,
                caption=caption,
                reply_markup=keyboard,
                parse_mode=enums.ParseMode.MARKDOWN
            )

            if sent_msg and hasattr(sent_msg, 'id'):
                asyncio.create_task(auto_delete_message(client, requester_id, sent_msg.id))
            
            sent_count += 1
            await asyncio.sleep(0.7)
        except UserIsBlocked:
            break
        except Exception as e:
            logger.debug(f"Skipping msg {msg_id} during batch send: {e}")
            continue

    if sent_count == 0:
        await client.send_message(requester_id, "⚠️ No valid files found in this batch range.")


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
            # ================= VERIFY HANDLER (PER-STEP GAP) =================
            if payload.startswith("verify_"):
                parts = payload.split("_")
                
                if len(parts) >= 4 and parts[1] == "batch":
                    owner_id = int(parts[2])
                    encoded_data = parts[3]
                    file_unique_id = f"batch_{encoded_data}"
                else:
                    _, owner_id_str, file_unique_id = payload.split("_", 2)
                    owner_id = int(owner_id_str)

                owner_settings = await get_user(owner_id)

                total_steps = 1
                if owner_settings:
                    if owner_settings.get("shortener_url_3") and owner_settings.get("shortener_api_3"):
                        total_steps = 3
                    elif owner_settings.get("shortener_url_2") and owner_settings.get("shortener_api_2"):
                        total_steps = 2

                current_step = await get_user_verify_step(owner_id, requester_id)
                vlog_ch = await get_verify_log_channel(owner_id)

                if file_unique_id.startswith("batch_"):
                    enc_part = file_unique_id.split("_", 1)[1]
                    _, b_min_id, _ = decode_batch_token(enc_part)
                    fname = await resolve_batch_display_name(owner_id, b_min_id) if b_min_id else "All Quality Batch Pack"
                else:
                    file_obj = await get_file_by_unique_id(owner_id, file_unique_id)
                    fname = file_obj.get("file_name", "Unknown File") if file_obj else "Unknown"
                
                if owner_settings:
                    gap_val = owner_settings.get(f'verify_gap_{current_step}') or owner_settings.get('verify_gap', 720)
                else:
                    gap_val = 720

                try:
                    gap_mins = int(gap_val)
                except Exception:
                    gap_mins = 720

                if vlog_ch:
                    try:
                        u = message.from_user
                        if u.username:
                            user_str = f"@{u.username} (`{requester_id}`)"
                        else:
                            first_name = u.first_name or "User"
                            user_str = f"[{first_name}](tg://user?id={requester_id}) (`{requester_id}`)"

                        ist_time = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
                        log_msg = (
                            f"⚡️ **Shortener Step {current_step} Passed!**\n\n"
                            f"👤 **User:** {user_str}\n"
                            f"📁 **File:** `{fname}`\n"
                            f"🔢 **Step:** `{current_step}/{total_steps}`\n"
                            f"⏱ **Access Valid:** `{gap_mins} Minutes`\n"
                            f"📅 **Time:** `{ist_time.strftime('%Y-%m-%d %I:%M:%S %p')} IST`"
                        )
                        await client.send_message(chat_id=int(vlog_ch), text=log_msg)
                    except Exception as err:
                        logger.warning(f"Could not send log to channel: {err}")

                await claim_step_verification(owner_id, file_unique_id, requester_id, current_step, total_steps, gap_mins=gap_mins)

                await message.reply_text(
                    f"✅ <b>Verification Successful!</b>\n\n"
                    f"⏳ Your access is now unlocked for <b>{gap_mins} Minutes</b>.\n"
                    "Enjoy your files 🎉",
                    parse_mode=enums.ParseMode.HTML
                )

                if file_unique_id.startswith("batch_"):
                    enc_part = file_unique_id.split("_", 1)[1]
                    await handle_batch_request(client, message, requester_id, enc_part)
                else:
                    await send_file(client, requester_id, owner_id, file_unique_id)
                return

            # ================= PUBLIC FILE =================
            if payload.startswith("get_"):
                if not Config.APP_URL:
                    return await message.reply_text("Streaming service not configured.")

                await handle_public_file_request(client, message, requester_id, payload)
                return

            # ================= ⚡ BATCH / ALL QUALITY LINK =================
            if payload.startswith("b_"):
                if not Config.APP_URL:
                    return await message.reply_text("Streaming service not configured.")

                encoded_str = payload[2:]
                await handle_batch_request(client, message, requester_id, encoded_str)
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

    # FSUB CHECK
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
                await update_user(owner_id, "f
