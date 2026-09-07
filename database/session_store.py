import os
import base64
import logging
from config import Config
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)
SESSION_FILE = "FinalStorageBot.session"

class SessionStorage:
    def __init__(self):
        self.client = AsyncIOMotorClient(Config.DATABASE_URI)
        self.db = self.client[Config.DATABASE_NAME]
        self.col = self.db["telegram_session_cache"]

    async def restore_session(self):
        """Startup par MongoDB se .session file disk par likhega"""
        try:
            doc = await self.col.find_one({"_id": "pyrogram_session"})
            if doc and "data" in doc:
                raw_bytes = base64.b64decode(doc["data"])
                with open(SESSION_FILE, "wb") as f:
                    f.write(raw_bytes)
                logger.info("✅ Restored Pyrogram session from MongoDB.")
                return True
            logger.warning("⚠️ No session found in MongoDB yet. Fresh session will be created.")
            return False
        except Exception as e:
            logger.error(f"Failed to restore session from MongoDB: {e}")
            return False

    async def save_session(self):
        """Disk ki .session file ko MongoDB me encode karke save karega"""
        try:
            if not os.path.exists(SESSION_FILE):
                return
            with open(SESSION_FILE, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
            
            await self.col.update_one(
                {"_id": "pyrogram_session"},
                {"$set": {"data": encoded}},
                upsert=True
            )
            logger.info("💾 Session successfully saved to MongoDB.")
        except Exception as e:
            logger.error(f"Failed to save session to MongoDB: {e}")
          
