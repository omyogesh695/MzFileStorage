# utils/helpers.py

import re
import base64
import logging
import PTN
import asyncio
import unicodedata
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant, ChatAdminRequired, ChannelInvalid, PeerIdInvalid, ChannelPrivate
from config import Config
from database.db import get_user, remove_from_list, update_user
from features.poster import get_poster
from features.shortener import get_shortlink

# Cinemagoer disabled to prevent SQLite title_basics crashes on container environments
ia = None

try:
    from rapidfuzz import fuzz
except ImportError:
    import difflib
    class FuzzFallback:
        @staticmethod
        def ratio(s1, s2):
            return int(difflib.SequenceMatcher(None, s1, s2).ratio() * 100)
        @staticmethod
        def token_sort_ratio(s1, s2):
            return int(difflib.SequenceMatcher(None, " ".join(sorted(s1.split())), " ".join(sorted(s2.split()))).ratio() * 100)
    fuzz = FuzzFallback()

logger = logging.getLogger(__name__)

PHOTO_CAPTION_LIMIT = 1024
TEXT_MESSAGE_LIMIT = 4096

LANGUAGE_MAP = {
    # 🇮🇳 Indian Languages
    'hin': 'Hindi', 'hindi': 'Hindi',
    'eng': 'English', 'english': 'English',
    'tam': 'Tamil', 'tamil': 'Tamil',
    'tel': 'Telugu', 'telugu': 'Telugu',
    'mal': 'Malayalam', 'malayalam': 'Malayalam',
    'kan': 'Kannada', 'kannada': 'Kannada',
    'pun': 'Punjabi', 'punjabi': 'Punjabi',
    'ben': 'Bengali', 'bengali': 'Bengali',
    'mar': 'Marathi', 'marathi': 'Marathi',
    'guj': 'Gujarati', 'gujarati': 'Gujarati',
    'ori': 'Odia', 'odia': 'Odia',
    'asm': 'Assamese', 'assamese': 'Assamese',
    'urd': 'Urdu', 'urdu': 'Urdu',
    'nep': 'Nepali', 'nepali': 'Nepali',
    'sin': 'Sinhala', 'sinhala': 'Sinhala',

    # 🌍 International Languages
    'jap': 'Japanese', 'japanese': 'Japanese',
    'kor': 'Korean', 'korean': 'Korean',
    'chi': 'Chinese', 'chinese': 'Chinese',
    'fre': 'French', 'french': 'French',
    'ger': 'German', 'german': 'German',
    'spa': 'Spanish', 'spanish': 'Spanish',
    'ita': 'Italian', 'italian': 'Italian',
    'rus': 'Russian', 'russian': 'Russian',
    'ara': 'Arabic', 'arabic': 'Arabic',
    'tur': 'Turkish', 'turkish': 'Turkish',
    'ind': 'Indonesian', 'indonesian': 'Indonesian',
    'por': 'Portuguese', 'portuguese': 'Portuguese',
    'dut': 'Dutch', 'dutch': 'Dutch',
    'pol': 'Polish', 'polish': 'Polish',
    'vie': 'Vietnamese', 'vietnamese': 'Vietnamese',
    'tha': 'Thai', 'thai': 'Thai',
    'fil': 'Filipino', 'filipino': 'Filipino',
    'heb': 'Hebrew', 'hebrew': 'Hebrew',
    'gre': 'Greek', 'greek': 'Greek',
    'swe': 'Swedish', 'swedish': 'Swedish',
    'nor': 'Norwegian', 'norwegian': 'Norwegian',
    'dan': 'Danish', 'danish': 'Danish',
    'fin': 'Finnish', 'finnish': 'Finnish',

    # 🎬 Special Tags
    'multi': 'Multi-Audio',
    'dual': 'Dual-Audio',
    'dub': 'Dubbed',
    'dubbed': 'Dubbed',
    'org': 'Original Audio',
    'original': 'Original Audio',
}

def simple_clean_filename(name: str) -> str:
    clean_name = ".".join(name.split('.')[:-1]) if '.' in name else name
    clean_name = re.sub(r'[\(\[\{].*?[\)\]\}]', '', clean_name)
    clean_name = clean_name.replace('\xa0', ' ').replace('\u200b', ' ')
    clean_name = clean_name.replace('.', ' ').replace('_', ' ').strip()
    clean_name = re.sub(r'\s+', ' ', clean_name).strip()
    return clean_name

def go_back_button(user_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton("« Go Back", callback_data=f"go_back_{user_id}")]])

def format_bytes(size):
    if not isinstance(size, (int, float)) or size == 0:
        return ""
    power = 1024
    n = 0
    power_labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while size >= power and n < len(power_labels) - 1:
        size /= power
        n += 1
    if n >= 3: return f"{size:.1f} {power_labels[n]}"
    elif n == 2: return f"{round(size)} {power_labels[n]}"
    else: return f"{int(size)} {power_labels[n]}"

async def get_definitive_title_from_imdb(title_from_filename):
    # Pure bypass to ensure lightning-fast execution and zero SQLite crashes
    return None, None

def extract_year_from_filename(filename: str) -> int | None:
    clean_fn = filename.replace('\xa0', ' ').replace('\u200b', ' ')
    match = re.search(r'(?:\D|^)(19\d{2}|20\d{2})(?:\D|$)', clean_fn)
    if match:
        return int(match.group(1))
    return None

async def clean_and_parse_filename()
        start()].strip()

async def create_post(client, user_id, messages, cache: dict):
    user = await get_user(user_id)
    if not user: return []

    media_info_list = []
    parse_tasks = [clean_and_parse_filename(getattr(m, m.media.value, None).file_name, cache) for m in messages if getattr(m, m.media.value, None)]
    parsed_results = await asyncio.gather(*parse_tasks)

    for i, info in enumerate(parsed_results):
        if info:
            media = getattr(messages[i], messages[i].media.value)
            info['file_size'] = media.file_size
            info['file_unique_id'] = media.file_unique_id
            media_info_list.append(info)

    if not media_info_list: return []

    def extract_number(s):
        numbers = re.findall(r'\d+', s or '')
        return int(numbers[-1]) if numbers else 0

    media_info_list.sort(key=lambda x: (
        extract_number(x.get('day_info')),
        extract_number(x.get('episode_info')),
        extract_number(x.get('part_info'))
    ))
    first_info = media_info_list[0]
    
    primary_display_title = first_info['display_title']
    
    # TMDb poster ke liye clean query setup
    poster_search_query = first_info.get('clean_search_title') or first_info['batch_title'].replace(first_info.get('season_info', ''), '').strip()
    poster_search_query = re.sub(r'\b(comedycha\s*5g|comedycha)\b.*$', '', poster_search_query, flags=re.IGNORECASE).strip()
    poster_search_query = re.sub(r'\s+', ' ', poster_search_query).strip()

    post_poster = await get_poster(poster_search_query, first_info['year']) if user.get('show_poster', True) else None
    
    footer_buttons = user.get('footer_buttons', [])
    footer_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(btn['name'], url=btn['url'])] for btn in footer_buttons]) if footer_buttons else None
    
    CAPTION_LIMIT = PHOTO_CAPTION_LIMIT if post_poster else TEXT_MESSAGE_LIMIT
    
    all_link_entries = []
    for info in media_info_list:
        display_tags_parts = []

        day_str = info.get('day_info', '')
        ep_text = ""
        if info.get('episode_info'):
            numbers = re.findall(r'\d+', info['episode_info'])
            if len(numbers) == 1:
                ep_text = f"EP {int(numbers[0])}"
            elif len(numbers) >= 2:
                ep_text = f"EP {int(numbers[0])}-{int(numbers[1])}"

        if day_str and ep_text:
            display_tags_parts.append(f"{day_str} - {ep_text}")
        elif day_str:
            display_tags_parts.append(day_str)
        elif ep_text:
            display_tags_parts.append(ep_text)

        if info.get('part_info') and info.get('part_info') != day_str:
            display_tags_parts.append(info['part_info'])
                
        if info.get('quality_tags'):
            for q_tag in info['quality_tags'].split(' | '):
                q_clean = q_tag.strip()
                if q_clean and q_clean not in display_tags_parts:
                    display_tags_parts.append(q_clean)

        languages = info.get('languages', [])
        for lang in languages:
            lang_clean = lang.strip()
            if lang_clean and lang_clean not in display_tags_parts:
                display_tags_parts.append(lang_clean)
        
        display_tags = " | ".join(filter(None, display_tags_parts))
        
        bot_username = client.me.username
        link = f"https://t.me/{bot_username}?start=get_{user_id}_{info['file_unique_id']}"
        file_size_str = format_bytes(info['file_size'])
        
        entry = (
            f"📁 ➤ {display_tags}\n"
            f"📥 ➪ [Click Here]({link}) ({file_size_str})"
        )
        all_link_entries.append(entry)

    # --- DYNAMIC MULTI-PART CHUNKING [Part 1/2] SYSTEM ---
    chunks = []
    current_chunk = []
    base_header_len = len(f"🔖 **Title: {primary_display_title} [Part 9/9]**\n\n")

    for entry in all_link_entries:
        candidate_text = "\n\n".join(current_chunk + [entry])
        if base_header_len + len(candidate_text) > CAPTION_LIMIT and current_chunk:
            chunks.append(current_chunk)
            current_chunk = [entry]
        else:
            current_chunk.append(entry)

    if current_chunk:
        chunks.append(current_chunk)

    total_parts = len(chunks)
    final_posts = []

    for idx, chunk in enumerate(chunks, 1):
        if total_parts > 1:
            part_header = f"🔖 **Title: {primary_display_title} [Part {idx}/{total_parts}]**\n\n"
        else:
            part_header = f"🔖 **Title: {primary_display_title}**\n\n"

        final_caption = part_header + "\n\n".join(chunk)
        post_img = post_poster if idx == 1 else None
        final_posts.append((post_img, final_caption, footer_keyboard))
            
    return final_posts

def calculate_title_similarity(title1: str, title2: str) -> float:
    return fuzz.token_sort_ratio(title1.lower(), title2.lower())

async def get_title_key(filename: str) -> str:
    media_info = await clean_and_parse_filename(filename)
    return media_info['batch_title'] if media_info else None

async def get_file_raw_link(message):
    return f"https://t.me/c/{str(message.chat.id).replace('-100', '')}/{message.id}"

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'([0-9]+)', s or '')]

async def get_main_menu(user_id):
    user_settings = await get_user(user_id) or {}
    text = "✅ **Setup Complete!**\n\nYou can now forward files to your Index Channel." if user_settings.get('index_db_channel') and user_settings.get('post_channels') else "⚙️ **Bot Settings**\n\nChoose an option below to configure the bot."
    buttons = [
        [InlineKeyboardButton("🗂️ Manage Channels", callback_data="manage_channels_menu")],
        [InlineKeyboardButton("🔗 Shortener", callback_data="shortener_menu"), InlineKeyboardButton("🔄 Backup", callback_data="backup_links")],
        [InlineKeyboardButton("✍️ Filename Link", callback_data="filename_link_menu"), InlineKeyboardButton("👣 Footer Buttons", callback_data="manage_footer")],
        [InlineKeyboardButton("🖼️ IMDb Poster", callback_data="poster_menu"), InlineKeyboardButton("📂 My Files", callback_data="my_files_1")],
        [InlineKeyboardButton("📢 FSub", callback_data="fsub_menu"), InlineKeyboardButton("📊 Daily Stats", callback_data="daily_stats_menu")],
        [InlineKeyboardButton("❓ How to Download", callback_data="how_to_download_menu")]
    ]
    return text, InlineKeyboardMarkup(buttons)

async def notify_and_remove_invalid_channel(client, user_id, channel_id, channel_type):
    try:
        # Pehle get_chat try karein taaki peer resolve ho sake
        await client.get_chat(channel_id)
        await client.get_chat_member(channel_id, "me")
        return True
    except (PeerIdInvalid, ChannelInvalid):
        # Peer cache na hone par channel delete NA karein, sirf ignore karein
        logger.warning(f"Could not resolve peer cache for {channel_id} during startup/check.")
        return True
    except (ChannelPrivate, UserNotParticipant):
        # Jab bot ko sach me channel se nikaal diya gaya ho tabhi remove karein
        db_key = 'index_db_channel' if channel_type == 'Index DB' else 'post_channels'
        user_settings = await get_user(user_id)
        if isinstance(user_settings.get(db_key), list):
            await remove_from_list(user_id, db_key, channel_id)
        else:
            await update_user(user_id, db_key, None)
        try:
            await client.send_message(user_id, f"⚠️ **Channel Inaccessible**\n\nYour {channel_type} Channel (ID: `{channel_id}`) has been removed because the bot is not an admin or participant.")
        except Exception:
            pass
        return False
    except Exception as e:
        logger.error(f"Error checking channel {channel_id}: {e}")
        return True
