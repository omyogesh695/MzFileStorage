# server/stream_routes.py

import os
import base64
import logging
from aiohttp import web
from aiohttp.client_exceptions import ClientConnectionResetError
from util.render_template import render_player_page
from util.custom_dl import ByteStreamer
from util.file_properties import get_media_from_message
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
            try:
                await res.write(chunk)
            except (ClientConnectionResetError, ConnectionResetError, BrokenPipeError, ConnectionError):
                logger.warning(f"Client disconnected for stream of message_id {message_id}.")
                break
        
        return res

    except RPCError as e:
        logger.error(f"Telegram RPCError in stream_handler: {e}", exc_info=True)
        return web.Response(status=404, text="File not accessible on Telegram.")
    except Exception as e:
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
            try:
                await res.write(chunk)
            except (ClientConnectionResetError, ConnectionResetError, BrokenPipeError, ConnectionError):
                logger.warning(f"Client disconnected for download of message_id {message_id}.")
                break

        return res
        
    except RPCError as e:
        logger.error(f"Telegram RPCError in download_handler: {e}", exc_info=True)
        return web.Response(status=404, text="File not accessible on Telegram.")
    except Exception as e:
        logger.error(f"Error in download_handler: {e}", exc_info=True)
        return web.Response(status=500, text="Internal server error.")


# =====================================================================
# KOYEB PROTECTION / 5-SECOND COUNTDOWN REDIRECTION ROUTE
# =====================================================================
@routes.get(r"/{payload:[a-zA-Z0-9_\-]+}")
async def redirect_to_shortener_handler(request):
    payload = request.match_info.get("payload")
    try:
        # Base64 decode string
        padding = "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode((payload + padding).encode("ascii")).decode("ascii")
        
        # Format check: get_{owner_id}_{file_unique_id} YA verify_{owner_id}_{file_unique_id}
        parts = decoded.split("_")
        if len(parts) < 3 or parts[0] not in ["get", "verify"]:
            return web.Response(text="Invalid payload link format.", status=400)
            
        action_type = parts[0]
        owner_id = int(parts[1])
        file_unique_id = parts[2]
        
        # Bot username get karein
        bot = request.app.get('bot')
        bot_username = bot.me.username if bot and hasattr(bot, 'me') and bot.me else None
        
        if not bot_username and os.path.exists(Config.BOT_USERNAME_FILE):
            with open(Config.BOT_USERNAME_FILE, "r") as f:
                bot_username = f.read().strip()

        # Destination Deep Link
        telegram_deep_link = f"https://t.me/{bot_username}?start={action_type}_{owner_id}_{file_unique_id}"
        
        # Shortener API call
        final_short_url = await get_shortlink(telegram_deep_link, owner_id)
        
        # Modern 5-Second Timer Landing Page
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Securing Your Link...</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            background: radial-gradient(circle at center, #1e293b, #0f172a);
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 20px;
        }}
        .card {{
            background: rgba(30, 41, 59, 0.7);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            padding: 35px 25px;
            border-radius: 20px;
            box-shadow: 0 15px 35px rgba(0,0,0,0.5), 0 0 15px rgba(56, 189, 248, 0.1);
            text-align: center;
            max-width: 400px;
            width: 100%;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .icon {{
            font-size: 40px;
            margin-bottom: 12px;
        }}
        h2 {{
            color: #38bdf8;
            font-size: 22px;
            font-weight: 700;
            margin-bottom: 8px;
            letter-spacing: -0.5px;
        }}
        p {{
            color: #94a3b8;
            font-size: 14px;
            line-height: 1.5;
            margin-bottom: 25px;
        }}
        .timer-container {{
            position: relative;
            width: 80px;
            height: 80px;
            margin: 0 auto 25px;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .timer-circle {{
            font-size: 32px;
            font-weight: 800;
            color: #38bdf8;
            width: 100%;
            height: 100%;
            border-radius: 50%;
            border: 3px solid rgba(56, 189, 248, 0.2);
            border-top: 3px solid #38bdf8;
            display: flex;
            align-items: center;
            justify-content: center;
            animation: spin 1s linear infinite;
        }}
        .timer-number {{
            position: absolute;
            font-size: 28px;
            font-weight: 800;
            color: #ffffff;
        }}
        .btn {{
            display: block;
            width: 100%;
            background: linear-gradient(135deg, #0284c7, #2563eb);
            color: #ffffff;
            padding: 14px 20px;
            border-radius: 12px;
            text-decoration: none;
            font-weight: 600;
            font-size: 15px;
            box-shadow: 0 4px 15px rgba(37, 99, 235, 0.3);
            transition: all 0.2s ease;
        }}
        .btn:hover {{
            background: linear-gradient(135deg, #0369a1, #1d4ed8);
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(37, 99, 235, 0.4);
        }}
        @keyframes spin {{
            0% {{ transform: rotate(0deg); }}
            100% {{ transform: rotate(360deg); }}
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">🛡️</div>
        <h2>Security Verification</h2>
        <p>Your secure link is being generated. You will be redirected in a moment...</p>
        
        <div class="timer-container">
            <div class="timer-circle"></div>
            <div class="timer-number" id="countdown">5</div>
        </div>

        <a href="{final_short_url}" class="btn" id="goBtn">Click Here if not redirected</a>
    </div>

    <script>
        let timeLeft = 5;
        const timerElem = document.getElementById('countdown');
        const targetUrl = "{final_short_url}";
        
        const interval = setInterval(() => {{
            timeLeft--;
            if (timeLeft > 0) {{
                timerElem.innerText = timeLeft;
            }} else {{
                clearInterval(interval);
                timerElem.innerText = "0";
                window.location.href = targetUrl;
            }}
        }}, 1000);
    </script>
</body>
</html>"""
        return web.Response(text=html_content, content_type="text/html")

    except Exception as e:
        logger.error(f"Error in Koyeb redirect handler: {e}", exc_info=True)
        return web.Response(text="Invalid or expired protection link.", status=400)
                     
