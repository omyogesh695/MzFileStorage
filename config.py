import os 

class Config:
    # Your API details from my.telegram.org
    API_ID = int(os.environ.get("API_ID", ""))
    API_HASH = os.environ.get("API_HASH", "")

    # Your Bot Token
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

    # Your Admin User ID
    ADMIN_ID = int(os.environ.get("ADMIN_ID", ""))
    
    # Your Owner DB Channel ID
    OWNER_DB_CHANNEL = int(os.environ.get("OWNER_DB_CHANNEL", "-1003433884727"))
    LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "-1004424440786"))  # Aapka Master Admin Log Channel

    # Your MongoDB Connection String
    MONGO_URI = os.environ.get("MONGO_URI", "")
    DATABASE_NAME = os.environ.get("DATABASE_NAME", "File_Storage")
    
    # --- TMDB API Key (Optional, for posters) ---
    TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
    
    # --- The full public URL of your application (Koyeb) ---
    APP_URL = os.environ.get("APP_URL", "https://few-agnese-mztech-651f3c23.koyeb.app")
    
    # The name of the file that stores your bot's username (for the redirector)
    BOT_USERNAME_FILE = "bot_username.txt"
    
    # Tutorial Link
    TUTORIAL_URL = os.environ.get("TUTORIAL_URL", "https://t.me/mzbotzupdate")

    # ================================================================= #
    # 🔒 ANTI-BYPASS HMAC SECURITY CONFIGURATION #
    # ================================================================= #
    SECRET_KEY = os.environ.get("SECRET_KEY", "mz_super_secret_anti_bypass_key_2026")
    LINK_EXPIRY = int(os.environ.get("LINK_EXPIRY", "900"))  # 15 minutes
