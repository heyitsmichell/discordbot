import asyncio
import aiohttp
import time
import requests
import discord
import config
import hmac
import hashlib
from database import get_discord_ids_by_twitch, get_streamer, update_streamer_tokens

# Global variables
ban_queue = asyncio.Queue()
TWITCH_APP_TOKEN = None
TWITCH_APP_TOKEN_EXPIRES_AT = 0

async def get_twitch_app_token():
    """Get or refresh Twitch app token."""
    global TWITCH_APP_TOKEN, TWITCH_APP_TOKEN_EXPIRES_AT
    
    if TWITCH_APP_TOKEN and time.time() < TWITCH_APP_TOKEN_EXPIRES_AT - 30:
        return TWITCH_APP_TOKEN

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": config.TWITCH_CLIENT_ID,
                "client_secret": config.TWITCH_CLIENT_SECRET,
                "grant_type": "client_credentials",
            },
        ) as resp:
            data = await resp.json()
    
    if not data or "access_token" not in data:
        raise RuntimeError(f"Failed to fetch twitch app token: {data}")
    
    TWITCH_APP_TOKEN = data["access_token"]
    expires_in = int(data.get("expires_in", 3600))
    TWITCH_APP_TOKEN_EXPIRES_AT = time.time() + expires_in
    return TWITCH_APP_TOKEN

async def handle_twitch_ban(bot, twitch_identifier: str):
    """Handle Twitch ban event."""
    if not twitch_identifier:
        return

    discord_ids = get_discord_ids_by_twitch(twitch_identifier)
    if not discord_ids:
        print(f"ℹ️ No Discord account linked for Twitch identifier '{twitch_identifier}'")
        return

    print(f"ℹ️ Twitch identifier '{twitch_identifier}' maps to Discord IDs: {discord_ids}")

    for discord_id_str in discord_ids:
        try:
            discord_id = int(discord_id_str)
        except Exception:
            print(f"⚠️ Invalid discord id stored in DB: {discord_id_str}")
            continue

        for guild in bot.guilds:
            try:
                try:
                    await guild.fetch_ban(discord_id)
                    print(f"⚠️ Already banned {discord_id} in {guild.name} – skipping")
                    continue
                except discord.NotFound:
                    pass
                except discord.Forbidden:
                    msg = f"❌ Missing permission to query bans in {guild.name}"
                    print(msg)
                    from utils.helpers import log_to_channel
                    await log_to_channel(bot, f"[ban] {msg}")
                    continue
                except discord.HTTPException as e:
                    print(f"❌ HTTP error checking bans in {guild.name} for {discord_id}: {e}")
                    continue

                member = guild.get_member(discord_id)
                if member is None:
                    try:
                        member = await guild.fetch_member(discord_id)
                    except discord.NotFound:
                        member = discord.Object(id=discord_id)
                    except discord.Forbidden:
                        msg = f"❌ Missing permission to fetch members in {guild.name}"
                        print(msg)
                        from utils.helpers import log_to_channel
                        await log_to_channel(bot, f"[ban] {msg}")
                        continue
                    except discord.HTTPException as e:
                        print(f"❌ HTTP error fetching member {discord_id} in {guild.name}: {e}")
                        continue

                try:
                    await guild.ban(member, reason=f"Banned on Twitch ({twitch_identifier})")
                    msg = f"✅ Banned Discord ID {discord_id} from {guild.name} (Twitch: {twitch_identifier})"
                    print(msg)
                    from utils.helpers import log_to_channel
                    await log_to_channel(bot, f"[ban] {msg}")
                except discord.Forbidden:
                    msg = f"❌ Missing permission to ban {discord_id} in {guild.name}"
                    print(msg)
                    from utils.helpers import log_to_channel
                    await log_to_channel(bot, f"[ban] {msg}")
                except discord.HTTPException as e:
                    msg = f"❌ HTTP error banning {discord_id} in {guild.name}: {e}"
                    print(msg)
                    from utils.helpers import log_to_channel
                    await log_to_channel(bot, f"[ban] {msg}")

                await asyncio.sleep(0.6)

            except Exception as e:
                print(f"❌ Unexpected error while processing ban for {discord_id} in {guild.name}: {e}")
                from utils.helpers import log_to_channel
                await log_to_channel(bot, f"[ban] ERROR processing {discord_id} in {guild.name}: {e}")

async def ban_worker(bot):
    """Worker to process ban queue."""
    while True:
        twitch_user = await ban_queue.get()
        await handle_twitch_ban(bot, twitch_user)
        ban_queue.task_done()

def enqueue_ban_job(twitch_identifier: str):
    """Add ban job to queue."""
    if not twitch_identifier:
        return
    try:
        import asyncio
        asyncio.run_coroutine_threadsafe(ban_queue.put(twitch_identifier), asyncio.get_event_loop())
    except Exception as e:
        print("enqueue_ban_job error:", e)

async def twitch_get_user_by_login(login: str):
    """Get Twitch user by login."""
    if not login:
        return None
    token = await get_twitch_app_token()
    headers = {"Client-ID": config.TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://api.twitch.tv/helix/users",
            params={"login": login},
            headers=headers,
        ) as resp:
            try:
                data = await resp.json()
            except Exception:
                return None
    if not data or not data.get("data"):
        return None
    return data["data"][0]

def verify_twitch_signature(flask_request) -> bool:
    """Verify Twitch webhook signature."""
    try:
        secret = config.TWITCH_EVENTSUB_SECRET
        if not secret:
            print("verify_twitch_signature: no TWITCH_EVENTSUB_SECRET configured.")
            return False

        sig_header = flask_request.headers.get("Twitch-Eventsub-Message-Signature")
        msg_id = flask_request.headers.get("Twitch-Eventsub-Message-Id")
        msg_ts = flask_request.headers.get("Twitch-Eventsub-Message-Timestamp")
        body = flask_request.get_data() or b""

        if not sig_header or not msg_id or not msg_ts:
            print("verify_twitch_signature: missing Twitch signature headers.")
            return False

        try:
            hash_prefix, sent_sig = sig_header.split("=", 1)
        except Exception:
            print("verify_twitch_signature: bad signature header format.")
            return False

        if hash_prefix.lower() != "sha256":
            print("verify_twitch_signature: unexpected hash prefix:", hash_prefix)
            return False

        message = msg_id.encode() + msg_ts.encode() + body
        computed_hmac = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()

        if hmac.compare_digest(computed_hmac, sent_sig):
            return True
        else:
            print("verify_twitch_signature: signature mismatch.")
            return False

    except Exception as e:
        print("verify_twitch_signature exception:", e)
        return False

def refresh_streamer_token(discord_id: str):
    """Refresh streamer's OAuth token."""
    streamer = get_streamer(str(discord_id))
    if not streamer or not streamer.get("refresh_token"):
        return None
    
    refresh_token = streamer["refresh_token"]
    resp = requests.post(
        "https://id.twitch.tv/oauth2/token",
        params={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": config.TWITCH_CLIENT_ID,
            "client_secret": config.TWITCH_CLIENT_SECRET,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        return None
    
    data = resp.json()
    new_access = data.get("access_token")
    new_refresh = data.get("refresh_token", refresh_token)
    
    update_streamer_tokens(str(discord_id), new_access, new_refresh)
    
    return new_access