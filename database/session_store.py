# database/session_store.py
import os
import base64
import logging
from config import Config
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)
SESSION_FILE = "FinalStorageBot.session"

class SessionStorage:
    def __init__(self):
        # Database URL dhundhne ke liye fallback sequence
        mongo_uri = (
            getattr(Config, "DATABASE_URI", None)
            or getattr(Config, "DATABASE_URL", None)
            or getattr(Config, "MONGO_URI", None)
            or getattr(Config, "MONGO_DB_URI", None)
            or os.environ.get("DATABASE_URI")
            or os.environ.get("DATABASE_URL")
            or os.environ.get("MONGO_URI")
        )

        db_name = (
            getattr(Config, "DATABASE_NAME", None)
            or os.environ.get("DATABASE_NAME", "Cluster0")
        )

        if not mongo_uri:
            raise ValueError("MongoDB URI nahi mili! Config ya Koyeb env vars me DATABASE_URI/DATABASE_URL check karein.")

        self.client = AsyncIOMotorClient(mongo_uri)
        self.db = self.client[db_name]
        self.col = self.db["telegram_session_cache"]

    async def restore_session(self):
        """Startup par MongoDB se .session file disk par restore karta hai"""
        try:
            doc = await self.col.find_one({"_id": "pyrogram_session"})
            if doc and "data" in doc:
                raw_bytes = base64.b64decode(doc["data"])
                with open(SESSION_FILE, "wb") as f:
                    f.write(raw_bytes)
                logger.info("✅ Restored Pyrogram session database from MongoDB.")
                return True
            logger.warning("⚠️ No session file found in MongoDB yet. A fresh session will be created.")
            return False
        except Exception as e:
            logger.error(f"Failed to restore session from MongoDB: {e}")
            return False

    async def save_session(self):
        """Disk ki .session file ko MongoDB me binary format me encode karke save karta hai"""
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
            logger.info("💾 Successfully saved Pyrogram session database to MongoDB.")
        except Exception as e:
            logger.error(f"Failed to save session to MongoDB: {e}")
