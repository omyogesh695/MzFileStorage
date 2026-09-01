# utils/helpers.py

import re
import base64
import logging
import PTN
import asyncio
from imdb import Cinemagoer
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant, ChatAdminRequired, ChannelInvalid, PeerIdInvalid, ChannelPrivate
from config import Config
from database.db import get_user, remove_from_list, update_user
from features.poster import get_poster
from features.shortener import get_shortlink
from thefuzz import fuzz

logger = logging.getLogger(__name__)

PHOTO_CAPTION_LIMIT = 1024
TEXT_MESSAGE_LIMIT = 4096

try:
    ia = Cinemagoer()
except Exception:
    ia = None

LANGUAGE_MAP = {
    'hin': 'Hindi', 'hindi': 'Hindi',
    'eng': 'English', 'english': 'English',
    'tam': 'Tamil', 'tamil': 'Tamil',
    'tel': 'Telugu', 'telugu': 'Telugu',
    'mal': 'Malayalam', 'malayalam': 'Malayalam',
    'kan': 'Kannada', 'kannada': 'Kannada',
    'pun': 'Punjabi', 'punjabi': 'Punjabi',
    'mar': 'Marathi', 'marathi': 'Marathi',
    'beng': 'Bengali', 'bengali': 'Bengali', 'bangla': 'Bengali',
    'guj': 'Gujarati', 'gujarati': 'Gujarati',
    'jap': 'Japanese', 'japanese': 'Japanese',
    'kor': 'Korean', 'korean': 'Korean',
    'chi': 'Chinese', 'chinese': 'Chinese',
    'fre': 'French', 'french': 'French',
    'ger': 'German', 'german': 'German',
    'spa': 'Spanish', 'spanish': 'Spanish',
    'ita': 'Italian', 'italian': 'Italian',
    'rus': 'Russian', 'russian': 'Russian',
    'multi': 'Multi-Audio', 'dual': 'Dual-Audio'
}

# TMDb Exact Matched Show Names for Indian Serials
SERIAL_SHORTCUTS = {
    "anupama": "Anupamaa",
    "anupamaa": "Anupamaa",
    "udne ki aasha": "Udne Ki Aasha",
    "yeh rishta kya kehlata hai": "Yeh Rishta Kya Kehlata Hai",
    "yrkkh": "Yeh Rishta Kya Kehlata Hai",
    "ghkkpm": "Ghum Hai Kisikey Pyaar Meiin",
    "ghum hai kisikey pyaar meiin": "Ghum Hai Kisikey Pyaar Meiin",
    "jhanak": "Jhanak",
    "taarak mehta ka ooltah chashmah": "Taarak Mehta Ka Ooltah Chashmah",
    "tmkoc": "Taarak Mehta Ka Ooltah Chashmah",
    "kundali bhagya": "Kundali Bhagya",
    "kumkum bhagya": "Kumkum Bhagya",
    "sairaab": "Sairaab",
    "maharashtrachi hasyajatra": "Maharashtrachi Hasya Jatra",
    "maharashtrachi hasya jatra": "Maharashtrachi Hasya Jatra",
    "hasyajatra": "Maharashtrachi Hasya Jatra"
}

def simple_clean_filename(name: str) -> str:
    clean_name = ".".join(name.split('.')[:-1]) if '.' in name else name
    clean_name = re.sub(r'[\(\[\{].*?[\)\]\}]', '', clean_name)
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
    if not title_from_filename or ia is None:
        return None, None
    try:
        loop = asyncio.get_event_loop()
        words = title_from_filename.split()
        search_queries = [" ".join(words[:i]) for i in range(len(words), 0, -1)]
        
        for q in search_queries[:4]:
            results = await loop.run_in_executor(None, lambda: ia.search_movie(q, results=1))
            if results:
                movie = results[0]
                imdb_title_raw = movie.get('title')
                if not imdb_title_raw:
                    continue
                if q.lower() in imdb_title_raw.lower() or imdb_title_raw.lower() in q.lower():
                    await loop.run_in_executor(None, lambda: ia.update(movie, info=['main']))
                    return movie.get('title'), movie.get('year')
        return None, None
    except Exception:
        return None, None

async def clean_and_parse_filename(name: str, cache: dict = None):
    original_name = name

    # 1. Strip file extension
    clean_base = re.sub(r'\.(mp4|mkv|avi|webm|ts|mov|flv|m4v)$', '', name, flags=re.IGNORECASE)
    clean_base = clean_base.replace('_', ' ').replace('.', ' ')
    clean_base = re.sub(r'(?:www\.)?[\w-]+\.(?:com|org|net|xyz|me|io|in|cc|biz|world|info|club|mobi|press|top|site|tech|online|store|live|co|shop|fun|tamilmv)\b', '', clean_base, flags=re.IGNORECASE)
    clean_base = re.sub(r'@[a-zA-Z0-9_]+', '', clean_base).strip()

    # 2. Extract Quality directly
    res_match = re.search(r'\b(2160p|4k|1080p|720p|480p|360p|240p)\b', name, re.IGNORECASE)
    found_resolution = res_match.group(1).lower() if res_match else ""

    # 3. Detect Languages
    found_languages = set()
    search_string_lower = name.lower()
    for key, value in LANGUAGE_MAP.items():
        if re.search(r'\b' + key + r'\b', search_string_lower):
            found_languages.add(value)

    season_info_str = ""
    episode_info_str = ""
    show_name_candidate = clean_base

    # 4. Smart TV Season/Episode Isolation
    se_match = re.search(r'\bS(\d{1,2})\s*[-_.]?\s*(?:E|EP|Episode)\s*(\d{1,4})\b', clean_base, re.IGNORECASE)
    if se_match:
        season_info_str = f"S{int(se_match.group(1)):02d}"
        episode_info_str = f"Episode {int(se_match.group(2))}"
        show_name_candidate = clean_base[:se_match.start()].strip()
    else:
        patterns = [
            (r'\b(?:Season|S)\s*(\d{1,2})\s+.*?Episode\s*(\d{1,4})\b', 'se_both'),
            (r'\bS(\d{1,2}).*?EP\((\d{1,4})-(\d{1,4})\)', 'se_range'),
            (r'\bS(\d{1,2}).*?\[E?(\d{1,4})\s*-\s*E?(\d{1,4})\]', 'se_range'),
            (r'\bS(\d{1,2})\s*[-_.]?\s*E?p?(\d{1,4})', 'season_single'),
            (r'\b(?:Season|S)\s*(\d{1,2})\b', 'season_only'),
            (r'\b(?:Episode|Epi|Ep|E)\s*[-_.]?\s*(\d{1,4})\b', 'ep_only'),
            (r'\b(?:Ep|Episode)\s*(\d{1,4})\s*-\s*(\d{1,4})\b', 'ep_range'),
        ]
        for pat, p_type in patterns:
            m = re.search(pat, clean_base, re.IGNORECASE)
            if m:
                if p_type == 'se_both':
                    if not season_info_str: season_info_str = f"S{int(m.group(1)):02d}"
                    if not episode_info_str: episode_info_str = f"Episode {int(m.group(2))}"
                    show_name_candidate = clean_base[:m.start()].strip()
                elif p_type == 'season_single':
                    if not season_info_str: season_info_str = f"S{int(m.group(1)):02d}"
                    if not episode_info_str: episode_info_str = f"Episode {int(m.group(2))}"
                    show_name_candidate = clean_base[:m.start()].strip()
                elif p_type == 'season_only' and not season_info_str:
                    season_info_str = f"S{int(m.group(1)):02d}"
                    show_name_candidate = clean_base[:m.start()].strip()
                elif p_type == 'ep_only' and not episode_info_str:
                    episode_info_str = f"Episode {int(m.group(1))}"
                    show_name_candidate = clean_base[:m.start()].strip()
                break

    # 5. Clean junk words
    junk_words = [
        'Comedycha', '5G', 'Full', 'HD', 'Sony', 'LIV', 'Zee5', 'JioCinema', 'Hotstar',
        'Ep', 'Eps', 'Episode', 'Episodes', 'Season', 'Series', 'Dubbed', 'Completed',
        'Web', r'\d+Kbps', 'UNCUT', 'ORG', 'HQ', 'ESubs', 'MSubs', 'REMASTERED', 'REPACK',
        'PROPER', 'iNTERNAL', 'Sample', 'Video', 'Dual', 'Audio', 'Multi',
        'Hindi', 'English', 'Tamil', 'Telugu', 'Kannada', 'Malayalam', 'Punjabi', 'Marathi',
        'NF', 'AMZN', 'MAX', 'DSNP', 'ZEE5', 'WEB-DL', 'HDRip', 'WEBRip', 'HEVC', 'x265', 'x264', 'AAC',
        '1tamilmv', 'www', 'mp4', 'mkv', 'avi'
    ]
    junk_pattern_re = r'\b(' + r'|'.join(junk_words) + r')\b'
    cleaned_candidate = re.sub(junk_pattern_re, '', show_name_candidate, flags=re.IGNORECASE)
    cleaned_candidate = re.sub(r'[-_.]', ' ', cleaned_candidate)
    cleaned_candidate = re.sub(r'^[^\w\s]+', '', cleaned_candidate)
    cleaned_candidate = re.sub(r'\s+', ' ', cleaned_candidate).strip()

    # 6. Check Shortcuts or IMDb
    matched_show = None
    cand_lower = cleaned_candidate.lower().replace(" ", "")
    for key, val in SERIAL_SHORTCUTS.items():
        if key.replace(" ", "") in cand_lower:
            matched_show = val
            break

    if matched_show:
        final_title = matched_show
        definitive_year = None
    else:
        definitive_title, definitive_year = await get_definitive_title_from_imdb(cleaned_candidate)
        final_title = definitive_title if definitive_title else cleaned_candidate.title()
        final_title = re.sub(r'^[^\w]+', '', final_title).strip()

    name_for_ptn = re.sub(r'\[.*?\]', '', clean_base).strip()
    parsed_info = PTN.parse(name_for_ptn)
    final_year = definitive_year if definitive_year else parsed_info.get('year')

    # Build Header Display Title
    series_tags = []
    if season_info_str:
        series_tags.append(season_info_str)
    if episode_info_str:
        series_tags.append(episode_info_str)

    display_title_main = final_title
    if series_tags:
        for tag in series_tags:
            if tag.lower() not in display_title_main.lower():
                display_title_main += f" {tag}"

    if final_year:
        display_title_main += f" ({final_year})"

    final_quality = found_resolution or parsed_info.get('resolution') or ''

    return {
        "batch_title": f"{final_title} {season_info_str}".strip(),
        "display_title": display_title_main,
        "year": final_year,
        "is_series": bool(season_info_str or episode_info_str),
        "season_info": season_info_str, 
        "episode_info": episode_info_str,
        "languages": sorted(list(found_languages)),
        "quality_tags": final_quality
    }

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

    media_info_list.sort(key=lambda x: natural_sort_key(x.get('episode_info', '')))
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
        
        if info.get('quality_tags'):
            display_tags_parts.append(info['quality_tags'])

        if info.get('episode_info'):
            display_tags_parts.append(info['episode_info'])
        
        languages = info.get('languages', [])
        if languages:
            display_tags_parts.append(" + ".join(languages))
        
        display_tags = " | ".join(filter(None, display_tags_parts))
        
        bot_username = client.me.username if hasattr(client, "me") and client.me else "MzFileStorageBot"
        link = f"https://t.me/{bot_username}?start=get_{user_id}_{info['file_unique_id']}"

        file_size_str = format_bytes(info['file_size'])
        all_link_entries.append(f"├─📁 {display_tags or 'File'}\n│  ╰─➤ [Click Here]({link}) ({file_size_str})")

    final_posts, current_links_part = [], []
    
    base_caption_header = f"╭─🎬 **{primary_display_title}** ─╮"
    clean_header_text = f"🎬 {primary_display_title}"
    footer_middle = '─' * int(len(clean_header_text) * 0.9)
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
        await client.get_chat_member(channel_id, "me")
        return True
    except Exception:
        db_key = 'index_db_channel' if channel_type == 'Index DB' else 'post_channels'
        user_settings = await get_user(user_id)
        if isinstance(user_settings.get(db_key), list):
             await remove_from_list(user_id, db_key, channel_id)
        else:
             await update_user(user_id, db_key, None)
        await client.send_message(user_id, f"⚠️ **Channel Inaccessible**\n\nYour {channel_type} Channel (ID: `{channel_id}`) has been automatically removed because I could not access it.")
        return False
                      
