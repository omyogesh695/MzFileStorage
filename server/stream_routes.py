# server/stream_routes.py

import os
import base64
import logging
from aiohttp import web
from aiohttp.client_exceptions import ClientConnectionResetError
from util.render_template import render_player_page
from util.custom_dl import ByteStreamer
from util.file_properties import get_media_from_message # Import helper
from features.shortener import get_shortlink
from config import Config
from pyrogram.errors import RPCError

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response({
        "server_status": "running",
        "bot_status": "connected"
    })

@routes.get("/favicon.ico", allow_head=True)
async def favicon_handler(request):
    return web.Response(status=204)


@routes.get("/watch/{message_id}", allow_head=True)
async def watch_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        bot = request.app['bot']
        content = await render_player_page(bot, message_id)
        return web.Response(text=content, content_type="text/html")
    except Exception as e:
        logger.error(f"Error in watch_handler: {e}", exc_info=True)
        return web.Response(text="<h1>500 - Internal Server Error</h1><p>Could not render the page.</p>", content_type="text/html", status=500)

# --- LEGENDARY MODIFICATION: Refactored to use Message object ---
@routes.get(r"/stream/{message_id:\d+}")
async def stream_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        bot = request.app['bot']
        streamer = ByteStreamer(bot)
        
        # 1. Fetch the full message object
        message = await streamer.get_file_properties(message_id)
        media = get_media_from_message(message)
        
        file_size = media.file_size
        file_name = media.file_name

        res = web.StreamResponse(
            headers={
                "Content-Type": media.mime_type,
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes 0-{file_size-1}/{file_size}",
                "Content-Disposition": f'inline; filename="{file_name}"'
            }
        )
        await res.prepare(request)

        # 2. Pass the message object directly to stream_media
        async for chunk in bot.stream_media(message, limit=1024*1024):
            # --- LEGENDARY FIX v2.0: The Unbreakable Shield ---
            # This now catches ALL known disconnection errors for 100% stability.
            try:
                await res.write(chunk)
            except (ClientConnectionResetError, ConnectionResetError, BrokenPipeError, ConnectionError):
                logger.warning(f"Client disconnected for stream of message_id {message_id}.")
                # Stop sending data and exit cleanly
                break
        
        return res

    except RPCError as e:
        logger.error(f"Telegram RPCError in stream_handler: {e}", exc_info=True)
        return web.Response(status=404, text="File not accessible on Telegram.")
    except Exception as e:
        # This will no longer catch the handled connection errors
        logger.error(f"Error in stream_handler: {e}", exc_info=True)
        return web.Response(status=500, text="Internal server error.")

@routes.get(r"/download/{message_id:\d+}")
async def download_handler(request):
    try:
        message_id = int(request.match_info['message_id'])
        bot = request.app['bot']
        streamer = ByteStreamer(bot)
        
        # 1. Fetch the full message object
        message = await streamer.get_file_properties(message_id)
        media = get_media_from_message(message)

        res = web.StreamResponse(
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(media.file_size),
                "Content-Disposition": f'attachment; filename="{media.file_name}"'
            }
        )
        await res.prepare(request)
        
        # 2. Pass the message object directly to stream_media
        async for chunk in bot.stream_media(message, limit=1024*1024):
            # --- LEGENDARY FIX v2.0: The Unbreakable Shield ---
            # This now catches ALL known disconnection errors for 100% stability.
            try:
                await res.write(chunk)
            except (ClientConnectionResetError, ConnectionResetError, BrokenPipeError, ConnectionError):
                logger.warning(f"Client disconnected for download of message_id {message_id}.")
                # Stop sending data and exit cleanly
                break

        return res
        
    except RPCError as e:
        logger.error(f"Telegram RPCError in download_handler: {e}", exc_info=True)
        return web.Response(status=404, text="File not accessible on Telegram.")
    except Exception as e:
        # This will no longer catch the handled connection errors
        logger.error(f"Error in download_handler: {e}", exc_info=True)
        return web.Response(status=500, text="Internal server error.")


# =====================================================================
# KOYEB PROTECTION / REDIRECTION ROUTE (Shortener Redirect)
# =====================================================================
@routes.get(r"/{payload:[a-zA-Z0-9_\-]+}")
async def redirect_to_shortener_handler(request):
    payload = request.match_info.get("payload")
    try:
        # Base64 decode string
        padding = "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode((payload + padding).encode("ascii")).decode("ascii")
        
        # Format check: get_{owner_id}_{file_unique_id}
        parts = decoded.split("_")
        if len(parts) < 3 or parts[0] != "get":
            return web.Response(text="Invalid payload link format.", status=400)
            
        owner_id = int(parts[1])
        file_unique_id = parts[2]
        
        # Bot username get karein (bot instance ya config file se)
        bot = request.app.get('bot')
        bot_username = bot.me.username if bot and hasattr(bot, 'me') and bot.me else None
        
        if not bot_username and os.path.exists(Config.BOT_USERNAME_FILE):
            with open(Config.BOT_USERNAME_FILE, "r") as f:
                bot_username = f.read().strip()

        # Destination Deep Link
        telegram_deep_link = f"https://t.me/{bot_username}?start=get_{owner_id}_{file_unique_id}"
        
        # Shortener API call
        final_short_url = await get_shortlink(telegram_deep_link, owner_id)
        
        # Shortener link par redirect
        return web.HTTPFound(final_short_url)

    except Exception as e:
        logger.error(f"Error in Koyeb redirect handler: {e}", exc_info=True)
        return web.Response(text="Invalid or expired protection link.", status=400)
  
