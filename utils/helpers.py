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

async def clean_and_parse_filename(name: str, cache: dict = None):
    original_name = name

    # Non-breaking space (\xa0) aur zero-width spaces ko standard space mein badalna
    clean_raw_name = name.replace('\xa0', ' ').replace('\u200b', ' ')

    # Original filename se reliable 4-digit release year nikaalna
    extracted_year = extract_year_from_filename(clean_raw_name)

    # Unicode normalization: stylized letters ko standard text mein convert karna
    normalized_name = unicodedata.normalize('NFKD', clean_raw_name)
    clean_name_ascii = normalized_name.encode('ascii', 'ignore').decode('ascii')
    
    # Telegram channels aur trailing handles remove karein
    clean_name_ascii = re.sub(r'--.*$', '', clean_name_ascii)
    name_for_parsing = clean_name_ascii.replace('_', ' ').replace('.', ' ')
    name_for_parsing = re.sub(r'(?:www\.)?[\w-]+\.(?:com|org|net|xyz|me|io|in|cc|biz|world|info|club|mobi|press|top|site|tech|online|store|live|co|shop|fun|tamilmv)\b', '', name_for_parsing, flags=re.IGNORECASE)
    name_for_parsing = re.sub(r'@[a-zA-Z0-9_]+', '', name_for_parsing).strip()

    part_info = ""
    part_match = re.search(r'part[\s._-]?(\d+)', name_for_parsing, re.IGNORECASE)
    if part_match:
        part_info = f"Part {int(part_match.group(1)):02d}"

    # Reality shows ke Day tag ko detect karna
    day_info_str = ""
    day_match = re.search(r'\b(?:Day|D)\s*0*(\d{1,3})\b', name_for_parsing, re.IGNORECASE)
    if day_match:
        day_info_str = f"Day {int(day_match.group(1)):02d}"

    season_info_str = ""
    episode_info_str = ""
    raw_episode_text_to_remove = ""

    # Direct SXXEXXX check
    direct_se = re.search(r'\bS(\d{1,3})\s*E(\d{1,4})\b', name_for_parsing, re.IGNORECASE)
    if direct_se:
        season_info_str = f"S{int(direct_se.group(1)):02d}"
        episode_info_str = f"E{int(direct_se.group(2)):02d}"

    range_patterns = [
        (r'(\d{1,2})\s+(?:To|-|–|—)\s+(\d{1,2})', 'no_season'),
        (r'(\d{1,2})\s+(\d{1,2})(?=\s\d{4})', 'no_season'),
        (r'S(\d{1,3}).*?EP\((\d{1,4})-(\d{1,4})\)', 'season'),
        (r'S(\d{1,3}).*?\[E?(\d{1,4})\s*-\s*E?(\d{1,4})\]', 'season'),
        (r'S(\d{1,3}).*?\[(\d{1,4})\s*To\s*(\d{1,4})\s*Eps?\]', 'season'),
        (r'S(\d{1,3}).*?\[EP\s*(\d{1,4})\s*to\s*(\d{1,4})\]', 'season'),
        (r'S(\d{1,3}).*?\[Epi\s*(\d{1,4})\s*-\s*(\d{1,4})\]', 'season'),
        (r'S(\d{1,3}).*?Ep\.?(\d{1,4})-(\d{1,4})', 'season'),
        (r'S(\d{1,3})\s*E(\d{1,4})[-\s]*E(\d{1,4})', 'season'),
        (r'\.Ep\.\[(\d{1,4})-(\d{1,4})\]', 'no_season'),
        (r'Ep\s*(\d{1,4})\s*-\s*(\d{1,4})', 'no_season'),
        (r'(?:E|Episode)s?\.?\s?(\d{1,4})\s?(?:to|-|–|—)\s?(\d{1,4})', 'no_season'),
    ]

    for pattern, p_type in range_patterns:
        match = re.search(pattern, name_for_parsing, re.IGNORECASE)
        if match:
            groups = match.groups()
            raw_episode_text_to_remove = match.group(0)
            if p_type == 'season':
                if not season_info_str: season_info_str = f"S{int(groups[0]):02d}"
                start_ep, end_ep = groups[1], groups[2]
            else:
                start_ep, end_ep = groups[0], groups[1]

            if int(start_ep) < int(end_ep):
                episode_info_str = f"E{int(start_ep):02d}-E{int(end_ep):02d}"
                name_for_parsing = name_for_parsing.replace(raw_episode_text_to_remove, ' ', 1)
                break 

    name_for_ptn = re.sub(r'\[.*?\]', '', name_for_parsing).strip()
    parsed_info = PTN.parse(name_for_ptn)
    
    initial_title = parsed_info.get('title', '').strip()
    initial_title = re.sub(r'^(?:\d+\s*[-_.]?\s*)+(?=[A-Za-z])', '', initial_title)
    
    # Season extraction fallback
    if not season_info_str and parsed_info.get('season'):
        s_val = parsed_info.get('season')
        try:
            season_info_str = f"S{int(s_val):02d}"
        except Exception:
            season_info_str = f"S{s_val}"

    # Episode extraction fallback
    if not episode_info_str:
        ep_val = parsed_info.get('episode')
        if ep_val:
            if isinstance(ep_val, list):
                if len(ep_val) > 1: episode_info_str = f"E{int(min(ep_val)):02d}-E{int(max(ep_val)):02d}"
                elif ep_val: episode_info_str = f"E{int(ep_val[0]):02d}"
            else:
                try:
                    episode_info_str = f"E{int(ep_val):02d}"
                except Exception:
                    episode_info_str = f"E{ep_val}"
        else:
            ep_direct = re.search(r'\b(?:E|EP|Episode)\s*0*(\d{1,4})\b', name_for_parsing, re.IGNORECASE)
            if ep_direct:
                episode_info_str = f"E{int(ep_direct.group(1)):02d}"
    
    year_from_filename = parsed_info.get('year')
    if not year_from_filename:
        year_from_filename = extracted_year
    
    # --- 1. LANGUAGE DETECTION ---
    found_languages = set()
    cleaned_name_for_lang = clean_name_ascii.replace('.', ' ').replace('_', ' ').replace('-', ' ').lower()
    
    ptn_audio_tags = parsed_info.get('audio', '')
    if isinstance(ptn_audio_tags, list):
        ptn_audio_tags = " ".join(ptn_audio_tags)
    cleaned_name_for_lang += " " + ptn_audio_tags.lower()
    
    for key, value in LANGUAGE_MAP.items():
        if re.search(r'\b' + re.escape(key) + r'\b', cleaned_name_for_lang):
            found_languages.add(value)

    # --- 2. QUALITY & METADATA EXTRACTOR ---
    extracted_tags = []
    
    res_match = re.search(r'\b(480p|576p|720p|1080p|2160p|4k|uhd)\b', clean_name_ascii, re.IGNORECASE)
    if res_match:
        extracted_tags.append(res_match.group(1).lower())
    elif parsed_info.get('resolution'):
        extracted_tags.append(str(parsed_info.get('resolution')).lower())

    source_match = re.search(r'(WEB[\.\-_]?DL|WEB[\.\-_]?Rip|BluRay|BRRip|BDRip|HD[\.\-_]?Rip|DVDRip|HDTC|HDCAM|PreDVD)', clean_name_ascii, re.IGNORECASE)
    if source_match:
        s = source_match.group(1).upper()
        if "WEB" in s and "DL" in s:
            s = "WEB-DL"
        elif "WEB" in s and "RIP" in s:
            s = "WEBRip"
        elif "BLU" in s or "BR" in s or "BD" in s:
            s = "BluRay"
        extracted_tags.append(s)
    elif parsed_info.get('quality'):
        extracted_tags.append(str(parsed_info.get('quality')).upper())

    codec_match = re.search(r'(H[\.\s]?264|H[\.\s]?265|x264|x265|HEVC)', clean_name_ascii, re.IGNORECASE)
    if codec_match:
        c = codec_match.group(1).upper().replace(' ', '.')
        extracted_tags.append(c)

    audio_match = re.search(r'(DD[\+]?[\.\s]?5\.1|Atmos|AAC[\.\s]?2\.0|Dual[\.\s\-_]?Audio|Multi[\.\s\-_]?Audio)', clean_name_ascii, re.IGNORECASE)
    if audio_match:
        a = audio_match.group(1).title().replace(' ', '.')
        if "Dual" in a: a = "Dual-Audio"
        if "Multi" in a: a = "Multi-Audio"
        extracted_tags.append(a)

    quality_tags_str = " | ".join(extracted_tags) if extracted_tags else "HD"

    # --- 3. CLEAN TITLE HANDLING ---
    title_to_clean = initial_title
    
    # Title ke andar se raw 4-digit release year remove karna
    title_to_clean = re.sub(r'(?:\D|^)(19\d{2}|20\d{2})(?:\D|$)', ' ', title_to_clean).strip()
    
    if raw_episode_text_to_remove:
        title_to_clean = title_to_clean.replace(raw_episode_text_to_remove, '')
        
    title_to_clean = re.sub(r'\bS\d{1,3}\s*E\d{1,4}\b', '', title_to_clean, flags=re.IGNORECASE)
    title_to_clean = re.sub(r'\bS\d{1,3}\b|\bE\d{1,4}\b', '', title_to_clean, flags=re.IGNORECASE)
    
    day_match_inline = re.search(r'\b(?:Day|D)\s*\d{1,3}\b.*$', title_to_clean, flags=re.IGNORECASE)
    if day_match_inline:
        title_to_clean = title_to_clean[:day_match_inline.start()].strip()

    title_to_clean = re.sub(r'[\(\[\{].*?[\)\]\}]', ' ', title_to_clean)
    title_to_clean = re.sub(r'[\(\[\{\}\]\)\'\"`]', ' ', title_to_clean)
    
    junk_words = [
        'Ep', 'Eps', 'Episode', 'Episodes', 'Season', 'Series', 'South', 'Dubbed', 'Completed',
        'Web', r'\d+Kbps', 'UNCUT', 'ORG', 'HQ', 'ESubs', 'MSubs', 'REMASTERED', 'REPACK',
        'PROPER', 'iNTERNAL', 'Sample', 'Video', 'Dual', 'Audio', 'Multi', 'Hollywood',
        'New', 'Combined', 'Complete', 'Chapter', 'PSA', 'JC', 'DIDAR', 'StarBoy', 'Movies', 'Mp4',
        'Hindi', 'English', 'Tamil', 'Telugu', 'Kannada', 'Malayalam', 'Punjabi', 'Japanese', 'Korean', 'Marathi',
        'NF', 'AMZN', 'MAX', 'DSNP', 'ZEE5', 'SONY', 'WEB-DL', 'HDRip', 'WEBRip', 'HEVC', 'x265', 'x264', 'AAC',
        '1tamilmv', 'www', 'Join Us', 'Day', 'BBHin', 'JioCinema', 'Hotstar', 'SonyLiv', 'Voot'
    ]
    junk_pattern_re = r'\b(' + r'|'.join(junk_words) + r')\b'
    cleaned_title = re.sub(junk_pattern_re, ' ', title_to_clean, flags=re.IGNORECASE)
    cleaned_title = re.sub(r'[-_.]', ' ', cleaned_title)

    if re.search(r'bigg\s*boss', cleaned_title, re.IGNORECASE):
        cleaned_title = re.sub(r'\b(bigg\s*boss)\b.*$', r'\1', cleaned_title, flags=re.IGNORECASE).strip()
    
    cleaned_title = re.sub(r'[\+\-&|/]+', ' ', cleaned_title)
    cleaned_title = re.sub(r'^[^\w]+|[^\w]+$', '', cleaned_title).strip()
    cleaned_title = re.sub(r'\s+', ' ', cleaned_title).strip()
    
    if not cleaned_title: 
        cleaned_title = " ".join(clean_name_ascii.split('.')[:-1])

    definitive_title, definitive_year = await get_definitive_title_from_imdb(cleaned_title)

    final_title = definitive_title if definitive_title else cleaned_title.title()
    # Title ke end se raw year string saaf karna
    final_title = re.sub(r'(?:\D|^)(19\d{2}|20\d{2})(?:\D|$)', ' ', final_title).strip()
    final_title = re.sub(r'^[^\w]+|[^\w]+$', '', final_title).strip()
    final_title = re.sub(r'\s+', ' ', final_title).strip()

    final_year = definitive_year or year_from_filename or extracted_year
    is_series = bool(season_info_str) or bool(episode_info_str) or bool(day_info_str)
    
    display_title_main = final_title.strip()
    if season_info_str and season_info_str not in display_title_main:
        display_title_main += f" {season_info_str}"
    
    # Strictly single bracket format for release year
    display_title_with_year = f"{display_title_main} ({final_year})" if final_year else display_title_main
        
    return {
        "batch_title": f"{final_title} {season_info_str}".strip(),
        "display_title": display_title_with_year,
        "clean_search_title": final_title.strip(),
        "year": final_year,
        "is_series": is_series,
        "season_info": season_info_str, 
        "episode_info": episode_info_str,
        "day_info": day_info_str,
        "part_info": part_info,
        "languages": sorted(list(found_languages)),
        "quality_tags": quality_tags_str
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
