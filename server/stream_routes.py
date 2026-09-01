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
# IN-MEMORY SESSION & SINGLE-USE TOKEN STORE
# =====================================================================
ACTIVE_SESSIONS = {}  # { short_id: { "owner_id": 123, "file_id": "xyz", "user_id": 456, "ts": 1788224400 } }
USED_TOKENS = set()   # Expired / Burned Tokens

def register_short_session(short_id, owner_id, file_id, user_id, ts):
    """Store short session mapping for 15 minutes"""
    current_t = int(time.time())
    expired = [k for k, v in ACTIVE_SESSIONS.items() if current_t - v.get("ts", 0) > 900]
    for k in expired:
        ACTIVE_SESSIONS.pop(k, None)
        
    ACTIVE_SESSIONS[short_id] = {
        "owner_id": owner_id,
        "file_id": file_id,
        "user_id": user_id,
        "ts": ts
    }

# =====================================================================
# UI TEMPLATES
# =====================================================================
ACCESS_DENIED_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Access Denied | Security Alert</title>
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
        <p>Bypass bot or illegitimate request detected.</p>
        <div class="alert-box">⚠️ Security violation!<br>Direct bypass links are strictly blocked.<br>Please open and complete the shortener manually.</div>
        <div class="footer">🔒 Security Enforced by <b>Mz File Store ⚡</b></div>
    </div>
</body>
</html>"""

BROWSER_GATEWAY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Validating Shortener...</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: radial-gradient(circle at center, #1e293b, #0f172a);
            color: #ffffff; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 20px;
        }}
        .card {{
            background: rgba(30, 41, 59, 0.85); padding: 35px 25px; border-radius: 24px;
            text-align: center; max-width: 380px; width: 100%; border: 1px solid rgba(255, 255, 255, 0.1);
            box-shadow: 0 20px 40px rgba(0,0,0,0.5);
        }}
        .spinner {{
            width: 48px; height: 48px; border: 4px solid rgba(56, 189, 248, 0.2);
            border-top: 4px solid #38bdf8; border-radius: 50%;
            animation: spin 1s linear infinite; margin: 20px auto;
        }}
        @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
        .btn {{
            display: none; background: #22c55e; color: white; padding: 14px;
            border-radius: 12px; text-decoration: none; font-weight: bold; margin-top: 20px;
            cursor: pointer; border: none; width: 100%; font-size: 16px;
        }}
    </style>
</head>
<body>
    <div class="card">
        <h2 style="color: #38bdf8;">🛡️ Verification in Progress</h2>
        <p style="color: #94a3b8; font-size: 14px; margin-top: 8px;" id="msg">Verifying browser impression integrity...</p>
        <div class="spinner" id="loader"></div>
        <button class="btn" id="claimBtn" onclick="verifyBrowser()">🚀 Open in Telegram</button>
    </div>

    <script>
        const short_id = "{short_id}";
        const sig = "{sig}";
        const token = "{token}";
        let startTime = Date.now();

        setTimeout(() => {{
            document.getElementById('loader').style.display = 'none';
            document.getElementById('msg').innerText = '✅ Shortener impression verified!';
            document.getElementById('claimBtn').style.display = 'block';
        }}, 2500);

        async function verifyBrowser() {{
            document.getElementById('claimBtn').innerText = 'Unlocking...';
            document.getElementById('claimBtn').disabled = true;

            try {{
                let resp = await fetch("/api/v5/confirm", {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json" }},
                    body: JSON.stringify({{
                        short_id: short_id,
                        sig: sig,
                        token: token,
                        spent: Math.floor((Date.now() - startTime) / 1000)
                    }})
                }});

                let res = await resp.json();
                if (res.status === "ok") {{
                    window.location.href = res.redirect;
                }} else {{
                    document.body.innerHTML = `{denied_html}`;
                }}
            }} catch (e) {{
                document.body.innerHTML = `{denied_html}`;
            }}
        }}
    </script>
</body>
</html>"""


@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response({"server_status": "running", "bot_status": "connected"})

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
        return web.Response(text="<h1>500 - Internal Server Error</h1>", content_type="text/html", status=500)

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
                break
        return res
    except Exception as e:
        logger.error(f"Error in stream_handler: {e}")
        return web.Response(status=500, text="Internal error.")

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
                break
        return res
    except Exception as e:
        logger.error(f"Error in download_handler: {e}")
        return web.Response(status=500, text="Internal error.")


# =====================================================================
# 🔒 SHORT LINK DESTINATION (e.g., /v/Mg4Vd7?sig=...)
# =====================================================================
@routes.get(r"/v/{short_id:[a-zA-Z0-9_\-]+}")
async def short_destination_verify_handler(request):
    short_id = request.match_info.get("short_id")
    sig_param = request.query.get("sig")

    if not sig_param or "___" not in sig_param:
        return web.Response(text=ACCESS_DENIED_HTML, content_type="text/html", status=403)

    signature, ts_str = sig_param.split("___", 1)

    try:
        ts = int(ts_str)
    except Exception:
        return web.Response(text=ACCESS_DENIED_HTML, content_type="text/html", status=403)

    # 1. Scraper filter
    ua = request.headers.get("User-Agent", "").lower()
    if any(b in ua for b in ["python", "aiohttp", "bot", "curl", "requests", "go-http", "scraper", "urllib", "wget"]):
        return web.Response(text=ACCESS_DENIED_HTML, content_type="text/html", status=403)

    # 2. Check Session Existence
    session = ACTIVE_SESSIONS.get(short_id)
    if not session or session.get("ts") != ts:
        return web.Response(text=ACCESS_DENIED_HTML, content_type="text/html", status=403)

    # 3. Cryptographic Signature Validation
    secret_key = getattr(Config, "SECRET_KEY", "mz_super_secret_anti_bypass_key_2026")
    raw_data = f"{short_id}_{ts}"
    expected_sig = hmac.new(secret_key.encode(), raw_data.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_sig, signature):
        return web.Response(text=ACCESS_DENIED_HTML, content_type="text/html", status=403)

    # 4. Generate dynamic verification challenge token
    token = hashlib.sha256(f"{short_id}_{ts}_{secret_key}_mz".encode()).hexdigest()
    
    if token in USED_TOKENS:
        return web.Response(text=ACCESS_DENIED_HTML, content_type="text/html", status=403)

    safe_denied = ACCESS_DENIED_HTML.replace("`", "'").replace("\n", "")

    return web.Response(
        text=BROWSER_GATEWAY_HTML.format(
            short_id=short_id,
            sig=sig_param,
            token=token,
            denied_html=safe_denied
        ),
        content_type="text/html"
    )


@routes.post("/api/v5/confirm")
async def api_v5_confirm_handler(request):
    try:
        data = await request.json()
        short_id = data.get("short_id", "")
        sig_param = data.get("sig", "")
        token = data.get("token", "")
        spent = int(data.get("spent", 0))

        if not sig_param or "___" not in sig_param or spent < 2:
            return web.json_response({"status": "error"}, status=403)

        # 🚨 SINGLE USE CHECK (Burned Token)
        if token in USED_TOKENS:
            return web.json_response({"status": "error", "message": "Token already consumed"}, status=403)

        signature, ts_str = sig_param.split("___", 1)
        ts = int(ts_str)

        session = ACTIVE_SESSIONS.get(short_id)
        if not session or session.get("ts") != ts:
            return web.json_response({"status": "error", "message": "Session expired or invalid"}, status=403)

        elapsed = int(time.time()) - ts

        # 🚨 Real shortener solving time window (20s - 90s max)
        if elapsed < 20 or elapsed > 90:
            return web.json_response({"status": "error", "message": "Time verification failed"}, status=403)

        secret_key = getattr(Config, "SECRET_KEY", "mz_super_secret_anti_bypass_key_2026")

        # 1. Token validation
        expected_token = hashlib.sha256(f"{short_id}_{ts}_{secret_key}_mz".encode()).hexdigest()
        if not hmac.compare_digest(expected_token, token):
            return web.json_response({"status": "error"}, status=403)

        # 2. Signature validation
        raw_data = f"{short_id}_{ts}"
        expected_sig = hmac.new(secret_key.encode(), raw_data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, signature):
            return web.json_response({"status": "error"}, status=403)

        # 🔥 Instantly Burn Token & Session
        USED_TOKENS.add(token)
        ACTIVE_SESSIONS.pop(short_id, None)

        if len(USED_TOKENS) > 10000:
            USED_TOKENS.clear()

        owner_id = session["owner_id"]
        file_unique_id = session["file_id"]
        requester_id = session["user_id"]

        # ✅ Real Human Verified -> DB Update
        await claim_verification_for_file(owner_id, file_unique_id, requester_id)

        bot = request.app.get('bot')
        bot_username = bot.me.username if bot and hasattr(bot, 'me') and bot.me else "Mzfilestorage_bot"

        if not bot_username and os.path.exists(Config.BOT_USERNAME_FILE):
            with open(Config.BOT_USERNAME_FILE, "r") as f:
                bot_username = f.read().strip()

        bot_deep_link = f"https://t.me/{bot_username}?start=get_{owner_id}_{file_unique_id}"
        return web.json_response({"status": "ok", "redirect": bot_deep_link})

    except Exception as e:
        logger.error(f"Error in api_v5_confirm: {e}")
        return web.json_response({"status": "error"}, status=400)
      
