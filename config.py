import os 

class Config:
    # Your API details from my.telegram.org
    API_ID = int(os.environ.get("API_ID", "13441344"))
    API_HASH = os.environ.get("API_HASH", "2f10533d9068507d0c10bf1074527167")

    # Your Bot Token
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

    # Your Admin User ID
    ADMIN_ID = int(os.environ.get("ADMIN_ID", ""))
    
    # Your Owner DB Channel ID
    OWNER_DB_CHANNEL = int(os.environ.get("OWNER_DB_CHANNEL", "-1003433884727"))

    # Your MongoDB Connection String
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://yogedrasama:D8oNvWFxBws2et6W@cluster0.5m2w6n8.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
    DATABASE_NAME = os.environ.get("DATABASE_NAME", "FileStorage")
    
    # --- TMDB API Key (Optional, for posters) ---
    TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "5a318417c7f4a722afd9d71df548877b") #add your own
    
    # --- DECREED MODIFICATION: Replaced VPS_IP and VPS_PORT ---
    # The full public URL of your application (e.g., https://my-bot.koyeb.app or https://my-bot.herokuapp.com)
    # DO NOT add a trailing slash / at the end!
    APP_URL = os.environ.get("APP_URL", "")
    
    # The name of the file that stores your bot's username (for the redirector)
    BOT_USERNAME_FILE = "bot_username.txt" #do not change this
    
    # ================================================================= #
    # VVVVVV YAHAN PAR NAYA TUTORIAL LINK ADD KIYA GAYA HAI VVVVVV #
    # ================================================================= #
    # Yahan apna tutorial video ya channel ka link daalein
    TUTORIAL_URL = os.environ.get("TUTORIAL_URL", "https://t.me/mzbotz")
