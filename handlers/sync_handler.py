import logging
from pyrogram import Client, filters
from database.session_store import SessionStorage
from config import Config

logger = logging.getLogger(__name__)
session_store = SessionStorage()

@Client.on_message(filters.command("sync") & filters.private)
async def manual_sync(client, message):
    status_msg = await message.reply_text("⏳ **Syncing private channels...**")
    
    success_log = []
    
    # Target channels
    channels = [
        ("Owner DB", getattr(Config, "OWNER_DB_CHANNEL", None)),
        ("Log Channel", getattr(Config, "LOG_CHANNEL", None))
    ]
    
    for name, ch_id in channels:
        if not ch_id:
            continue
        try:
            cid = int(ch_id)
            # Channel ko direct ping karein
            sent = await client.send_message(cid, f"🔄 **Sync Ping for {name}**")
            success_log.append(f"✅ `{name}` ({cid}): Connected!")
        except Exception as e:
            success_log.append(f"❌ `{name}` ({ch_id}): Error ({e})")
            
    # Session MongoDB me save karein
    await session_store.save_session()
    client.is_healthy.set()
    
    final_text = "**Sync Report:**\n\n" + "\n".join(success_log)
    final_text += "\n\n💾 **Session cache saved to MongoDB permanently!**"
    await status_msg.edit_text(final_text)


@Client.on_message(filters.private & filters.forwarded, group=-1)
async def forward_sync(client, message):
    """Channel se forward aate hi intercept karega"""
    forward_chat = message.forward_from_chat
    if not forward_chat:
        return

    chat_id = forward_chat.id
    chat_title = forward_chat.title or "Private Channel"
    
    status_msg = await message.reply_text(f"⏳ **Capturing Peer for:** `{chat_title}` (`{chat_id}`)...")
    
    try:
        # Access hash ko session me register karein
        await client.get_chat(chat_id)
        await client.send_message(chat_id, "✅ **Channel successfully linked via forward!**")
        
        # MongoDB me turant push karein
        await session_store.save_session()
        client.is_healthy.set()
        
        await status_msg.edit_text(
            f"✅ **Success!**\n\n"
            f"• **Channel:** `{chat_title}`\n"
            f"• **ID:** `{chat_id}`\n\n"
            f"💾 **Access Hash saved to MongoDB!**"
        )
        # Message processing yahin stop kar dein
        message.stop_propagation()
    except Exception as e:
        await status_msg.edit_text(f"❌ **Failed:** `{e}`")
        message.stop_propagation()
  
