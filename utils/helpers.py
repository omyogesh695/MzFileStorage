# utils/helpers.py

import re
import base64
import logging
import PTN
import asyncio
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
    'fre': 'French', 'french': 'French',
    'ger': 'German', 'german': 'German',
    'spa': 'Spanish', 'spanish': 'Spanish',
    'ita': 'Italian', 'italian': 'Italian',
    'rus': 'Russian', 'russian': 'Russian',
    'multi': 'Multi-Audio', 'dual': 'Dual-Audio'
}

SERIAL_SHORTCUTS = {
    "anupama": ("Anupamaa", "Hindi"),
    "anupamaa": ("Anupamaa", "Hindi"),
    "udne ki aasha": ("Udne Ki Aasha", "Hindi"),
    "yeh rishta kya kehlata hai": ("Yeh Rishta Kya Kehlata Hai", "Hindi"),
    "yrkkh": ("Yeh Rishta Kya Kehlata Hai", "Hindi"),
    "ghkkpm": ("Ghum Hai Kisikey Pyaar Meiin", "Hindi"),
    "ghum hai kisikey pyaar meiin": ("Ghum Hai Kisikey Pyaar Meiin", "Hindi"),
    "jhanak": ("Jhanak", "Hindi"),
    "taarak mehta ka ooltah chashmah": ("Taarak Mehta Ka Ooltah Chashmah", "Hindi"),
    "tmkoc": ("Taarak Mehta Ka Ooltah Chashmah", "Hindi"),
    "kundali bhagya": ("Kundali Bhagya", "Hindi"),
    "kumkum bhagya": ("Kumkum Bhagya", "Hindi"),
    "sairaab": ("Sairaab", "Hindi"),
    "maharashtrachi hasyajatra": ("Maharashtrachi Hasya Jatra", "Marathi"),
    "maharashtrachi hasya jatra": ("Maharashtrachi Hasya Jatra", "Marathi"),
    "hasyajatra": ("Maharashtrachi Hasya Jatra", "Marathi")
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

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'([0-9]+)', s or '')]

def get_resolution_num(quality_str: str) -> int:
    if not quality_str:
        return 0
    match = re.search(r'(\d{3,4})', quality_str)
    if match:
        return int(match.group(1))
    if '4k' in quality_str.lower() or '2160' in quality_str.lower():
        return 2160
    return 0

async def clean_and_parse_filename(name: str, cache: dict = None):
    original_name = name or ""

    # 1. Strip Extension & Delimiters
    clean_base = re.sub(r'\.(mp4|mkv|avi|webm|ts|mov|flv|m4v)$', '', original_name, flags=re.IGNORECASE)
    clean_base = clean_base.replace('_', ' ').replace('.', ' ')
    
    # 2. Extract Source / Rip Type
    found_source = ""
    source_patterns = [
        (r'\b(?:web[\s\-_]?dl|webdl)\b', 'WEB-DL'),
        (r'\b(?:web[\s\-_]?rip|webrip)\b', 'WEBRip'),
        (r'\b(?:hd[\s\-_]?rip|hdrip)\b', 'HDRip'),
        (r'\b(?:blu[\s\-_]?ray|bdrip|brrip)\b', 'BluRay'),
        (r'\b(?:dvd[\s\-_]?rip|dvd)\b', 'DVDRip'),
        (r'\b(?:hdtc|tc|camrip)\b', 'HDTC'),
        (r'\b(?:hdtv|pdtv)\b', 'HDTV')
    ]
    for sp, s_label in source_patterns:
        if re.search(sp, clean_base, re.IGNORECASE):
            found_source = s_label
            clean_base = re.sub(sp, ' ', clean_base, flags=re.IGNORECASE)
            break

    # 3. Universal Part Detection (Safe from Movie Titles like 'Brahmastra Part 1')
    part_info_str = ""
    part_num = None

    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', clean_base)
    if year_match:
        target_str = original_name[year_match.end():]
    else:
        target_str = original_name

    s_raw = re.sub(r'[\._\-\(\)\[\]\{\}:]', ' ', target_str.lower())

    m_std = re.search(r'\b(?:part|pt|cd|disc|disk|vol|volume)\s*0*([1-9]\d*)\b', s_raw)
    m_of = re.search(r'\b(?:part|pt|cd)?\s*0*([1-9]\d*)\s*(?:of|_of_)\s*\d+\b', s_raw)
    m_roman = re.search(r'\b(?:part|pt|cd|disc|disk)\s+(i|ii|iii|iv|v|vi)\b', s_raw)
    m_word = re.search(r'\b(?:part|pt|cd)\s+(one|two|three|four|five)\b', s_raw)

    if m_std:
        part_num = int(m_std.group(1))
    elif m_of:
        part_num = int(m_of.group(1))
    elif m_roman:
        part_num = {'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5, 'vi': 6}.get(m_roman.group(1))
    elif m_word:
        part_num = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}.get(m_word.group(1))

    if part_num:
        part_info_str = f"Part {part_num:02d}"
        if year_match:
            clean_pre = clean_base[:year_match.end()]
            clean_post = clean_base[year_match.end():]
            clean_post = re.sub(r'\b(?:part|pt|cd|disc|disk|vol|volume)\s*0*\d+\b', ' ', clean_post, flags=re.IGNORECASE)
            clean_post = re.sub(r'\b\d+\s*of\s*\d+\b', ' ', clean_post, flags=re.IGNORECASE)
            clean_post = re.sub(r'\b(?:part|pt|cd|disc|disk)\s+(i|ii|iii|iv|v|vi|one|two|three|four|five)\b', ' ', clean_post, flags=re.IGNORECASE)
            clean_base = clean_pre + clean_post
        else:
            clean_base = re.sub(r'\b(?:part|pt|cd|disc|disk|vol|volume)\s*0*\d+\b', ' ', clean_base, flags=re.IGNORECASE)
            clean_base = re.sub(r'\b\d+\s*of\s*\d+\b', ' ', clean_base, flags=re.IGNORECASE)
            clean_base = re.sub(r'\b(?:part|pt|cd|disc|disk)\s+(i|ii|iii|iv|v|vi|one|two|three|four|five)\b', ' ', clean_base, flags=re.IGNORECASE)

    # 4. Extract Resolution
    res_match = re.search(r'\b(2160p|4k|1080p|720p|576p|540p|480p|360p|240p)\b', clean_base, re.IGNORECASE)
    found_resolution = res_match.group(1).lower() if res_match else ""

    # 5. Extract Languages Directly from Original Raw Filename
    raw_lower = re.sub(r'[\._\-\(\)\[\]\{\}:#~]', ' ', original_name.lower())
    detected_languages = []
    
    lang_checks = [
        (r'\b(hindi|hin)\b', 'Hindi'),
        (r'\b(english|eng)\b', 'English'),
        (r'\b(tamil|tam)\b', 'Tamil'),
        (r'\b(telugu|tel)\b', 'Telugu'),
        (r'\b(malayalam|mal)\b', 'Malayalam'),
        (r'\b(kannada|kan)\b', 'Kannada'),
        (r'\b(marathi|mar)\b', 'Marathi'),
        (r'\b(punjabi|pun)\b', 'Punjabi'),
        (r'\b(bengali|bangla|ben)\b', 'Bengali'),
        (r'\b(gujarati|guj)\b', 'Gujarati'),
        (r'\b(korean|kor)\b', 'Korean'),
        (r'\b(japanese|jap)\b', 'Japanese'),
        (r'\b(french|fre)\b', 'French'),
        (r'\b(german|ger)\b', 'German'),
        (r'\b(spanish|spa)\b', 'Spanish'),
        (r'\b(russian|rus)\b', 'Russian')
    ]
    
    for pattern, lang_name in lang_checks:
        if re.search(pattern, raw_lower) and lang_name not in detected_languages:
            detected_languages.append(lang_name)

    if re.search(r'\b(chinese|mandarin|cantonese)\b', raw_lower) and "Chinese" not in detected_languages:
        detected_languages.append("Chinese")

    if not detected_languages:
        if re.search(r'\bmulti[\s._-]?(?:audio)?\b', raw_lower):
            detected_languages.append("Multi-Audio")
        elif re.search(r'\bdual[\s._-]?(?:audio)?\b', raw_lower):
            detected_languages.append("Dual-Audio")

    # 6. Clean URLs, Tags & Watermarks
    clean_base = re.sub(r'@[a-zA-Z0-9_]+', ' ', clean_base)
    clean_base = re.sub(r'(?:https?://)?(?:www\.)?[\w-]+\.(?:com|org|net|xyz|me|io|in|cc|biz|world|info|club|mobi|press|top|site|tech|online|store|live|co|shop|fun|tamilmv)\b', ' ', clean_base, flags=re.IGNORECASE)
    clean_base = re.sub(r'\b(?:mkvcinemas|telly|sb old movie house|old movie house|bolly4u|vegamovies|luxmovies|hdmovies5|symoviiez|symoviez)\b', ' ', clean_base, flags=re.IGNORECASE)
    clean_base = re.sub(r'[^\w\s\(\)\[\]\.\-_]', ' ', clean_base)
    clean_base = re.sub(r'\s+', ' ', clean_base).strip()

    # 7. Extract TV Season and Compact Episode Numbers (E01-04, E01)
    season_info_str = ""
    episode_info_str = ""
    show_name_candidate = clean_base

    # Episode & Range Parsing Target (Normalize delimiters)
    ep_target = re.sub(r'[\{\}\[\]\(\)]', ' ', original_name)

    # Check 1: Explicit Range (e.g. {E01 - 04}, E01_04, E01-E04, EP01-EP04, Ep 01 to 04)
    m_range = re.search(r'\b(?:e|ep|episode)[\s._\-]*(0*[1-9]\d*)\s*(?:-|to|_)\s*(?:e|ep|episode)?[\s._\-]*(0*[1-9]\d*)\b', ep_target, re.IGNORECASE)
    
    # Check 2: Range in brackets without 'E' (e.g. {01-04}, [01_06])
    if not m_range:
        m_range = re.search(r'[\{\[\(]\s*0*([1-9]\d*)\s*(?:-|to|_)\s*0*([1-9]\d*)\s*[\}\]\)]', original_name)

    # Check 3: Single Episode (e.g. E01, EP05, Episode 1)
    m_single = re.search(r'\b(?:e|ep|episode)[\s._\-]*0*([1-9]\d*)\b', ep_target, re.IGNORECASE)

    if m_range:
        start_ep = int(m_range.group(1))
        end_ep = int(m_range.group(2))
        episode_info_str = f"E{start_ep:02d}-{end_ep:02d}"
        show_name_candidate = re.sub(r'[\{\[\(]?\s*(?:e|ep|episode)?[\s._\-]*0*\d+\s*(?:-|to|_)\s*(?:e|ep|episode)?[\s._\-]*0*\d+\s*[\}\]\)]?', ' ', show_name_candidate, flags=re.IGNORECASE)
    elif m_single:
        ep_num = int(m_single.group(1))
        episode_info_str = f"E{ep_num:02d}"
        show_name_candidate = re.sub(r'\b(?:e|ep|episode)[\s._\-]*0*\d+\b', ' ', show_name_candidate, flags=re.IGNORECASE)

    # Season Check & Clean Title Isolation: Season ke baad ka sara kachra title se cut karein
    s_match = re.search(r'\b(?:season|s)[\s._\-]*0*([1-9]\d*)\b', show_name_candidate, re.IGNORECASE)
    if s_match:
        season_info_str = f"S{int(s_match.group(1)):02d}"
        # Cut string right before the Season tag to protect Title cleanly
        show_name_candidate = show_name_candidate[:s_match.start()].strip()

    is_series = bool(season_info_str or episode_info_str)

    # 8. Extract Movie Year
    final_year = None
    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', show_name_candidate)
    if year_match:
        final_year = int(year_match.group(1))
        # Series ya Movie dono ke liye year ke baad ka residual kachra title mein nahi aana chahiye
        show_name_candidate = show_name_candidate[:year_match.start()].strip()

    # 9. Clean Residual Metadata Words
    junk_words = [
        'Combined', 'Complete', 'Pack', 'Batch', 'Dual', 'Audio', 'Multi',
        'Comedycha', '5G', 'Full', 'HD', 'Sony', 'LIV', 'Zee5', 'JioCinema', 'Hotstar',
        'Ep', 'Eps', 'Episode', 'Episodes', 'Season', 'Series', 'Dubbed', 'Completed',
        'Web', r'\d+Kbps', 'UNCUT', 'ORG', 'HQ', 'ESubs', 'MSubs', 'REMASTERED', 'REPACK',
        'PROPER', 'iNTERNAL', 'Sample', 'Video', 'AMZN', 'JH', 'HS', 'DDP',
        'Hindi', 'English', 'Tamil', 'Telugu', 'Kannada', 'Malayalam', 'Punjabi', 'Marathi',
        'NF', 'MAX', 'DSNP', 'ZEE5', 'HEVC', 'x265', 'x264', 'AAC', '576p',
        '1tamilmv', 'www', 'mp4', 'mkv', 'avi', '2160p', '1080p', '720p', '540p', '480p', '360p',
        r'S\d{1,2}', r'E\d{1,4}'
    ]
    junk_pattern_re = r'\b(' + r'|'.join(junk_words) + r')\b'
    cleaned_candidate = re.sub(junk_pattern_re, ' ', show_name_candidate, flags=re.IGNORECASE)
    cleaned_candidate = re.sub(r'[\(\[\{].*?[\)\]\}]', ' ', cleaned_candidate)
    cleaned_candidate = re.sub(r'[-_.]', ' ', cleaned_candidate)
    cleaned_candidate = re.sub(r'^[^\w\s]+', '', cleaned_candidate)
    cleaned_candidate = re.sub(r'\s+', ' ', cleaned_candidate).strip()

    # 10. Check Shortcuts for Indian Serials
    matched_show = None
    default_lang = None
    cand_lower = cleaned_candidate.lower().replace(" ", "")
    
    for key, (val_title, val_lang) in SERIAL_SHORTCUTS.items():
        if key.replace(" ", "") in cand_lower:
            matched_show = val_title
            default_lang = val_lang
            break

    if matched_show:
        final_title = matched_show
        final_year = None
        if default_lang and not detected_languages:
            detected_languages.append(default_lang)
    else:
        final_title = cleaned_candidate.title()

    if not final_title:
        final_title = " ".join(clean_base.split()[:3]).title()

    # 11. Clean Duplicate Brackets and Format Final Display Title
    final_title = re.sub(r'[\(\[\{\)\]\}]', '', final_title).strip()
    display_title_main = final_title

    if final_year:
        display_title_main += f" ({final_year})"

    if season_info_str and season_info_str.lower() not in display_title_main.lower():
        display_title_main += f" {season_info_str}"

    display_title_main = re.sub(r'\s*\(\s*\(', ' (', display_title_main)
    display_title_main = re.sub(r'\)\s*\)', ')', display_title_main).strip()

    batch_key = f"{final_title} {final_year}" if final_year and not is_series else f"{final_title} {season_info_str}".strip()

    return {
        "batch_title": batch_key,
        "display_title": display_title_main,
        "year": final_year,
        "is_series": is_series,
        "season_info": season_info_str, 
        "episode_info": episode_info_str,
        "part_info": part_info_str,
        "source_tag": found_source,
        "languages": detected_languages,
        "quality_tags": found_resolution
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

    # Sort: Higher Resolution First (1080p -> 720p), then Natural Ascending for Parts and Episodes
    media_info_list.sort(key=lambda x: (
        -get_resolution_num(x.get('quality_tags', '')),
        natural_sort_key(x.get('part_info', '')),
        natural_sort_key(x.get('episode_info', ''))
    ))
    
    first_info = media_info_list[0]
    primary_display_title = first_info['display_title']
    
    poster_search_query = first_info['display_title'].split('(')[0].replace(first_info.get('season_info', ''), '').strip()
    post_poster = await get_poster(poster_search_query, first_info['year']) if user.get('show_poster', True) else None
    
    footer_buttons = user.get('footer_buttons', [])
    footer_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(btn['name'], url=btn['url'])] for btn in footer_buttons]) if footer_buttons else None
    
    CAPTION_LIMIT = PHOTO_CAPTION_LIMIT if post_poster else TEXT_MESSAGE_LIMIT
    
    # --- Metadata Tags Builder (Quality • Codec • Part • Audio) ---
    formatted_items = []
    bot_username = client.me.username if hasattr(client, "me") and client.me else "MzFileStorageBot"

    for info in media_info_list:
        display_tags_parts = []
        
        # 1. Episode Details ({E01-04}, {E01})
        if info.get('episode_info'):
            display_tags_parts.append(f"{{{info['episode_info']}}}")

        # 2. Quality / Resolution (1080p, 720p)
        if info.get('quality_tags'):
            display_tags_parts.append(info['quality_tags'])

        # 3. Source / Rip Type (WEB-DL, BluRay)
        if info.get('source_tag'):
            display_tags_parts.append(info['source_tag'])

        # 4. Part Details ([Part 01], [Part 02])
        if info.get('part_info'):
            display_tags_parts.append(f"[{info['part_info']}]")
        
        # 5. Audio Languages ([Hindi + English])
        languages = info.get('languages', [])
        if languages:
            display_tags_parts.append(f"[{' + '.join(languages)}]")
        
        meta_str = " • ".join(filter(None, display_tags_parts)) or "File"
        link = f"https://t.me/{bot_username}?start=get_{user_id}_{info['file_unique_id']}"
        file_size_str = format_bytes(info['file_size'])

        formatted_items.append({
            "meta": meta_str,
            "link": link,
            "size": file_size_str
        })

    # Clean rendering block (tree lines removed, vertical alignment applied)
    def render_tree_block(items_chunk, title_header):
        lines = [title_header, ""]
        for item in items_chunk:
            lines.append(f"📁 {item['meta']}")
            lines.append(f"📥 [Click Here]({item['link']}) ({item['size']})")
            lines.append("")
        return "\n".join(lines).strip()

    # Clean Header
    clean_title = re.sub(r'[\(\[\{]\s*[\(\[\{]', '(', primary_display_title)
    clean_title = re.sub(r'[\)\]\}]\s*[\)\]\}]', ')', clean_title).strip()
    base_header = f"🎬 **{clean_title}**"

    final_posts = []
    current_chunk = []

    for item in formatted_items:
        test_chunk = current_chunk + [item]
        test_caption = render_tree_block(test_chunk, base_header)
        
        # Check Telegram caption limit (1024 characters for photos)
        if len(test_caption) > CAPTION_LIMIT and current_chunk:
            caption_text = render_tree_block(current_chunk, base_header)
            final_posts.append((post_poster if not final_posts else None, caption_text, footer_keyboard))
            current_chunk = [item]
        else:
            current_chunk = test_chunk

    if current_chunk:
        caption_text = render_tree_block(current_chunk, base_header)
        final_posts.append((post_poster if not final_posts else None, caption_text, footer_keyboard))

    # Multi-post header naming if split occurs
    if len(final_posts) > 1:
        for i, (poster, cap, foot) in enumerate(final_posts):
            part_header = f"🎬 **{clean_title} (Part {i+1}/{len(final_posts)})**"
            new_cap = cap.replace(base_header, part_header)
            final_posts[i] = (poster, new_cap, foot)

    return final_posts

def calculate_title_similarity(title1: str, title2: str) -> float:
    return fuzz.token_sort_ratio(title1.lower(), title2.lower())

async def get_title_key(filename: str) -> str:
    media_info = await clean_and_parse_filename(filename)
    return media_info['batch_title'] if media_info else None

async def get_file_raw_link(message):
    return f"https://t.me/c/{str(message.chat.id).replace('-100', '')}/{message.id}"

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
