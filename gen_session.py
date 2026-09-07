import asyncio
from pyrogram import Client
from config import Config

async def main():
    print("Generating session string, please wait...")
    async with Client(
        name=":memory:",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN
    ) as app:
        session = await app.export_session_string()
        print("\n" + "=" * 50)
        print("SESSION_STRING (Copy this):")
        print("=" * 50)
        print(session)
        print("=" * 50 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
  
