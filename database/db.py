# database/db.py

import datetime
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

client = AsyncIOMotorClient(Config.MONGO_URI)
db = client[Config.DATABASE_NAME]
logger = logging.getLogger(__name__)

users = db['users']
files = db['files']
posts = db['posts']
bot_settings = db['bot_settings']
verified_users = db['verified_users']
# --- Collections for Daily Stats ---
daily_stats = db['daily_stats']
monthly_records = db['monthly_records']


async def add_user(user_id):
    """Adds a new user to the database if they don't already exist."""
    user_data = {
        'user_id': user_id,
        'post_channels': [],
        'index_db_channel': None,
        
        # Legacy fallback
        'shortener_url': None,
        'shortener_api': None,
        
        # 3 Shortener Configuration
        'shortener_url_1': None,
        'shortener_api_1': None,
        'shortener_url_2': None,
        'shortener_api_2': None,
        'shortener_url_3': None,
        'shortener_api_3': None,
        
        # Verification Gap (Default in Minutes, e.g., 720 mins = 12 hours)
        'verify_gap': 720,
        
        'fsub_channel': None,
        'filename_url': None,
        'footer_buttons': [],
        'show_poster': True,
        'shortener_enabled': True,
        'how_to_download_link': None,
        'shortener_mode': 'each_time',
        'daily_notify_enabled': False,
        'backup_channels': []
    }
    await users.update_one({'user_id': user_id}, {"$setOnInsert": user_data}, upsert=True)

# --- Functions for Daily Stats Feature ---

async def record_daily_view(owner_id: int, requester_id: int):
    """Records a unique view for an owner for the current day."""
    today_utc = datetime.datetime.utcnow().date()
    today_start = datetime.datetime(today_utc.year, today_utc.month, today_utc.day)

    result = await daily_stats.update_one(
        {'owner_id': owner_id, 'date': today_start, 'unique_viewers': {'$ne': requester_id}},
        {
            '$inc': {'view_count': 1},
            '$addToSet': {'unique_viewers': requester_id}
        }
    )
    
    if result.matched_count == 0:
        await daily_stats.update_one(
            {'owner_id': owner_id, 'date': today_start},
            {
                '$setOnInsert': {'owner_id': owner_id, 'date': today_start, 'view_count': 0, 'unique_viewers': []}
            },
            upsert=True
        )
        await daily_stats.update_one(
            {'owner_id': owner_id, 'date': today_start, 'unique_viewers': {'$ne': requester_id}},
            {
                '$inc': {'view_count': 1},
                '$addToSet': {'unique_viewers': requester_id}
            }
        )

async def get_stats_for_owner(owner_id: int, days: int = 6):
    """Fetches view count for the specified number of past days."""
    end_date = datetime.datetime.utcnow().replace(hour=23, minute=59, second=59)
    start_date = end_date - datetime.timedelta(days=days - 1)
    start_date = start_date.replace(hour=0, minute=0, second=0)

    cursor = daily_stats.find(
        {'owner_id': owner_id, 'date': {'$gte': start_date, '$lte': end_date}},
        {'date': 1, 'view_count': 1, '_id': 0}
    ).sort('date', -1)
    
    return await cursor.to_list(length=days)

async def get_users_with_daily_notify_enabled():
    """Gets all user IDs who have enabled daily stats notifications."""
    cursor = users.find({'daily_notify_enabled': True}, {'user_id': 1})
    return [doc['user_id'] for doc in await cursor.to_list(length=None)]

async def get_monthly_record(owner_id: int):
    """Gets the highest view count for an owner in the last 30 days."""
    return await monthly_records.find_one({'owner_id': owner_id})

async def update_monthly_record(owner_id: int, new_count: int, record_date: datetime.datetime):
    """Updates the monthly high score for an owner."""
    await monthly_records.update_one(
        {'owner_id': owner_id},
        {'$set': {'highest_view_count': new_count, 'date_of_record': record_date}},
        upsert=True
    )

# --- Verification & Shortener Step Management ---

async def get_user_verify_step(owner_id: int, requester_id: int) -> int:
    """Gets current verification step of the user (Defaults to 1)."""
    data = await verified_users.find_one({'owner_id': owner_id, 'requester_id': requester_id})
    if not data:
        return 1
    return data.get('current_step', 1)

async def set_user_verify_step(owner_id: int, requester_id: int, step: int):
    """Updates the verification step for user."""
    await verified_users.update_one(
        {'owner_id': owner_id, 'requester_id': requester_id},
        {'$set': {'current_step': step}},
        upsert=True
    )

async def add_verified_user(owner_id: int, requester_id: int):
    """
    Marks the user as verified with current timestamp.
    """
    try:
        await verified_users.update_one(
            {
                "owner_id": owner_id,
                "requester_id": requester_id
            },
            {
                "$set": {
                    "verified_at": datetime.datetime.utcnow(),
                    "current_step": 1
                }
            },
            upsert=True
        )
        logger.info(f"User {requester_id} verified for owner {owner_id}")
    except Exception as e:
        logger.error(f"Error adding verified user: {e}")

async def claim_step_verification(owner_id: int, file_unique_id: str, requester_id: int, current_step: int, total_steps: int) -> bool:
    """
    User ko current step ke turant baad verified mark karta hai
    aur agle expiry cycle ke liye next step ready rakhta hai.
    """
    file_exists = await files.find_one({
        'owner_id': owner_id,
        'file_unique_id': file_unique_id
    })

    if not file_exists:
        return False

    next_step = current_step + 1 if current_step < total_steps else 1

    await verified_users.update_one(
        {
            "owner_id": owner_id,
            "requester_id": requester_id
        },
        {
            "$set": {
                "verified_at": datetime.datetime.utcnow(),
                "current_step": next_step
            }
        },
        upsert=True
    )
    await record_daily_view(owner_id, requester_id)
    return True

async def is_user_verified(owner_id: int, requester_id: int) -> bool:
    """
    Checks if user is verified within the owner's configured verify_gap (in minutes).
    Dynamically fetched from owner settings.
    """
    try:
        verification = await verified_users.find_one(
            {
                "owner_id": owner_id,
                "requester_id": requester_id
            }
        )

        if (
            not verification or
            "verified_at" not in verification or
            not isinstance(verification["verified_at"], datetime.datetime)
        ):
            return False

        # Owner ki settings se dynamic verify_gap (minutes) nikalna
        owner_data = await get_user(owner_id)
        # Default 720 minutes (12 hours) agar set na ho
        gap_minutes = owner_data.get('verify_gap', 720) if owner_data else 720

        # Minutes ke hisaab se expiry check
        expiry_threshold = datetime.datetime.utcnow() - datetime.timedelta(minutes=int(gap_minutes))

        return verification["verified_at"] > expiry_threshold

    except Exception as e:
        logger.error(f"An error occurred in is_user_verified check: {e}")
        return False

async def claim_verification_for_file(owner_id: int, file_unique_id: str, requester_id: int) -> bool:
    """Verifies user when completing the final step (Fallback compatibility)."""
    file_exists = await files.find_one({
        'owner_id': owner_id,
        'file_unique_id': file_unique_id
    })

    if not file_exists:
        return False

    await add_verified_user(owner_id, requester_id)
    await record_daily_view(owner_id, requester_id)
    return True

# --- Post and Backup Channel Functions ---

async def set_post_channel(user_id: int, channel_id: int):
    await users.update_one({'user_id': user_id}, {'$addToSet': {'post_channels': channel_id}})

async def get_post_channels(user_id: int):
    user = await users.find_one({'user_id': user_id})
    return user.get('post_channels', []) if user else []

async def get_post_channel(user_id: int):
    user = await users.find_one({'user_id': user_id})
    return user.get('post_channels')[0] if user and user.get('post_channels') else None

async def set_index_db_channel(user_id: int, channel_id: int):
    await users.update_one({'user_id': user_id}, {'$set': {'index_db_channel': channel_id}}, upsert=True)

async def get_index_db_channel(user_id: int):
    user = await users.find_one({'user_id': user_id})
    return user.get('index_db_channel') if user else None

async def add_backup_channel(user_id: int, channel_id: int):
    await users.update_one({'user_id': user_id}, {'$addToSet': {'backup_channels': channel_id}})

async def remove_backup_channel(user_id: int, channel_id: int):
    await users.update_one({'user_id': user_id}, {'$pull': {'backup_channels': channel_id}})

async def get_backup_channels(user_id: int):
    user = await users.find_one({'user_id': user_id})
    return user.get('backup_channels', []) if user else []

async def save_file_data(owner_id, original_message, copied_message, stream_message):
    from utils.helpers import get_file_raw_link
    original_media = getattr(original_message, original_message.media.value)
    raw_link = await get_file_raw_link(copied_message)
    file_data = {
        'owner_id': owner_id,
        'file_unique_id': original_media.file_unique_id,
        'file_id': copied_message.id,
        'stream_id': stream_message.id,
        'file_name': original_media.file_name,
        'file_size': original_media.file_size,
        'raw_link': raw_link
    }
    await files.update_one(
        {'owner_id': owner_id, 'file_unique_id': original_media.file_unique_id},
        {'$set': file_data}, upsert=True
    )

async def get_user(user_id):
    return await users.find_one({'user_id': user_id})

async def get_all_user_ids(storage_owners_only=False):
    query = {}
    if storage_owners_only:
        query = {"$or": [{"post_channels": {"$exists": True, "$ne": []}}, {"index_db_channel": {"$exists": True, "$ne": None}}]}
    cursor = users.find(query, {'user_id': 1})
    return [doc['user_id'] for doc in await cursor.to_list(length=None) if 'user_id' in doc]

async def get_storage_owner_ids():
    query = {"$or": [{"post_channels": {"$exists": True, "$ne": []}}, {"index_db_channel": {"$exists": True, "$ne": None}}]}
    cursor = users.find(query, {'user_id': 1})
    return [doc['user_id'] for doc in await cursor.to_list(length=None) if 'user_id' in doc]

async def get_normal_user_ids():
    all_users_cursor = users.find({}, {'user_id': 1})
    storage_owners_cursor = users.find({"$or": [{"post_channels": {"$exists": True, "$ne": []}}, {"index_db_channel": {"$exists": True, "$ne": None}}]}, {'user_id': 1})
    all_user_ids = {doc['user_id'] for doc in await all_users_cursor.to_list(length=None) if 'user_id' in doc}
    storage_owner_ids = {doc['user_id'] for doc in await storage_owners_cursor.to_list(length=None) if 'user_id' in doc}
    return list(all_user_ids - storage_owner_ids)

async def get_storage_owners_count():
    query = {"$or": [{"post_channels": {"$exists": True, "$ne": []}}, {"index_db_channel": {"$exists": True, "$ne": None}}]}
    return await users.count_documents(query)

async def update_user(user_id, key, value):
    await users.update_one({'user_id': user_id}, {'$set': {key: value}}, upsert=True)

async def add_to_list(user_id, list_name, item):
    await users.update_one({'user_id': user_id}, {'$addToSet': {list_name: item}})

async def remove_from_list(user_id, list_name, item):
    await users.update_one({'user_id': user_id}, {'$pull': {list_name: item}})

async def find_owner_by_index_channel(channel_id):
    user = await users.find_one({'index_db_channel': channel_id})
    return user['user_id'] if user else None

async def get_file_by_unique_id(owner_id: int, file_unique_id: str):
    return await files.find_one({'owner_id': owner_id, 'file_unique_id': file_unique_id})

async def get_user_file_count(owner_id):
    return await files.count_documents({'owner_id': owner_id})

async def get_all_user_files(user_id):
    return files.find({'owner_id': user_id})

async def get_paginated_files(user_id, page: int, page_size: int = 5):
    skip = (page - 1) * page_size
    cursor = files.find({'owner_id': user_id}).sort('_id', -1).skip(skip).limit(page_size)
    return await cursor.to_list(length=page_size)

async def search_user_files(user_id, query: str, page: int, page_size: int = 5):
    search_filter = {'owner_id': user_id, 'file_name': {'$regex': query, '$options': 'i'}}
    skip = (page - 1) * page_size
    total_files = await files.count_documents(search_filter)
    cursor = files.find(search_filter).sort('_id', -1).skip(skip).limit(page_size)
    files_list = await cursor.to_list(length=page_size)
    return files_list, total_files

async def total_users_count():
    return await users.count_documents({})

async def add_footer_button(user_id, button_name, button_url):
    button = {'name': button_name, 'url': button_url}
    await users.update_one({'user_id': user_id}, {'$push': {'footer_buttons': button}})

async def remove_footer_button(user_id, button_name):
    await users.update_one({'user_id': user_id}, {'$pull': {'footer_buttons': {'name': button_name}}})

async def remove_all_footer_buttons(user_id):
    await users.update_one({'user_id': user_id}, {'$set': {'footer_buttons': []}})

async def delete_all_files():
    result = await files.delete_many({})
    return result.deleted_count

def _serialize_inline_keyboard(keyboard):
    if not isinstance(keyboard, InlineKeyboardMarkup):
        return None
    
    serializable_keyboard = []
    for row in keyboard.inline_keyboard:
        new_row = []
        for button in row:
            button_dict = {
                "text": button.text,
                "url": button.url,
                "callback_data": button.callback_data,
            }
            new_row.append({k: v for k, v in button_dict.items() if v is not None})
        serializable_keyboard.append(new_row)
    return {"inline_keyboard": serializable_keyboard}

async def save_post(owner_id, post_channel_id, message_id, poster, caption, reply_markup):
    serializable_reply_markup = _serialize_inline_keyboard(reply_markup)
    post_data = {
        'owner_id': owner_id,
        'post_channel_id': post_channel_id,
        'message_id': message_id,
        'poster': poster,
        'caption': caption,
        'reply_markup': serializable_reply_markup,
        'saved_at': datetime.datetime.utcnow()
    }
    await posts.update_one(
        {'owner_id': owner_id, 'message_id': message_id},
        {'$set': post_data},
        upsert=True
    )

async def get_posts_for_backup(owner_id, post_channel_id):
    cursor = posts.find({'owner_id': owner_id, 'post_channel_id': post_channel_id}).sort('message_id', 1)
    return await cursor.to_list(length=None)

async def delete_posts_from_channel(owner_id, post_channel_id):
    result = await posts.delete_many({'owner_id': owner_id, 'post_channel_id': post_channel_id})
    return result.deleted_count

async def set_verify_log_channel(user_id: int, channel_id: int):
    """Saves the verify log channel ID for the storage owner."""
    await users.update_one({'user_id': user_id}, {'$set': {'verify_log_channel': channel_id}}, upsert=True)

async def get_verify_log_channel(user_id: int):
    """Retrieves the verify log channel ID for a storage owner."""
    user = await users.find_one({'user_id': user_id})
    return user.get('verify_log_channel') if user else None
