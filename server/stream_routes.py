# server/stream_routes.py

import os
import time
import hmac
import hashlib
import logging
from aiohttp import web
from aiohttp.client_exceptions import ClientConnectionResetError
from util.render_template import render_player_page
from util.custom_dl import ByteStreamer
from util.file_properties import get_media_from_message
from database.db import claim_verification_for_file
from config import Config
from pyrogram.errors import RPCError

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()

# =====================================================================
# UI TEMPLATES (ACCESS DENIED & SUCCESS REDIRECT)
# =====================================================================
ACCESS_DENIED_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Access Denied | Av Bypass Bot</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background: linear-gradient(180deg, #dbeafe 0%, #ede9fe 50%, #fce7f3 100%);
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding: 20px;
        }
        .card {
            background: #ffffff; padding: 45px 30px; border-radius: 32px;
            box-shadow: 0 20px 50px rgba(99, 102, 241, 0.08); text-align: center;
            max-width: 380px; width: 100%; border: 1px solid rgba(255, 255, 255, 0.8);
        }
        .icon-box {
            width: 88px; height: 88px; background: #fff1f2; border-radius: 28px;
            display: flex; align-items: center; justify-content: center;
            margin: 0 auto 24px; border: 2px solid #fecdd3; transform: rotate(45deg);
        }
        .icon-symbol { transform: rotate(-45deg); font-size: 38px; color: #ef4444; }
        h2 { color: #ef4444; font-size: 26px; margin-bottom: 12px; font-weight: 800; }
        p { color: #64748b; font-size: 15px; line-height: 1.5; margin-bottom: 25px; }
        .alert-box {
            background: #fff1f2; color: #e11d48; padding: 16px;
            border-radius: 18px; font-size: 14px; font-weight: 700;
            margin-bottom: 30px; border: 1.5px dashed #fecdd3; line-height: 1.4;
        }
        .footer { color: #6366f1; font-size: 14px; font-weight: 700; }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon-box"><div class="icon-symbol">🚫</div></div>
        <h2>🚫 Access denied!</h2>
        <p>We could not process your request due to a security violation.</p>
        <div class="alert-box">⚠️ ⚠️ Invalid security signature!<br>Please generate a new link.</div>
        <div class="footer">🔒 Security Enforced by <b>Av Bypass Bot ⚡</b></div>
    </div>
</body>
</html>"""

SUCCESS_REDIRECT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Verification Success</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: radial-gradient(circle at center, #1e293b, #0f172a);
            color: #ffffff; font-family: -apple-system, sans-serif;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; padding: 20px;
        }}
        .card {{
            background: rgba(30, 41, 59, 0.85); padding: 35px 25px; border-radius: 20px;
            text-align: center; max-width: 380px; width: 90%; border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        h2 {{ color: #22c55e; margin-bottom: 8px; }}
        p {{ color: #94a3b8; font-size: 14px; margin-bottom: 25px; line-height: 1.5; }}
        .btn {{
            display: block; width: 100%; background: #22c55e; color: white;
            padding: 14px; border-radius: 12px; text-decoration: none; font-weight: bold;
        }}
    </style>
</head>
<body>
    <div class="card">
        <h2>✅ Verification Successful!</h2>
        <p>Your access is now valid for <b>24 Hours</b>.<br>Redirecting to bot...</p>
        <a href="{bot_url}" class="btn">🚀 Open in Telegram</a>
    </div>
    <script>
        setTimeout(() => {{ window.location.href = "{bot_url}"; }}, 2000);
    </script>
</body>
</html>"""


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
# 🔒 SHORTENER DESTINATION GATEWAY (HMAC & TIME-LOCK ANTI-BYPASS)
# =====================================================================
@routes.get(r"/destination/{payload:[a-zA-Z0-9_\-]+}")
async def shortener_destination_verify_handler(request):
    payload = request.match_info.get("payload") # Format: ownerid_fileid_userid
    sig_param = request.query.get("sig")        # Format: <sig>___<timestamp>

    if not sig_param or "___" not in sig_param:
        return web.Response(text=ACCESS_DENIED_HTML, content_type="text/html", status=403)

    signature, ts_str = sig_param.split("___", 1)

    try:
        ts = int(ts_str)
        parts = payload.split("_")
        if len(parts) < 3:
            return web.Response(text=ACCESS_DENIED_HTML, content_type="text/html", status=403)
            
        owner_id = int(parts[0])
        file_unique_id = parts[1]
        requester_id = int(parts[2])
    except Exception:
        return web.Response(text=ACCESS_DENIED_HTML, content_type="text/html", status=403)

    elapsed = int(time.time()) - ts
    link_expiry = getattr(Config, "LINK_EXPIRY", 900)

    # 1. 🚨 Anti-Bypass Check (Bypass bot 20s ke andar bypass karta hai)
    if elapsed < 20:
        return web.Response(text=ACCESS_DENIED_HTML, content_type="text/html", status=403)

    # 2. Expiry Check (Default: 15 minutes)
    if elapsed > link_expiry:
        return web.Response(text=ACCESS_DENIED_HTML, content_type="text/html", status=403)

    # 3. Cryptographic Signature Match
    secret_key = getattr(Config, "SECRET_KEY", "mz_super_secret_anti_bypass_key_2026")
    raw_data = f"{payload}_{ts}"
    expected_sig = hmac.new(secret_key.encode(), raw_data.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_sig, signature):
        return web.Response(text=ACCESS_DENIED_HTML, content_type="text/html", status=403)

    # ✅ Verification Pass -> Database me user ko 24 hours ke liye verify karein
    await claim_verification_for_file(owner_id, file_unique_id, requester_id)

    # Telegram Bot Deep Link URL
    bot = request.app.get('bot')
    bot_username = bot.me.username if bot and hasattr(bot, 'me') and bot.me else None
    
    if not bot_username and os.path.exists(Config.BOT_USERNAME_FILE):
        with open(Config.BOT_USERNAME_FILE, "r") as f:
            bot_username = f.read().strip()

    bot_deep_link = f"https://t.me/{bot_username}?start=get_{owner_id}_{file_unique_id}"

    return web.Response(
        text=SUCCESS_REDIRECT_HTML.format(bot_url=bot_deep_link),
        content_type="text/html"
    )
    
