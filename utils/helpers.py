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
    ia = Cinemagoer('http')
except Exception:
    ia = Cinemagoer()

LANGUAGE_MAP = {
    'hin': 'Hindi', 'hindi': 'Hindi',
    'eng': 'English', 'english': 'English',
    'tam': 'Tamil', 'tamil': 'Tamil',
    'tel': 'Telugu', 'telugu': 'Telugu',
    'mal': 'Malayalam', 'malayalam': 'Malayalam',
    'kan': 'Kannada', 'kannada': 'Kannada',
    'pun': 'Punjabi', 'punjabi': 'Punjabi',
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
    'multi': 'Multi-Audio', 'dual': 'Dual-Audio'
}

# Known Indian Serials mapping for clean detection
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
    "sairaab": "Sairaab"
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
    if not title_from_filename:
        return None, None
    try:
        loop = asyncio.get_event_loop()
        
        # Word-by-word trim lookup (Waterfall for clean show detection)
        words = title_from_filename.split()
        search_queries = [" ".join(words[:i]) for i in range(len(words), 0, -1)]
        
        for q in search_queries[:4]:
            results = await loop.run_in_executor(None, lambda: ia.search_movie(q, results=1))
            if results:
                movie = results[0]
                imdb_title_raw = movie.get('title')
                if not imdb_title_raw:
                    continue
                
                # Direct match check
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
    
    # 2. Clean URLs, @mentions
    name_for_parsing = clean_base.replace('_', ' ').replace('.', ' ')
    name_for_parsing = re.sub(r'(?:www\.)?[\w-]+\.(?:com|org|net|xyz|me|io|in|cc|biz|world|info|club|mobi|press|top|site|tech|online|store|live|co|shop|fun|tamilmv)\b', '', name_for_parsing, flags=re.IGNORECASE)
    name_for_parsing = re.sub(r'@[a-zA-Z0-9_]+', '', name_for_parsing).strip()

    season_info_str = ""
    episode_info_str = ""
    raw_detected_to_remove = []

    # 3. Detect Season and Episode Patterns
    patterns = [
        (r'\bS(\d{1,2})\s*[-_.]?\s*(?:E|EP|Episode)\s*(\d{1,4})\b', 'se_both'),
        (r'\b(?:Season|S)\s*(\d{1,2})\s+.*?Episode\s*(\d{1,4})\b', 'se_both'),
        (r'\bS(\d{1,2}).*?EP\((\d{1,4})-(\d{1,4})\)', 'se_range'),
        (r'\bS(\d{1,2}).*?\[E?(\d{1,4})\s*-\s*E?(\d{1,4})\]', 'se_range'),
        (r'\bS(\d{1,2})\s*[-_.]?\s*E?p?(\d{1,4})', 'season_single'),
        (r'\b(?:Season|S)\s*(\d{1,2})\b', 'season_only'),
        (r'\b(?:Episode|Epi|Ep|E)\s*[-_.]?\s*(\d{1,4})\b', 'ep_only'),
        (r'\b(?:Ep|Episode)\s*(\d{1,4})\s*-\s*(\d{1,4})\b', 'ep_range'),
    ]

    for pat, p_type in patterns:
        m = re.search(pat, name_for_parsing, re.IGNORECASE)
        if m:
            raw_detected_to_remove.append(m.group(0))
            if p_type == 'se_both':
                if not season_info_str: season_info_str = f"S{int(m.group(1)):02d}"
                if not episode_info_str: episode_info_str = f"Episode {int(m.group(2))}"
            elif p_type == 'se_range':
                if not season_info_str: season_info_str = f"S{int(m.group(1)):02d}"
                if not episode_info_str: episode_info_str = f"Episode {int(m.group(2))}-{int(m.group(3))}"
            elif p_type == 'season_single':
                if not season_info_str: season_info_str = f"S{int(m.group(1)):02d}"
                if not episode_info_str: episode_info_str = f"Episode {int(m.group(2))}"
            elif p_type == 'season_only' and not season_info_str:
                season_info_str = f"S{int(m.group(1)):02d}"
            elif p_type == 'ep_only' and not episode_info_str:
                episode_info_str = f"Episode {int(m.group(1))}"
            elif p_type == 'ep_range' and not episode_info_str:
                episode_info_str = f"Episode {int(m.group(1))}-{int(m.group(2))}"

    for rem in raw_detected_to_remove:
        name_for_parsing = name_for_parsing.replace(rem, ' ')

    name_for_ptn = re.sub(r'\[.*?\]', '', name_for_parsing).strip()
    parsed_info = PTN.parse(name_for_ptn)
    
    initial_title = parsed_info.get('title', '').strip()
    
    if not season_info_str and parsed_info.get('season'):
        season_info_str = f"S{parsed_info.get('season'):02d}"
        
    if not episode_info_str and parsed_info.get('episode'):
        ep = parsed_info.get('episode')
        if isinstance(ep, list):
            episode_info_str = f"Episode {min(ep)}-{max(ep)}" if len(ep) > 1 else f"Episode {ep[0]}"
        else:
            episode_info_str = f"Episode {ep}"
            
    year_from_filename = parsed_info.get('year')
    
    # Language detection
    found_languages = set()
    search_string_lower = name.lower()
    ptn_audio_tags = parsed_info.get('audio', '')
    if isinstance(ptn_audio_tags, list):
        ptn_audio_tags = " ".join(ptn_audio_tags)
    search_string_lower += " " + ptn_audio_tags.lower()
    
    for key, value in LANGUAGE_MAP.items():
        if re.search(r'\b' + key + r'\b', search_string_lower):
            found_languages.add(value)

    title_to_clean = initial_title
    if year_from_filename:
        title_to_clean = re.sub(r'\b' + str(year_from_filename) + r'\b', '', title_to_clean)
        
    title_to_clean = re.sub(r'\bS\d{1,2}\b|\bE\d{1,4}\b', '', title_to_clean, flags=re.IGNORECASE)
    
    junk_words = [
        'Ep', 'Eps', 'Episode', 'Episodes', 'Season', 'Series', 'South', 'Dubbed', 'Completed',
        'Web', r'\d+Kbps', 'UNCUT', 'ORG', 'HQ', 'ESubs', 'MSubs', 'REMASTERED', 'REPACK',
        'PROPER', 'iNTERNAL', 'Sample', 'Video', 'Dual', 'Audio', 'Multi', 'Hollywood', 'Movies',
        'New', 'Combined', 'Complete', 'Chapter', 'PSA', 'JC', 'DIDAR', 'StarBoy', 'Join Us',
        'Hindi', 'English', 'Tamil', 'Telugu', 'Kannada', 'Malayalam', 'Punjabi', 'Japanese', 'Korean',
        'NF', 'AMZN', 'MAX', 'DSNP', 'ZEE5', 'WEB-DL', 'HDRip', 'WEBRip', 'HEVC', 'x265', 'x264', 'AAC',
        '1tamilmv', 'www', 'mp4', 'mkv', 'avi'
    ]
    junk_pattern_re = r'\b(' + r'|'.join(junk_words) + r')\b'
    cleaned_title = re.sub(junk_pattern_re, '', title_to_clean, flags=re.IGNORECASE)
    cleaned_title = re.sub(r'[-_.]', ' ', cleaned_title)
    cleaned_title = re.sub(r'^[^\w\s]+', '', cleaned_title)
    cleaned_title = re.sub(r'\s+', ' ', cleaned_title).strip()
    
    # Fast shortcut detection for TV serial titles
    matched_show = None
    cleaned_lower = cleaned_title.lower()
    for key, val in SERIAL_SHORTCUTS.items():
        if key in cleaned_lower:
            matched_show = val
            break

    if matched_show:
        final_title = matched_show
        definitive_year = None
    else:
        definitive_title, definitive_year = await get_definitive_title_from_imdb(cleaned_title)
        final_title = definitive_title if definitive_title else cleaned_title.title()
        final_title = re.sub(r'^[^\w]+', '', final_title).strip()

    final_year = definitive_year if definitive_year else year_from_filename

    # Build Header: Pure Title + Season + Episode
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
        
    return {
        "batch_title": f"{final_title} {season_info_str}".strip(),
        "display_title": display_title_main,
        "year": final_year,
        "is_series": bool(season_info_str or episode_info_str),
        "season_info": season_info_str, 
        "episode_info": episode_info_str,
        "languages": sorted(list(found_languages)),
        "quality_tags": " | ".join(filter(None, [parsed_info.get('resolution'), parsed_info.get('quality'), parsed_info.get('codec')]))
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
  
