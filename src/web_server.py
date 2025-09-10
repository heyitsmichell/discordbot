# ========== web_server.py ==========
from flask import Flask, request
import threading
import requests
import sqlite3
import json
import config
from utils.twitch_utils import enqueue_ban_job, verify_twitch_signature

app = Flask(__name__)

@app.route("/")
def index():
    return "OAuth2 Server Running!"

@app.route("/callback")
def callback():
    """Discord OAuth callback for linking Twitch/YouTube accounts."""
    try:
        code = request.args.get("code")
        state = request.args.get("state")  # identify twitch vs youtube
        if not code:
            return "No code provided", 400

        if not config.CLIENT_ID or not config.CLIENT_SECRET or not config.REDIRECT_URI or str(config.REDIRECT_URI).strip().lower() in {"none", "null", ""}:
            return "OAuth not configured on server.", 400

        data = {
            "client_id": config.CLIENT_ID,
            "client_secret": config.CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.REDIRECT_URI
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        token_res = requests.post("https://discord.com/api/oauth2/token", data=data, headers=headers, timeout=10)
        token_res.raise_for_status()
        access_token = token_res.json().get("access_token")

        user_res = requests.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        user_res.raise_for_status()
        user_data = user_res.json()
        discord_id = user_data["id"]

        conn_res = requests.get("https://discord.com/api/users/@me/connections", headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
        conn_res.raise_for_status()
        connections = conn_res.json()

        twitch_name = None
        youtube_name = None
        for c in connections:
            if c.get("type") == "twitch" and state != "youtube":
                twitch_name = c.get("name")
            elif c.get("type") == "youtube" and state == "youtube":
                youtube_name = c.get("name")

        sql_conn = sqlite3.connect(config.DB_FILE, timeout=10)
        cur = sql_conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO users (discord_id, twitch_username, youtube_channel)
            VALUES (
                ?,
                COALESCE(?, (SELECT twitch_username FROM users WHERE discord_id=?)),
                COALESCE(?, (SELECT youtube_channel FROM users WHERE discord_id=?))
            )
        """, (discord_id, twitch_name, discord_id, youtube_name, discord_id))
        sql_conn.commit()
        sql_conn.close()

        if state == "youtube":
            return f"✅ Linked successfully! YouTube: {youtube_name}"
        return f"✅ Linked successfully! Twitch: {twitch_name}"

    except requests.HTTPError as e:
        try:
            return f"OAuth error: {e.response.status_code} {e.response.text}", 400
        except Exception:
            return f"OAuth HTTP error: {e}", 400
    except Exception as e:
        return f"Unexpected error: {e}", 500

@app.route("/twitch/streamer/callback")
def twitch_streamer_callback():
    """Twitch OAuth callback for streamers."""
    try:
        code = request.args.get("code")
        state = request.args.get("state")  # this is ctx.author.id passed in the link

        if not code or not state:
            return "Missing code or state", 400

        token_res = requests.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": config.TWITCH_CLIENT_ID,
                "client_secret": config.TWITCH_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": config.TWITCH_STREAMER_REDIRECT_URI,
            },
            timeout=10,
        )
        token_res.raise_for_status()
        token_data = token_res.json()

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        if not access_token:
            return f"Failed to get access token: {token_data}", 400

        headers = {
            "Client-ID": config.TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {access_token}"
        }
        user_res = requests.get("https://api.twitch.tv/helix/users", headers=headers, timeout=10)
        user_res.raise_for_status()
        user_data = user_res.json().get("data", [])
        if not user_data:
            return "Failed to fetch Twitch user info", 400

        user = user_data[0]
        twitch_id = user["id"]
        twitch_login = user["login"]

        conn = sqlite3.connect(config.DB_FILE, timeout=10)
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS streamers (
                discord_id TEXT PRIMARY KEY,
                twitch_id TEXT,
                twitch_username TEXT,
                access_token TEXT,
                refresh_token TEXT
            )
        """)

        cur.execute("""
            INSERT OR REPLACE INTO streamers (discord_id, twitch_id, twitch_username, access_token, refresh_token)
            VALUES (?, ?, ?, ?, ?)
        """, (str(state), twitch_id, twitch_login, access_token, refresh_token))

        # Also update users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                discord_id TEXT PRIMARY KEY,
                twitch_username TEXT,
                youtube_channel TEXT,
                twitch_id TEXT
            )
        """)
        cur.execute("""
            INSERT OR REPLACE INTO users (discord_id, twitch_username)
            VALUES (?, ?)
        """, (str(state), twitch_login))

        conn.commit()
        conn.close()

        return f"✅ Successfully linked Twitch streamer account <b>{twitch_login}</b> (ID: {twitch_id}). You can close this page."

    except requests.HTTPError as e:
        try:
            return f"OAuth error: {e.response.status_code} {e.response.text}", 400
        except Exception:
            return f"OAuth HTTP error: {e}", 400
    except Exception as e:
        return f"Unexpected error: {e}", 500

@app.route("/twitch/events", methods=["POST"])
def twitch_events():
    """Handle Twitch EventSub webhooks."""
    if not verify_twitch_signature(request):
        return "❌ Invalid signature", 403

    payload = request.json or {}
    
    # Handle webhook verification challenge
    if "challenge" in payload:
        return payload["challenge"], 200

    subscription_type = payload.get("subscription", {}).get("type")
    event = payload.get("event", {}) or {}

    if subscription_type == "channel.ban":
        user_id = event.get("user_id")
        user_login = event.get("user_login")
        if user_id:
            enqueue_ban_job(user_id)
            print(f"📩 channel.ban event received for user_id {user_id}")
        elif user_login:
            enqueue_ban_job(user_login.lower())
            print(f"📩 channel.ban event received for login {user_login}")
    
    return "", 200

def start_flask_server():
    """Start Flask server in a separate thread."""
    port = int(config.FLASK_PORT) if hasattr(config, 'FLASK_PORT') else 5000
    
    def run_flask():
        app.run(host="0.0.0.0", port=port)
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"Flask server started on port {port}")