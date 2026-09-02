# handlers/settings.py 

import asyncio
import base64
import logging
import aiohttp
import re
import time
from pyrogram import Client, filters, enums
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
# --- LEGENDARY MODIFICATION: Import specific error for precise handling ---
from pyrogram.errors import MessageNotModified, UserNotParticipant, ChannelPrivate, ButtonDataInvalid, ChatAdminRequired, QueryIdInvalid
from pyromod.exceptions import ListenerTimeout
from database.db import (
    get_user, update_user, add_to_list, remove_from_list,
    get_user_file_count, add_footer_button, remove_footer_button, remove_all_footer_buttons,
    get_all_user_files, get_paginated_files, search_user_files,
    add_user, set_post_channel, set_index_db_channel, get_index_db_channel,
    get_posts_for_backup, delete_posts_from_channel, add_backup_channel,
    get_backup_channels, remove_backup_channel, get_post_channels, 
    set_user_log_channel, remove_user_log_channel,
)
from util.logger import send_client_config_log
from utils.helpers import go_back_button, get_main_menu, create_post, clean_and_parse_filename, calculate_title_similarity, notify_and_remove_invalid_channel, format_bytes, PHOTO_CAPTION_LIMIT, TEXT_MESSAGE_LIMIT
from features.shortener import validate_shortener, get_shortlink
from features.poster import get_poster
from config import Config
from collections import defaultdict
from thefuzz import fuzz

logger = logging.getLogger(__name__)
ACTIVE_BACKUP_TASKS = {} # Changed to a dict to store cancel events


async def safe_edit_message(source, *args, **kwargs):
    try:
        if isinstance(source, CallbackQuery):
            message_to_edit = source.message
        elif isinstance(source, Message):
            message_to_edit = source
        else:
            logger.error(f"safe_edit_message called with invalid type: {type(source)}")
            return
        if 'parse_mode' not in kwargs:
            kwargs['parse_mode'] = ParseMode.MARKDOWN
        await message_to_edit.edit_text(*args, **kwargs)
    except MessageNotModified:
        try:
            if isinstance(source, CallbackQuery):
                await source.answer()
        except (QueryIdInvalid, Exception): # Catch QueryIdInvalid here as well
            pass
    except ButtonDataInvalid:
        logger.exception("ButtonDataInvalid error while editing message")
        try:
            if isinstance(source, CallbackQuery):
                user_id = source.from_user.id
                await remove_all_footer_buttons(user_id)
                await source.answer(
                    "Your footer buttons were invalid and have been reset. Please add them again.",
                    show_alert=True
                )
                menu_text, menu_markup = await get_main_menu(user_id)
                await source.message.edit_text(text=menu_text, reply_markup=menu_markup)
                return
        except Exception as e:
            logger.error(f"Error during ButtonDataInvalid handling: {e}")
    except Exception as e:
        logger.exception("Error while editing message")
        try:
            if isinstance(source, CallbackQuery):
                await source.answer("An error occurred. Please try again.", show_alert=True)
        except (QueryIdInvalid, Exception):
            pass
            
# --- NEW: Daily Stats Menu Handlers ---
async def get_daily_stats_menu_parts(user_id):
    user = await get_user(user_id)
    if not user: await add_user(user_id); user = await get_user(user_id)
    
    is_enabled = user.get('daily_notify_enabled', False)
    status_text = 'ON 🟢' if is_enabled else 'OFF 🔴'
    
    text = (
        "**📊 Daily Stats Dashboard**\n\n"
        "Enable this feature to receive a daily report of your file clicks right here at 11:59 PM.\n\n"
        f"**Current Status:** `{status_text}`"
    )
    
    buttons = [
        [InlineKeyboardButton(f"Turn Notifications {'OFF' if is_enabled else 'ON'}", callback_data="toggle_daily_notify")],
        [go_back_button(user_id).inline_keyboard[0][0]]
    ]
    return text, InlineKeyboardMarkup(buttons)

@Client.on_callback_query(filters.regex("^daily_stats_menu$"))
async def daily_stats_menu_handler(client, query):
    user_id = query.from_user.id
    text, markup = await get_daily_stats_menu_parts(user_id)
    await safe_edit_message(query, text=text, reply_markup=markup)

@Client.on_callback_query(filters.regex("^toggle_daily_notify$"))
async def toggle_daily_notify_handler(client, query):
    user_id = query.from_user.id
    user = await get_user(user_id)
    if not user: await add_user(user_id); user = await get_user(user_id)

    new_status = not user.get('daily_notify_enabled', False)
    await update_user(user_id, 'daily_notify_enabled', new_status)
    await query.answer(f"Daily Notifications are now {'ON' if new_status else 'OFF'}", show_alert=True)
    text, markup = await get_daily_stats_menu_parts(user_id)
    await safe_edit_message(query, text=text, reply_markup=markup)

# --- END: Daily Stats Handlers ---


async def get_shortener_menu_parts(user_id):
    user = await get_user(user_id)
    if not user: await add_user(user_id); user = await get_user(user_id)
    
    is_enabled = user.get('shortener_enabled', True)
    shortener_url = user.get('shortener_url')
    shortener_api = user.get('shortener_api')
    
    text = "**🔗 Shortener Settings**\n\nAll links are shortened by default using your saved API and Domain."
    if shortener_url and shortener_api:
        text += f"\n**Domain:** `{shortener_url}`"
        text += f"\n**API Key:** `{shortener_api}`"
    else:
        text += "\n\n`No shortener domain or API is set.`\n\nShortener is currently disabled."
        is_enabled = False
        
    status_text = 'ON 🟢' if is_enabled else 'OFF 🔴'
    text += f"\n\n**Status:** {status_text}"
    
    buttons = [
        [InlineKeyboardButton(f"Turn Shortener {'OFF' if is_enabled else 'ON'}", callback_data="toggle_shortener")]
    ]
    
    buttons.append([InlineKeyboardButton("✏️ Set/Edit API & Domain", callback_data="set_shortener")])
    
    if shortener_url or shortener_api:
        buttons.append([InlineKeyboardButton("🗑️ Reset API & Domain", callback_data="reset_shortener")])
        
    buttons.append([go_back_button(user_id).inline_keyboard[0][0]])
    return text, InlineKeyboardMarkup(buttons)


@Client.on_callback_query(filters.regex("^reset_shortener$"))
async def reset_shortener_handler(client, query):
    user_id = query.from_user.id
    await update_user(user_id, "shortener_url", None)
    await update_user(user_id, "shortener_api", None)
    await query.answer("✅ Shortener settings have been reset.", show_alert=True)
    text, markup = await get_shortener_menu_parts(user_id)
    await safe_edit_message(query, text=text, reply_markup=markup)

async def get_poster_menu_parts(user_id):
    user = await get_user(user_id)
    if not user: await add_user(user_id); user = await get_user(user_id)
    
    is_enabled = user.get('show_poster', True)
    text = f"**🖼️ Poster Settings**\n\nIMDb Poster is currently **{'ON' if is_enabled else 'OFF'}**."
    return text, InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Turn Poster {'OFF 🔴' if is_enabled else 'ON 🟢'}", callback_data="toggle_poster")],
        [go_back_button(user_id).inline_keyboard[0][0]]
    ])

async def get_fsub_menu_parts(client, user_id):
    user = await get_user(user_id)
    if not user: await add_user(user_id); user = await get_user(user_id)
    
    fsub_ch = user.get('fsub_channel')
    text = "**📢 FSub Settings**\n\n"
    if fsub_ch:
        is_valid = await notify_and_remove_invalid_channel(client, user_id, fsub_ch, "FSub")
        if is_valid:
            try:
                chat = await client.get_chat(fsub_ch)
                text += f"Current FSub Channel: **{chat.title}** (`{fsub_ch}`)"
            except:
                text += f"Current FSub Channel ID: `{fsub_ch}`"
    else:
        text += "No FSub channel is set."
    buttons = [
        [InlineKeyboardButton("✏️ Set/Change FSub", callback_data="set_fsub")],
    ]
    if fsub_ch:
        buttons.append([InlineKeyboardButton("🗑️ Remove FSub", callback_data="remove_fsub")])
    buttons.append([go_back_button(user_id).inline_keyboard[0][0]])
    return text, InlineKeyboardMarkup(buttons)


@Client.on_callback_query(filters.regex("^how_to_download_menu$"))
async def how_to_download_menu_handler(client, query):
    user_id = query.from_user.id
    user = await get_user(user_id)
    if not user: await add_user(user_id); user = await get_user(user_id)

    download_link = user.get("how_to_download_link")

    text = "**❓ How to Download Link Settings**\n\n"
    if download_link:
        text += f"Your current 'How to Download' tutorial link is:\n`{download_link}`"
    else:
        text += "You have not set a 'How to Download' link yet."

    buttons = [
        [InlineKeyboardButton("✏️ Set/Change Link", callback_data="set_download")],
        [go_back_button(user_id).inline_keyboard[0][0]]
    ]
    await safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(buttons), disable_web_page_preview=True)


# --- Main Callback Handlers ---

@Client.on_callback_query(filters.regex("^manage_channels_menu$"))
async def manage_channels_submenu_handler(client, query):
    text = "🗂️ **Manage Channels**\n\nSelect which type of channel you want to manage."
    buttons = [
        [InlineKeyboardButton("➕ Manage Auto Post Channels", callback_data="manage_post_ch")],
        [InlineKeyboardButton("🗃️ Manage Database Channel", callback_data="manage_db_ch")],
        [go_back_button(query.from_user.id).inline_keyboard[0][0]]
    ]
    markup = InlineKeyboardMarkup(buttons)
    await safe_edit_message(query, text=text, reply_markup=markup)

@Client.on_callback_query(filters.regex("^filename_link_menu$"))
async def filename_link_menu_handler(client, query):
    user = await get_user(query.from_user.id)
    if not user: await add_user(query.from_user.id); user = await get_user(query.from_user.id)
    
    filename_url = user.get("filename_url")
    
    text = "**✍️ Filename Link Settings**\n\nThis URL will be used as a hyperlink for the filename when a user receives a file."
    if filename_url:
        text += f"\n\n**Current Link:**\n`{filename_url}`"
    else:
        text += "\n\n`You have not set a filename link yet.`"
    
    buttons = [
        [InlineKeyboardButton("✏️ Set/Change Link", callback_data="set_filename_link")],
        [go_back_button(query.from_user.id).inline_keyboard[0][0]]
    ]
    await safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(buttons), disable_web_page_preview=True)


@Client.on_callback_query(filters.regex(r"^(shortener|poster|fsub)_menu$"))
async def settings_submenu_handler(client, query):
    user_id = query.from_user.id
    menu_type = query.data.split("_")[0]
    if menu_type == "shortener": text, markup = await get_shortener_menu_parts(user_id)
    elif menu_type == "poster": text, markup = await get_poster_menu_parts(user_id)
    elif menu_type == "fsub": text, markup = await get_fsub_menu_parts(client, user_id)
    else: return
    await safe_edit_message(query, text=text, reply_markup=markup)

@Client.on_callback_query(filters.regex(r"toggle_shortener$"))
async def toggle_shortener_handler(client, query):
    user_id = query.from_user.id
    user = await get_user(user_id)
    if not user: await add_user(user_id); user = await get_user(user_id)
    
    if not user.get('shortener_url') or not user.get('shortener_api'):
        await query.answer("You must set an API and Domain before enabling the shortener.", show_alert=True)
        return

    new_status = not user.get('shortener_enabled', True)
    await update_user(user_id, 'shortener_enabled', new_status)
    await query.answer(f"Shortener is now {'ON' if new_status else 'OFF'}", show_alert=True)
    text, markup = await get_shortener_menu_parts(user_id)
    await safe_edit_message(query, text=text, reply_markup=markup)

@Client.on_callback_query(filters.regex(r"toggle_poster$"))
async def toggle_poster_handler(client, query):
    user_id = query.from_user.id
    user = await get_user(user_id)
    if not user: await add_user(user_id); user = await get_user(user_id)
    
    new_status = not user.get('show_poster', True)
    await update_user(user_id, 'show_poster', new_status)
    await query.answer(f"Poster is now {'ON' if new_status else 'OFF'}", show_alert=True)
    text, markup = await get_poster_menu_parts(user_id)
    await safe_edit_message(query, text=text, reply_markup=markup)

# --- LEGENDARY MODIFICATION: Corrected link generation in My Files ---
@Client.on_callback_query(filters.regex(r"my_files_(\d+)"))
async def my_files_handler(client, query):
    try:
        user_id = query.from_user.id
        page = int(query.data.split("_")[-1])
        total_files = await get_user_file_count(user_id)
        files_per_page = 5
        text = f"**📂 Your Saved Files ({total_files} Total)**\n\nThis is your owner dashboard. These are direct, unshortened links to your files for your personal use.\n\n"
        
        if total_files == 0:
            text += "You have not saved any files yet."
        else:
            files_on_page = await get_paginated_files(user_id, page, files_per_page)
            if not files_on_page: 
                text += "No more files found on this page."
            else:
                bot_username = (await client.get_me()).username
                for file in files_on_page:
                    # This now generates the correct user-facing deep link
                    link = f"https://t.me/{bot_username}?start=get_{user_id}_{file['file_unique_id']}"
                    text += f"**File:** `{file['file_name']}`\n**Link:** [Click Here to Get File]({link})\n\n"
        
        buttons, nav_row = [], []
        if page > 1: nav_row.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"my_files_{page-1}"))
        if total_files > page * files_per_page: nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"my_files_{page+1}"))
        if nav_row: buttons.append(nav_row)
        buttons.append([InlineKeyboardButton("🔍 Search My Files", callback_data="search_my_files")])
        buttons.append([InlineKeyboardButton("« Go Back", callback_data=f"go_back_{user_id}")])
        await safe_edit_message(query, text=text, reply_markup=InlineKeyboardMarkup(buttons), disable_web_page_preview=True)
    except Exception:
        logger.exception("Error in my_files_handler"); await query.answer("Something went wrong.", show_alert=True)

async def _format_and_send_search_results(client, source, user_id, search_query, page):
    files_per_page = 5
    files_list, total_files = await search_user_files(user_id, search_query, page, files_per_page)
    text = f"**🔎 Search Results for `{search_query}` ({total_files} Found)**\n\n"
    if not files_list: 
        text += "No files found for your query."
    else:
        bot_username = (await client.get_me()).username
        for file in files_list:
            link = f"https://t.me/{bot_username}?start=get_{user_id}_{file['file_unique_id']}"
            text += f"**File:** `{file['file_name']}`\n**Link:** [Click Here to Get File]({link})\n\n"
            
    buttons, nav_row = [], []
    if page > 1: nav_row.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"search_results_{page-1}"))
    if total_files > page * files_per_page: nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"search_results_{page+1}"))
    
    if nav_row: buttons.append(nav_row)
    buttons.append([InlineKeyboardButton("📚 Back to Full List", callback_data="my_files_1")])
    buttons.append([InlineKeyboardButton("« Go Back to Settings", callback_data=f"go_back_{user_id}")])
    await safe_edit_message(source, text=text, reply_markup=InlineKeyboardMarkup(buttons), disable_web_page_preview=True)

@Client.on_callback_query(filters.regex("search_my_files"))
async def search_my_files_prompt(client, query):
    user_id = query.from_user.id
    try:
        prompt = await query.message.edit_text("**🔍 Search Your Files**\n\nPlease send the name of the file you want to find.", reply_markup=go_back_button(user_id))
        response = await client.listen(chat_id=user_id, timeout=300, filters=filters.text)
        
        if not hasattr(client, 'search_cache'):
            client.search_cache = {}
        client.search_cache[user_id] = response.text
        
        await response.delete()
        await _format_and_send_search_results(client, query, user_id, response.text, 1)
    except ListenerTimeout: # --- LEGENDARY FIX: Handle Listener Timeout ---
        await safe_edit_message(query, text="❗️ **Timeout:** Search cancelled.", reply_markup=go_back_button(user_id))
    except Exception as e:
        logger.exception("Error in search_my_files_prompt"); await safe_edit_message(query, text=f"An error occurred: {e}", reply_markup=go_back_button(user_id))

@Client.on_callback_query(filters.regex(r"search_results_(\d+)"))
async def search_results_paginator(client, query):
    try:
        page = int(query.matches[0].group(1))
        user_id = query.from_user.id
        
        if not hasattr(client, 'search_cache') or user_id not in client.search_cache:
            return await query.answer("Your search session has expired. Please start a new search.", show_alert=True)
        search_query = client.search_cache[user_id]
        
        await _format_and_send_search_results(client, query, user_id, search_query, page)
    except Exception:
        logger.exception("Error during search pagination"); await safe_edit_message(query, text="An error occurred during pagination.")

# --- LEGENDARY BACKUP LOGIC (REFACTORED) ---

async def create_backup_post(client, user_id, file_batch, imdb_cache):
    user = await get_user(user_id)
    if not user: return []

    media_info_list = []
    parse_tasks = [clean_and_parse_filename(file_doc['file_name'], imdb_cache) for file_doc in file_batch]
    parsed_results = await asyncio.gather(*parse_tasks)

    for i, info in enumerate(parsed_results):
        if info:
            file_doc = file_batch[i]
            info['file_size'] = file_doc['file_size']
            info['file_unique_id'] = file_doc['file_unique_id']
            media_info_list.append(info)

    if not media_info_list: return []

    first_info = media_info_list[0]
    primary_display_title = first_info['display_title']
    
    poster_search_query = first_info['batch_title'].replace(first_info.get('season_info', ''), '').strip()
    post_poster = await get_poster(poster_search_query, first_info['year']) if user.get('show_poster', True) else None
    
    footer_buttons = user.get('footer_buttons', [])
    footer_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(btn['name'], url=btn['url'])] for btn in footer_buttons]) if footer_buttons else None
    
    CAPTION_LIMIT = PHOTO_CAPTION_LIMIT if post_poster else TEXT_MESSAGE_LIMIT
    
    all_link_entries = []
    for info in media_info_list:
        display_tags_parts = []
        if info.get('episode_info'):
            numbers = re.findall(r'\d+', info['episode_info'])
            ep_text = f"EP {numbers[0]}" if len(numbers) == 1 else f"EP {numbers[0]}-{numbers[1]}" if len(numbers) >= 2 else ""
            if ep_text: display_tags_parts.append(ep_text)
        
        languages = info.get('languages', [])
        if languages: display_tags_parts.append(" + ".join(languages))
        if info.get('quality_tags'): display_tags_parts.append(info['quality_tags'])
        
        display_tags = " | ".join(filter(None, display_tags_parts))
        
        deep_link = f"https://t.me/{client.me.username}?start=get_{user_id}_{info['file_unique_id']}"
        shortened_link = await get_shortlink(deep_link, user_id)
        
        file_size_str = format_bytes(info['file_size'])
        all_link_entries.append(f"├─📁 {display_tags or 'File'}\n│  ╰─➤ [Click Here]({shortened_link}) ({file_size_str})")

    final_posts, current_links_part = [], []
    base_caption_header = f"╭─🎬 **{primary_display_title}** ─╮"
    clean_header_text = f"🎬 {primary_display_title}"
    header_content_length = len(clean_header_text)
    footer_middle_length = int(header_content_length * 0.9)
    footer_middle = '─' * footer_middle_length
    footer_line = f"╰{footer_middle}╯"
    base_caption = f"{base_caption_header}\n│"
    current_length = len(base_caption) + len(footer_line)

    for entry in all_link_entries:
        if current_length + len(entry) + 2 > CAPTION_LIMIT and current_links_part:
            final_caption = f"{base_caption}\n\n" + "\n\n".join(current_links_part) + f"\n\n{footer_line}"
            final_posts.append((post_poster if not final_posts else None, final_caption, footer_keyboard))
            
            current_links_part = [entry]
            current_length = len(base_caption) + len(footer_line) + len(entry) + 2
        else:
            current_links_part.append(entry)
            current_length += len(entry) + 2
            
    if current_links_part:
        final_caption = f"{base_caption}\n\n" + "\n\n".join(current_links_part) + f"\n\n{footer_line}"
        final_posts.append((post_poster if not final_posts else None, final_caption, footer_keyboard))
        
    if len(final_posts) > 1:
        for i, (poster, cap, foot) in enumerate(final_posts):
            new_header = f"╭─🎬 **{primary_display_title} (Part {i+1}/{len(final_posts)})** ─╮"
            new_cap = cap.replace(base_caption_header, new_header)
            final_posts[i] = (poster, new_cap, foot)
            
    return final_posts

@Client.on_callback_query(filters.regex("^backup_links$"))
async def backup_links_handler(client, query):
    user_id = query.from_user.id
    total_files = await get_user_file_count(user_id)
    backup_channels = await get_backup_channels(user_id)
    
    text = f"**🔄 Full Account Backup**\n\nThis will back up all your **{total_files}** saved files into organized posts in your destination channel(s).\n\n"
    buttons = []

    if backup_channels:
        text += "**Destination Channels:**\n"
        for i, ch_id in enumerate(backup_channels):
            try:
                chat = await client.get_chat(ch_id)
                text += f"`{i+1}. {chat.title}`\n"
            except Exception:
                text += f"`{i+1}. Inaccessible Channel (ID: {ch_id})`\n"
        buttons.append([InlineKeyboardButton("🚀 Start Backup Process", callback_data="confirm_backup")])
    else:
        text += "**Destination Channel:** `Not Set`"

    add_button_text = "➕ Add More Channels" if backup_channels else "➕ Add Backup Channel"
    if len(backup_channels) < 5:
        buttons.append([InlineKeyboardButton(add_button_text, callback_data="add_backup_ch")])
    
    if backup_channels:
        buttons.append([InlineKeyboardButton("🗑️ Manage Backup Channels", callback_data="manage_backup_ch")])
    
    # --- LEGENDARY MODIFICATION: Renamed "Settings" to "Backup Settings" ---
    buttons.append([InlineKeyboardButton("⚙️ Backup Settings", callback_data=f"go_back_{user_id}")])
    buttons.append([go_back_button(user_id).inline_keyboard[0][0]])
    
    await safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(buttons))


@Client.on_callback_query(filters.regex("^manage_backup_ch$"))
async def manage_backup_channels_handler(client, query):
    user_id = query.from_user.id
    backup_channels = await get_backup_channels(user_id)
    
    text = "**🗑️ Manage Backup Channels**\n\nClick on a channel to remove it."
    buttons = []
    if backup_channels:
        for ch_id in backup_channels:
            try:
                chat = await client.get_chat(ch_id)
                buttons.append([InlineKeyboardButton(f"❌ {chat.title}", callback_data=f"rm_backup_{ch_id}")])
            except Exception:
                buttons.append([InlineKeyboardButton(f"❌ Unknown Channel (ID: {ch_id})", callback_data=f"rm_backup_{ch_id}")])
    
    buttons.append([InlineKeyboardButton("« Back to Backup Menu", callback_data="backup_links")])
    await safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex(r"^rm_backup_-?\d+$"))
async def remove_backup_channel_handler(client, query):
    user_id = query.from_user.id
    ch_id = int(query.data.split("_")[-1])
    await remove_backup_channel(user_id, ch_id)
    await query.answer("✅ Backup channel removed.", show_alert=True)
    await backup_links_handler(client, query)


# --- LEGENDARY MODIFICATION: Fix for QueryIdInvalid Error ---
@Client.on_callback_query(filters.regex("^add_backup_ch$"))
async def add_backup_channel_prompt(client, query):
    # Answer the query immediately to prevent it from expiring.
    await query.answer()
    
    # Run the rest of the logic in a separate task.
    asyncio.create_task(add_backup_channel_logic(client, query))

async def add_backup_channel_logic(client, query):
    user_id = query.from_user.id
    
    backup_channels = await get_backup_channels(user_id)
    if len(backup_channels) >= 5:
        await client.send_message(user_id, "You have already added the maximum of 5 backup channels.")
        return

    prompt_msg = None
    try:
        prompt_msg = await query.message.edit_text(
            "**➕ Add Backup Channel**\n\n"
            "Forward a message from your target backup channel.\n\n"
            "__I must be an admin with permission to post messages there.__",
            reply_markup=go_back_button(user_id)
        )
        response = await client.listen(chat_id=user_id, filters=filters.forwarded, timeout=300)

        if response and response.forward_from_chat:
            channel_id = response.forward_from_chat.id
            
            try:
                member = await client.get_chat_member(channel_id, "me")
                if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                    raise ChatAdminRequired
            except (ChatAdminRequired, ChannelPrivate):
                 await response.reply_text("❌ **Error!**\nFirst, make me admin there before forwarding the message. Please make me an admin and try again.", reply_markup=go_back_button(user_id))
                 return
            except Exception as e:
                await response.reply_text(f"❌ **Error!**\nCould not verify admin status. Error: `{e}`", reply_markup=go_back_button(user_id))
                return

            await add_backup_channel(user_id, channel_id)
            await response.reply_text(f"✅ **Success!** Channel `{response.forward_from_chat.title}` has been added to your backup destinations.", reply_markup=go_back_button(user_id))
            await asyncio.sleep(2)
            await backup_links_handler(client, query) 
        else:
            await safe_edit_message(prompt_msg, "Invalid forward. Backup cancelled.", reply_markup=go_back_button(user_id))

    except ListenerTimeout: # --- LEGENDARY FIX: Handle Listener Timeout ---
        if prompt_msg: await safe_edit_message(prompt_msg, text="❗️ **Timeout:** Cancelled.", reply_markup=go_back_button(user_id))
    finally:
        if 'response' in locals() and response:
            try: await response.delete()
            except: pass


@Client.on_callback_query(filters.regex("^confirm_backup$"))
async def confirm_backup_handler(client, query):
    user_id = query.from_user.id
    if user_id in ACTIVE_BACKUP_TASKS:
        return await query.answer("A backup process is already running for you. Please wait or cancel it.", show_alert=True)
    
    total_files = await get_user_file_count(user_id)
    if total_files == 0:
        return await query.answer("You have no files to back up.", show_alert=True)
    
    text = (f"**🚀 Ready to Start Backup?**\n\n"
            f"I will process all **{total_files}** of your files. This involves analyzing filenames, finding posters, and creating optimized posts.\n\n"
            "The bot will then send these posts to your configured backup channel(s). This will happen in the background.\n\n"
            "You can cancel at any time from the status message.")
            
    buttons = [
        [InlineKeyboardButton("✅ Yes, Proceed", callback_data="start_backup_now")],
        [InlineKeyboardButton("❌ No, Cancel", callback_data="backup_links")]
    ]
    await safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(buttons))


@Client.on_callback_query(filters.regex("^start_backup_now$"))
async def start_backup_now_handler(client, query):
     user_id = query.from_user.id
     destination_channels = await get_backup_channels(user_id) 
     if not destination_channels:
         return await query.answer("Backup destination not set. Please set it first.", show_alert=True)
     
     asyncio.create_task(start_backup_process(client, query, user_id, destination_channels)) 
     await query.answer("Backup process has been started in the background!", show_alert=False)


# --- LEGENDARY MODIFICATION: Complete overhaul for real-time percentage dashboard ---
async def start_backup_process(client, source_query, user_id, destination_channels):
    if user_id in ACTIVE_BACKUP_TASKS: return

    status_msg = source_query.message
    cancel_event = asyncio.Event()
    ACTIVE_BACKUP_TASKS[user_id] = cancel_event
    imdb_cache = {}
    
    def format_time(seconds):
        if seconds < 60: return f"{seconds:.0f}s"
        mins, secs = divmod(seconds, 60)
        return f"{int(mins)}m {int(secs)}s"

    try:
        total_files = await get_user_file_count(user_id)
        if total_files == 0:
            await safe_edit_message(status_msg, "You have no files to back up.", reply_markup=go_back_button(user_id))
            return
            
        cancel_button = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel Backup", callback_data=f"cancel_backup_{user_id}")]])
        last_update_time = 0

        # --- PHASE 1: ANALYSIS ---
        await status_msg.edit_text(
            f"**Phase 1/3: Analyzing Files...**\n\n"
            f"Initializing for `{total_files}` files.\n\n"
            "This is an automated process. Feel free to leave this screen; the backup will continue.",
            reply_markup=cancel_button
        )
        
        file_cursor = await get_all_user_files(user_id)
        logical_batches = defaultdict(list)
        processed_count = 0
        
        async for file_doc in file_cursor:
            if cancel_event.is_set(): raise asyncio.CancelledError("Backup cancelled by user.")
            
            try:
                parsed_info = await clean_and_parse_filename(file_doc['file_name'], imdb_cache)
                batch_title = (parsed_info.get("batch_title") if parsed_info else "Uncategorized") or "Uncategorized"
                SIMILARITY_THRESHOLD = 85
                best_match_key = max(logical_batches.keys(), key=lambda k: fuzz.token_set_ratio(batch_title, k), default=None)
                if best_match_key and fuzz.token_set_ratio(batch_title, best_match_key) > SIMILARITY_THRESHOLD:
                    logical_batches[best_match_key].append(file_doc)
                else:
                    logical_batches[batch_title].append(file_doc)
            except Exception as e:
                logger.error(f"Skipping file in backup due to parsing error: {file_doc.get('file_name')}, Error: {e}")
            
            processed_count += 1
            
            # Throttled update
            now = time.time()
            if now - last_update_time > 5:
                percentage = (processed_count / total_files) * 100
                await safe_edit_message(
                    status_msg,
                    f"**Phase 1/3: Analyzing Files...**\n\n"
                    f"Progress: `{processed_count} / {total_files}` ({percentage:.1f}%)\n\n"
                    "This is an automated process. Feel free to leave this screen; the backup will continue.",
                    reply_markup=cancel_button
                )
                last_update_time = now

        total_batches = len(logical_batches)

        # --- PHASE 2 & 3: POSTING ---
        current_batch_num = 0
        for batch_title, files_in_batch in logical_batches.items():
            if cancel_event.is_set(): raise asyncio.CancelledError("Backup cancelled by user.")
            current_batch_num += 1
            
            # Throttled update
            now = time.time()
            if now - last_update_time > 5:
                percentage = (current_batch_num / total_batches) * 100
                await safe_edit_message(
                    status_msg,
                    f"**Phase 2&3: Posting Batches...**\n\n"
                    f"Progress: `{current_batch_num} / {total_batches}` ({percentage:.1f}%)\n"
                    f"Current: `{batch_title}`\n\n"
                    "This is an automated process. Feel free to leave this screen; the backup will continue.",
                    reply_markup=cancel_button
                )
                last_update_time = now
            
            try:
                posts_to_send = await create_backup_post(client, user_id, files_in_batch, imdb_cache)
                for dest_ch_id in destination_channels:
                    for poster, caption, footer in posts_to_send:
                        if cancel_event.is_set(): raise asyncio.CancelledError("Backup cancelled by user.")
                        try:
                            if poster:
                                await client.send_photo(dest_ch_id, photo=poster, caption=caption, reply_markup=footer)
                            else:
                                await client.send_message(dest_ch_id, caption, reply_markup=footer, disable_web_page_preview=True)
                            await asyncio.sleep(2.5)
                        except Exception as post_err:
                            logger.error(f"Failed to post to backup channel {dest_ch_id}. Error: {post_err}")
                            await client.send_message(user_id, f"Skipped posting to `{dest_ch_id}` during backup due to an error: `{post_err}`")
                            continue
            except Exception as e:
                logger.error(f"Failed to create backup post for batch '{batch_title}'. Error: {e}", exc_info=True)
                await client.send_message(user_id, f"Skipped batch '{batch_title}' during backup due to an error: `{e}`")

        await status_msg.delete()
        await client.send_message(user_id, f"✅ **Backup Complete!**\n\nSuccessfully backed up `{total_files}` files in `{total_batches}` posts.", reply_markup=go_back_button(user_id))

    except asyncio.CancelledError:
        await safe_edit_message(status_msg, "❌ Backup cancelled by user.", reply_markup=go_back_button(user_id))
    except Exception as e:
        logger.exception("Major error in new backup process")
        await safe_edit_message(status_msg, f"A major error occurred: {e}", reply_markup=go_back_button(user_id))
    finally:
        ACTIVE_BACKUP_TASKS.pop(user_id, None)
        imdb_cache.clear()


@Client.on_callback_query(filters.regex(r"cancel_backup_"))
async def cancel_backup_handler(client, query):
    user_id = int(query.data.split("_")[-1])
    if query.from_user.id != user_id: return await query.answer("This is not for you.", show_alert=True)
    
    if user_id in ACTIVE_BACKUP_TASKS:
        ACTIVE_BACKUP_TASKS[user_id].set()
        await query.answer("Cancellation signal sent. The process will stop shortly.", show_alert=True)
    else:
        await query.answer("No active backup process found to cancel.", show_alert=True)

@Client.on_callback_query(filters.regex("manage_footer"))
async def manage_footer_handler(client, query):
    user = await get_user(query.from_user.id)
    if not user: await add_user(query.from_user.id); user = await get_user(query.from_user.id)

    buttons = user.get('footer_buttons', [])
    text = "**👣 Manage Footer Buttons**\n\nYou can add up to 3 URL buttons to your post footers."
    kb = [[InlineKeyboardButton(f"❌ {btn['name']}", callback_data=f"rm_footer_{btn['name']}")] for btn in buttons]
    if len(buttons) < 3: kb.append([InlineKeyboardButton("➕ Add New Button", callback_data="add_footer")])
    if buttons:
        kb.append([InlineKeyboardButton("🗑️ Reset All Buttons", callback_data="reset_footer")])
    kb.append([InlineKeyboardButton("« Go Back", callback_data=f"go_back_{query.from_user.id}")])
    await safe_edit_message(query, text=text, reply_markup=InlineKeyboardMarkup(kb))

@Client.on_callback_query(filters.regex("reset_footer"))
async def reset_footer_handler(client, query):
    user_id = query.from_user.id
    await remove_all_footer_buttons(user_id)
    await query.answer("✅ All footer buttons have been reset.", show_alert=True)
    await manage_footer_handler(client, query)

@Client.on_callback_query(filters.regex("add_footer"))
async def add_footer_handler(client, query):
    user_id = query.from_user.id
    prompt_msg = None
    try:
        prompt_msg = await query.message.edit_text(
            "**➕ Add Footer Button: Step 1/2**\n\n"
            "Send the **text** for your new button.\n\n"
            "**Example:** `Visit My Channel`",
            reply_markup=go_back_button(user_id)
        )
        button_name_msg = await client.listen(chat_id=user_id, timeout=300)
        button_name = button_name_msg.text.strip()
        await button_name_msg.delete()

        if len(button_name.encode('utf-8')) > 50:
            await prompt_msg.edit_text(
                "❌ **Error!**\n\nButton text is too long. Please keep it under 50 bytes.",
                reply_markup=go_back_button(user_id)
            )
            return

        await prompt_msg.edit_text(
            f"**➕ Add Footer Button: Step 2/2**\n\n"
            f"Button Text: `{button_name}`\n\n"
            "Now, send the **URL** for the button.\n\n"
            "**Example:** `https://t.me/your_channel_name`",
            reply_markup=go_back_button(user_id)
        )
        button_url_msg = await client.listen(chat_id=user_id, timeout=300)
        button_url = button_url_msg.text.strip()
        await button_url_msg.delete()

        if not button_url.startswith(("http://", "https://")):
            button_url = "https://" + button_url

        await prompt_msg.edit_text(f"⏳ **Validating URL...**\n`{button_url}`")
        is_valid = False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.head(button_url, timeout=5, allow_redirects=True) as resp:
                    if resp.status in range(200, 400):
                        is_valid = True
        except Exception as e:
            logger.error(f"URL validation failed for footer button: {e}")

        if is_valid:
            await add_footer_button(user_id, button_name, button_url)
            await prompt_msg.edit_text("✅ New footer button added!")
            await asyncio.sleep(2)
            await manage_footer_handler(client, query)
        else:
            await prompt_msg.edit_text(
                "❌ **Validation Failed!**\n\nThe URL you provided appears to be invalid or inaccessible. "
                "Your button has **not** been saved.\n\n"
                "Please check the URL and try again.",
                reply_markup=go_back_button(user_id)
            )
    except ListenerTimeout: # --- LEGENDARY FIX: Handle Listener Timeout ---
        if prompt_msg: await safe_edit_message(prompt_msg, text="❗️ **Timeout:** Cancelled.", reply_markup=go_back_button(user_id))
    except Exception as e:
        logger.exception("Error in add_footer_handler")
        if prompt_msg: await safe_edit_message(prompt_msg, text=f"An error occurred: {e}", reply_markup=go_back_button(user_id))


@Client.on_callback_query(filters.regex(r"rm_footer_"))
async def remove_footer_handler(client, query):
    await remove_footer_button(query.from_user.id, query.data.split("_", 2)[2])
    await query.answer("Button removed!", show_alert=True)
    await manage_footer_handler(client, query)

@Client.on_callback_query(filters.regex(r"manage_(post|db)_ch"))
async def manage_channels_handler(client, query):
    user_id, ch_type = query.from_user.id, query.data.split("_")[1]
    
    is_post_type = ch_type == 'post'
    ch_type_name = "Auto Post Channel" if is_post_type else "Database Channel"
    
    text = f"**⚙️ Manage Your {ch_type_name}(s)**\n\n"
    buttons = []
    
    if is_post_type:
        channels = await get_post_channels(user_id)
        text += "You can add up to 5 auto-post channels."
    else:
        db_channel = await get_index_db_channel(user_id)
        channels = [db_channel] if db_channel else []
        text += "You can only have 1 database channel."

    if channels:
        await query.answer("Checking channel status...")
        text += "\n\nHere are your connected channels. Click to remove.\n"
        for ch_id in channels:
            try:
                chat = await client.get_chat(ch_id)
                member = await client.get_chat_member(ch_id, "me")
                if member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                    buttons.append([InlineKeyboardButton(f"✅ {chat.title}", callback_data=f"rm_{ch_type}_{ch_id}")])
                else:
                    buttons.append([InlineKeyboardButton(f"⚠️ Admin rights needed in {chat.title}", callback_data=f"rm_{ch_type}_{ch_id}")])
            except Exception as e:
                logger.warning(f"Could not access channel {ch_id} for user {user_id}. Error: {e}")
                buttons.append([InlineKeyboardButton(f"👻 Ghost Channel - Click to Remove", callback_data=f"rm_{ch_type}_{ch_id}")])
    else:
        text += "\nYou haven't added any channels yet."

    add_button_text = "➕ Add More Channels" if channels else "➕ Add New Channel"
    can_add_more = (is_post_type and len(channels) < 5) or (not is_post_type and not channels)
    if can_add_more:
        buttons.append([InlineKeyboardButton(add_button_text, callback_data=f"add_{ch_type}_ch")])
        
    buttons.append([InlineKeyboardButton("« Go Back", callback_data="manage_channels_menu")])
    await safe_edit_message(query, text=text, reply_markup=InlineKeyboardMarkup(buttons))


@Client.on_callback_query(filters.regex(r"rm_(post|db)_-?\d+"))
async def remove_channel_handler(client, query):
    _, ch_type, ch_id_str = query.data.split("_")
    user_id = query.from_user.id
    ch_id = int(ch_id_str)
    
    if ch_type == 'post':
        await remove_from_list(user_id, "post_channels", ch_id)
        deleted_count = await delete_posts_from_channel(user_id, ch_id)
        logger.info(f"Deleted {deleted_count} backed up posts for user {user_id} from channel {ch_id}.")
    else:
        await update_user(user_id, "index_db_channel", None)
        
    await query.answer("Channel removed!", show_alert=True)
    query.data = f"manage_{ch_type}_ch"
    await manage_channels_handler(client, query)

@Client.on_callback_query(filters.regex(r"add_(post|db)_ch"))
async def add_channel_prompt(client, query):
    await query.answer()
    asyncio.create_task(add_channel_logic(client, query))

async def add_channel_logic(client, query):
    user_id, ch_type_short = query.from_user.id, query.data.split("_")[1]
    
    is_post_type = ch_type_short == 'post'
    if is_post_type:
        post_channels = await get_post_channels(user_id)
        if len(post_channels) >= 5:
            await client.send_message(user_id, "You have already added the maximum of 5 Auto Post channels.")
            return
    else:
        db_channel = await get_index_db_channel(user_id)
        if db_channel:
            await client.send_message(user_id, "You can only have one Database channel. Please remove the existing one first.")
            return
            
    ch_type_name = "Auto Post" if is_post_type else "Database"
    prompt_msg = None
    try:
        prompt_msg = await query.message.edit_text(
            f"Forward a message from your target **{ch_type_name} Channel**.\n\n"
            "__I must be an admin there to work correctly.__",
            reply_markup=go_back_button(user_id)
        )
        response = await client.listen(chat_id=user_id, filters=filters.forwarded, timeout=300)
        
        if response and response.forward_from_chat:
            channel_id = response.forward_from_chat.id
            
            try:
                member = await client.get_chat_member(channel_id, "me")
                if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                    raise ChatAdminRequired
            except (ChatAdminRequired, ChannelPrivate):
                 await response.reply_text("❌ **Error!**\nFirst, make me admin there before forwarding the message. Please make me an admin and try again.", reply_markup=go_back_button(user_id))
                 if prompt_msg: await prompt_msg.delete()
                 return
            except Exception as e:
                await response.reply_text(f"❌ **Error!**\nCould not verify admin status. Error: `{e}`", reply_markup=go_back_button(user_id))
                if prompt_msg: await prompt_msg.delete()
                return

            if ch_type_short == 'post':
                await set_post_channel(user_id, channel_id)
            else:
                await set_index_db_channel(user_id, channel_id)

            await response.reply_text(f"✅ Connected to **{response.forward_from_chat.title}** as a {ch_type_name} channel.", reply_markup=go_back_button(user_id))
        else: 
            await response.reply_text("This is not a valid forwarded message from a channel.", reply_markup=go_back_button(user_id))
            
        if prompt_msg: await prompt_msg.delete()
        if response: await response.delete()
        
    except ListenerTimeout: # --- LEGENDARY FIX: Handle Listener Timeout ---
        if prompt_msg: await safe_edit_message(prompt_msg, text="❗️ **Timeout:** Command cancelled.", reply_markup=go_back_button(user_id))
    except Exception as e:
        logger.exception("Error in add_channel_prompt")
        await query.message.reply_text(f"An error occurred: {e}", reply_markup=go_back_button(user_id))
    finally:
        if 'response' in locals() and response:
            try: await response.delete()
            except: pass


@Client.on_callback_query(filters.regex("^set_filename_link$"))
async def set_filename_link_handler(client, query):
    user_id = query.from_user.id
    try:
        prompt = await query.message.edit_text("Please send the full URL you want your filenames to link to.", reply_markup=go_back_button(user_id))
        response = await client.listen(chat_id=user_id, timeout=300, filters=filters.text)
        
        url_text = response.text.strip()
        if not url_text.startswith(("http://", "https://")):
            url_text = "https://" + url_text
            
        await update_user(user_id, "filename_url", url_text)
        await response.reply_text("✅ Filename link updated!", reply_markup=go_back_button(user_id))
        await prompt.delete()
    except ListenerTimeout: # --- LEGENDARY FIX: Handle Listener Timeout ---
        await safe_edit_message(query, text="❗️ **Timeout:** Cancelled.", reply_markup=go_back_button(user_id))
    except:
        logger.exception("Error in set_filename_link_handler"); await safe_edit_message(query, text="An error occurred.", reply_markup=go_back_button(user_id))

@Client.on_callback_query(filters.regex("^(set_fsub|set_download|remove_fsub)$"))
async def fsub_and_download_handler(client, query):
    await query.answer()
    asyncio.create_task(fsub_and_download_logic(client, query))

async def fsub_and_download_logic(client, query):
    user_id = query.from_user.id
    action = query.data.split("_")[1]

    if action == "fsub" and query.data == "remove_fsub":
        await update_user(user_id, "fsub_channel", None)
        await client.send_message(user_id, "FSub channel has been removed.")
        text, markup = await get_fsub_menu_parts(client, user_id)
        await safe_edit_message(query, text, reply_markup=markup)
        return

    prompts = {
        "fsub": ("📢 **Set FSub**\n\nForward a message from your FSub channel. I must be an admin there to work correctly.", "fsub_channel"),
        "download": ("❓ **Set 'How to Download'**\n\nSend your tutorial URL.", "how_to_download_link")
    }
    prompt_text, key = prompts[action]
    
    prompt = None
    response = None
    try:
        initial_text = prompt_text
        if action == "download":
            user = await get_user(user_id)
            if user and user.get(key):
                initial_text += f"\n\n**Current Link:** `{user.get(key)}`"
        prompt = await query.message.edit_text(initial_text, reply_markup=go_back_button(user_id), disable_web_page_preview=True)
        
        listen_filters = filters.forwarded if action == "fsub" else filters.text
        response = await client.listen(chat_id=user_id, timeout=300, filters=listen_filters)
        
        if action == "fsub":
            if not response.forward_from_chat:
                await safe_edit_message(prompt, "This is not a valid forwarded message from a channel.", reply_markup=go_back_button(user_id))
                return
            
            channel_id = response.forward_from_chat.id
            await safe_edit_message(prompt, "⏳ Checking permissions in the channel...")
            
            try:
                member = await client.get_chat_member(channel_id, "me")
                if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                    raise UserNotParticipant
            except (UserNotParticipant, ChannelPrivate, ChatAdminRequired) as e:
                logger.error(f"FSub permission check failed for user {user_id}, channel {channel_id}: {e}")
                await safe_edit_message(prompt, 
                    "❌ **Permission Denied!**\n\nThe channel is private or I'm not an admin there. "
                    "Please make sure I am a member of the channel and have been promoted to an admin, then try again.",
                    reply_markup=go_back_button(user_id)
                )
                return

            await update_user(user_id, key, channel_id)
            await safe_edit_message(prompt, f"✅ **Success!** FSub channel updated to **{response.forward_from_chat.title}**.")
            await asyncio.sleep(2)
            text, markup = await get_fsub_menu_parts(client, user_id)
            await safe_edit_message(prompt, text, reply_markup=markup)
        
        else:
            url_to_check = response.text.strip()
            if not url_to_check.startswith(("http://", "https://")): url_to_check = "https://" + url_to_check
            await safe_edit_message(prompt, f"⏳ **Validating URL...**\n`{url_to_check}`")
            
            is_valid = False
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.head(url_to_check, timeout=5, allow_redirects=True) as resp:
                        if resp.status in range(200, 400): is_valid = True
            except Exception as e: logger.error(f"URL validation failed for {url_to_check}: {e}")

            if is_valid:
                await update_user(user_id, key, url_to_check)
                await safe_edit_message(prompt, "✅ **Success!** Your 'How to Download' link has been saved.")
                await asyncio.sleep(2)
                await how_to_download_menu_handler(client, query)
            else:
                await safe_edit_message(prompt, "❌ **Validation Failed!**\n\nThe URL you provided is invalid or inaccessible. Your settings have not been saved.", reply_markup=go_back_button(user_id))

    except ListenerTimeout: # --- LEGENDARY FIX: Handle Listener Timeout ---
        if prompt: await safe_edit_message(prompt, text="❗️ **Timeout:** Cancelled.", reply_markup=go_back_button(user_id))
    except Exception as e:
        logger.exception("Error in handler")
        if prompt: await safe_edit_message(prompt, text=f"An error occurred: {e}", reply_markup=go_back_button(user_id))
    finally:
        if response: 
            try: await response.delete()
            except: pass


@Client.on_callback_query(filters.regex("^set_shortener$"))
async def set_shortener_handler(client, query):
    await query.answer()
    asyncio.create_task(set_shortener_logic(client, query))

async def set_shortener_logic(client, query):
    user_id = query.from_user.id
    prompt_msg = None
    domain_msg = None
    api_msg = None
    try:
        prompt_msg = await query.message.edit_text(
            "**🔗 Step 1/2: Set Domain**\n\n"
            "Please send your shortener website's domain name (e.g., `example.com`).",
            reply_markup=go_back_button(user_id)
        )
        
        domain_msg = await client.listen(chat_id=user_id, timeout=300, filters=filters.text & filters.private)
        
        if not domain_msg: 
             # This case is now handled by the ListenerTimeout exception
             return

        domain = domain_msg.text.strip()
        await domain_msg.delete()

        await prompt_msg.edit_text(
            f"**🔗 Step 2/2: Set API Key**\n\n"
            f"Domain: `{domain}`\n"
            "Now, please send your API key.",
            reply_markup=go_back_button(user_id)
        )

        api_msg = await client.listen(chat_id=user_id, timeout=300, filters=filters.text & filters.private)

        if not api_msg: 
             # This case is now handled by the ListenerTimeout exception
             return

        api_key = api_msg.text.strip()
        await api_msg.delete()
        
        await prompt_msg.edit_text("⏳ **Testing your credentials...**\nPlease wait a moment.")
        is_valid = await validate_shortener(domain, api_key)

        if is_valid:
            await update_user(user_id, "shortener_url", domain)
            await update_user(user_id, "shortener_api", api_key)
            await prompt_msg.edit_text("✅ **Success!**\n\nYour shortener has been verified and saved.")
            await asyncio.sleep(3)
        else:
            await prompt_msg.edit_text(
                "❌ **Validation Failed!**\n\n"
                "The domain or API key you provided appears to be incorrect. "
                "Your settings have **not** been saved.\n\n"
                "Please check your credentials and try again.",
                reply_markup=go_back_button(user_id)
            )
            return

        text, markup = await get_shortener_menu_parts(user_id)
        await safe_edit_message(prompt_msg, text=text, reply_markup=markup)

    except ListenerTimeout: # --- LEGENDARY FIX: Handle Listener Timeout ---
        if prompt_msg: await safe_edit_message(prompt_msg, text="❗️ **Timeout:** Command cancelled.", reply_markup=go_back_button(user_id))
    except Exception as e:
        logger.exception("Error in set_shortener_handler")
        if prompt_msg: await safe_edit_message(prompt_msg, text=f"An error occurred: {e}", reply_markup=go_back_button(user_id))
    finally:
        if domain_msg:
            try: await domain_msg.delete()
            except: pass
        if api_msg:
            try: await api_msg.delete()
            except: pass
# ================================================================= #
# 📜 PERSONAL LOG CHANNEL SETTINGS HANDLERS
# ================================================================= #

async def get_log_channel_menu_parts(client, user_id):
    current_log = await get_user_log_channel(user_id)
    
    text = "**📜 Personal Log Channel Settings**\n\n"
    if current_log:
        try:
            chat = await client.get_chat(current_log)
            text += f"Current Log Channel: **{chat.title}** (`{current_log}`)\n\n"
        except Exception:
            text += f"Current Log Channel ID: `{current_log}`\n\n"
        text += "Status: Connected 🟢\nAapki links ki verification activity is channel me aayegi."
    else:
        text += "Status: Not Set 🔴\n\nAapne abhi tak koi Log Channel set nahi kiya hai."

    buttons = [
        [InlineKeyboardButton("✏️ Set / Change Log Channel", callback_data="set_log_channel")],
    ]
    if current_log:
        buttons.append([InlineKeyboardButton("🗑️ Remove Log Channel", callback_data="remove_log_channel")])
    buttons.append([go_back_button(user_id).inline_keyboard[0][0]])
    return text, InlineKeyboardMarkup(buttons)


@Client.on_callback_query(filters.regex("^log_channel_menu$"))
async def log_channel_menu_handler(client, query):
    user_id = query.from_user.id
    text, markup = await get_log_channel_menu_parts(client, user_id)
    await safe_edit_message(query, text=text, reply_markup=markup)


@Client.on_callback_query(filters.regex("^remove_log_channel$"))
async def remove_log_channel_handler(client, query):
    user_id = query.from_user.id
    await remove_user_log_channel(user_id)
    await query.answer("✅ Log Channel removed successfully.", show_alert=True)
    text, markup = await get_log_channel_menu_parts(client, user_id)
    await safe_edit_message(query, text=text, reply_markup=markup)


@Client.on_callback_query(filters.regex("^set_log_channel$"))
async def set_log_channel_prompt(client, query):
    await query.answer()
    asyncio.create_task(set_log_channel_logic(client, query))


async def set_log_channel_logic(client, query):
    user_id = query.from_user.id
    prompt_msg = None
    response = None

    try:
        prompt_msg = await query.message.edit_text(
            "📜 **Set Log Channel**\n\n"
            "1. Apne channel me is Bot ko **Admin** banayein (`Post Messages` permission ke sath).\n"
            "2. Apne target channel se koi message yahan **Forward** karein.",
            reply_markup=go_back_button(user_id)
        )
        
        response = await client.listen(chat_id=user_id, timeout=300, filters=filters.forwarded)

        if not response.forward_from_chat:
            await safe_edit_message(prompt_msg, "❌ Yeh valid channel forward nahi hai. Operation cancelled.", reply_markup=go_back_button(user_id))
            return

        channel_id = response.forward_from_chat.id
        await safe_edit_message(prompt_msg, "⏳ Checking admin permissions...")

        try:
            member = await client.get_chat_member(channel_id, "me")
            if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                raise ChatAdminRequired
            if not member.privileges or not member.privileges.can_post_messages:
                raise ChatAdminRequired
        except (ChatAdminRequired, ChannelPrivate, UserNotParticipant) as e:
            logger.error(f"Log channel permission failed: {e}")
            await safe_edit_message(
                prompt_msg,
                "❌ **Permission Denied!**\n\n"
                "Pehle bot ko channel me Admin banayein aur **Post Messages** ki permission dein, phir dobara try karein.",
                reply_markup=go_back_button(user_id)
            )
            return

        # 1. User DB me save karein
        await set_user_log_channel(user_id, channel_id)

        # 2. Confirmation post user ke log channel me
        try:
            await client.send_message(
                channel_id,
                f"✅ **Log Channel Successfully Connected!**\n👤 **Owner:** [{query.from_user.first_name}](tg://user?id={user_id})"
            )
        except Exception:
            pass

        # 3. Master Log alert trigger karein
        chat_info = await client.get_chat(channel_id)
        await send_client_config_log(client, query.from_user, chat_info)

        await safe_edit_message(prompt_msg, f"✅ **Success!** Connected to **{response.forward_from_chat.title}** as your Log Channel.")
        await asyncio.sleep(2)
        
        text, markup = await get_log_channel_menu_parts(client, user_id)
        await safe_edit_message(prompt_msg, text=text, reply_markup=markup)

    except ListenerTimeout:
        if prompt_msg:
            await safe_edit_message(prompt_msg, text="❗️ **Timeout:** Setup cancelled.", reply_markup=go_back_button(user_id))
    except Exception as e:
        logger.exception("Error in set_log_channel_logic")
        if prompt_msg:
            await safe_edit_message(prompt_msg, text=f"An error occurred: {e}", reply_markup=go_back_button(user_id))
    finally:
        if response:
            try:
                await response.delete()
            except Exception:
                pass
            
