import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
import sqlite3
import threading
import requests
from flask import Flask, request
import time
import datetime
from collections import defaultdict
from collections import deque
import asyncio
import json

# retrieve information from .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')
REDIRECT_URI = os.getenv('DISCORD_REDIRECT_URI')

# retrieve DB file from env
DB_FILE = os.getenv("DB_PATH", "users.db")

# for logging purposes
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='a')
logging.basicConfig(level=logging.INFO, handlers=[handler])

# intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix='/', intents=intents, help_command=None)

# === Default Moderation Settings ===
DEFAULT_BAD_WORDS = ["badword1", "badword2", "example"]
DEFAULT_BANNED_LINKS = ["discord.gg", "bit.ly"]
DEFAULT_CAPS_THRESHOLD = 0.7  # 70% caps
DEFAULT_SPAM_WINDOW = 5       # seconds
DEFAULT_SPAM_THRESHOLD = 5    # messages
LOG_CHANNEL_ID = None  # set to an int channel ID if you want logs to be posted (e.g. 123456789012345678)

# === Default Anti-Raid Settings ===
DEFAULT_ACCOUNT_AGE_DAYS = 7
DEFAULT_JOIN_THRESHOLD = 5
DEFAULT_JOIN_WINDOW = 30  # seconds
join_logs = defaultdict(lambda: deque(maxlen=20))

# Anti-spam tracking (in-memory)
user_message_logs = defaultdict(list)

# === Default Auto-slowmode Settings (global fallback) ===
DEFAULT_TIME_CONFIGS = {
    50: 30,
    20: 15,
    10: 5,
    0: 0
}
DEFAULT_CHECK_FREQUENCY = 30  # seconds
SLOWMODE_EDIT_DELAY = 0.6     # seconds between edits to avoid rate limits

# auto-slowmode runtime variables
message_cache = {}     # {channel_id: message_count}
previous_delays = {}   # {channel_id: previous_delay}
last_updated = 0

# database setup
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        discord_id TEXT PRIMARY KEY,
        twitch_username TEXT,
        youtube_channel TEXT
    )
    """)

    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS guild_settings (
        guild_id TEXT PRIMARY KEY,
        autoslow_enabled INTEGER DEFAULT 1,
        check_frequency INTEGER DEFAULT 10,
        time_configs TEXT,
        blacklisted_channels TEXT,
        moderation_enabled INTEGER DEFAULT 1,
        bad_words TEXT,
        banned_links TEXT,
        caps_threshold REAL DEFAULT 0.7,
        spam_window INTEGER DEFAULT 10,
        spam_threshold INTEGER DEFAULT 5,
        antiraid_enabled INTEGER DEFAULT 0,
        join_threshold INTEGER DEFAULT 5,
        join_window INTEGER DEFAULT 30,
        min_account_age_days INTEGER DEFAULT 7
    )
    """)
    conn.commit()
    conn.close()

init_db()

def get_guild_settings(guild_id: int) -> dict:
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""SELECT autoslow_enabled, check_frequency, time_configs, blacklisted_channels, 
                   moderation_enabled, bad_words, banned_links, 
                   caps_threshold, spam_window, spam_threshold,
                   antiraid_enabled, join_threshold, join_window, min_account_age_days
                   FROM guild_settings WHERE guild_id = ?""", (str(guild_id),))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {
            "autoslow_enabled": True,
            "check_frequency": DEFAULT_CHECK_FREQUENCY,
            "time_configs": DEFAULT_TIME_CONFIGS.copy(),
            "blacklisted_channels": [],
            "moderation_enabled": True,
            "bad_words": DEFAULT_BAD_WORDS.copy(),
            "banned_links": DEFAULT_BANNED_LINKS.copy(),
            "caps_threshold": DEFAULT_CAPS_THRESHOLD,
            "spam_window": DEFAULT_SPAM_WINDOW,
            "spam_threshold": DEFAULT_SPAM_THRESHOLD,
            "antiraid_enabled": False,
            "join_threshold": DEFAULT_JOIN_THRESHOLD,
            "join_window": DEFAULT_JOIN_WINDOW,
            "min_account_age_days": DEFAULT_ACCOUNT_AGE_DAYS
        }

    (autoslow_enabled, check_frequency, time_configs_json, blacklisted_json,
     moderation_enabled, bad_words_json, banned_links_json, caps_threshold, spam_window, spam_threshold,
     antiraid_enabled, join_threshold, join_window, min_account_age_days) = row

    def _parse(j, default):
        try:
            return json.loads(j) if j else default
        except Exception:
            return default

    return {
        "autoslow_enabled": bool(autoslow_enabled),
        "check_frequency": int(check_frequency or DEFAULT_CHECK_FREQUENCY),
        "time_configs": _parse(time_configs_json, DEFAULT_TIME_CONFIGS.copy()),
        "blacklisted_channels": _parse(blacklisted_json, []),
        "moderation_enabled": bool(moderation_enabled),
        "bad_words": _parse(bad_words_json, DEFAULT_BAD_WORDS.copy()),
        "banned_links": _parse(banned_links_json, DEFAULT_BANNED_LINKS.copy()),
        "caps_threshold": float(caps_threshold or DEFAULT_CAPS_THRESHOLD),
        "spam_window": int(spam_window or DEFAULT_SPAM_WINDOW),
        "spam_threshold": int(spam_threshold or DEFAULT_SPAM_THRESHOLD),
        "antiraid_enabled": bool(antiraid_enabled),
        "join_threshold": int(join_threshold or DEFAULT_JOIN_THRESHOLD),
        "join_window": int(join_window or DEFAULT_JOIN_WINDOW),
        "min_account_age_days": int(min_account_age_days or DEFAULT_ACCOUNT_AGE_DAYS)
    }

def save_guild_settings(guild_id: int, settings: dict):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO guild_settings (
        guild_id, autoslow_enabled, check_frequency, time_configs, blacklisted_channels, 
        moderation_enabled, bad_words, banned_links, caps_threshold, 
        spam_window, spam_threshold, antiraid_enabled, join_threshold, join_window, min_account_age_days
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(guild_id),
        1 if settings.get("autoslow_enabled", True) else 0,
        int(settings.get("check_frequency", DEFAULT_CHECK_FREQUENCY)),
        json.dumps(settings.get("time_configs", DEFAULT_TIME_CONFIGS)),
        json.dumps(settings.get("blacklisted_channels", [])),
        1 if settings.get("moderation_enabled", True) else 0,
        json.dumps(settings.get("bad_words", DEFAULT_BAD_WORDS)),
        json.dumps(settings.get("banned_links", DEFAULT_BANNED_LINKS)),
        float(settings.get("caps_threshold", DEFAULT_CAPS_THRESHOLD)),
        int(settings.get("spam_window", DEFAULT_SPAM_WINDOW)),
        int(settings.get("spam_threshold", DEFAULT_SPAM_THRESHOLD)),
        1 if settings.get("antiraid_enabled", False) else 0,
        int(settings.get("join_threshold", DEFAULT_JOIN_THRESHOLD)),
        int(settings.get("join_window", DEFAULT_JOIN_WINDOW)),
        int(settings.get("min_account_age_days", DEFAULT_ACCOUNT_AGE_DAYS))
    ))
    conn.commit()
    conn.close()

# === Flask App (OAuth2 callback) ===
app = Flask(__name__)

@app.route("/")
def index():
    return "OAuth2 Server Running!"

@app.route("/callback")
def callback():
    code = request.args.get("code")
    state = request.args.get("state")  # identify twitch vs youtube
    if not code:
        return "No code provided", 400

    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    token_res = requests.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
    token_res.raise_for_status()
    access_token = token_res.json()["access_token"]

    user_res = requests.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {access_token}"})
    user_res.raise_for_status()
    user_data = user_res.json()
    discord_id = user_data["id"]

    conn_res = requests.get("https://discord.com/api/users/@me/connections", headers={"Authorization": f"Bearer {access_token}"})
    conn_res.raise_for_status()
    connections = conn_res.json()

    twitch_name = None
    youtube_name = None
    for c in connections:
        if c.get("type") == "twitch" and state != "youtube":
            twitch_name = c.get("name")
        elif c.get("type") == "youtube" and state == "youtube":
            youtube_name = c.get("name")

    sql_conn = sqlite3.connect(DB_FILE)
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

# === Moderation Helpers ===
def is_spam(user_id, current_time, spam_window, spam_threshold):
    message_times = user_message_logs[user_id]
    message_times.append(current_time)
    user_message_logs[user_id] = [t for t in message_times if current_time - t < spam_window]
    return len(user_message_logs[user_id]) >= spam_threshold

async def warn_user(user, reason):
    try:
        await user.send(f"⚠️ You have been warned: {reason}")
    except discord.Forbidden:
        pass
    await log_to_channel(f"⚠️ Warned {user.mention} for: {reason}")

async def mute_user(user, duration=60, reason=""):
    guild = user.guild
    if guild is None:
        return
    mute_role = discord.utils.get(guild.roles, name="Muted")
    if not mute_role:
        try:
            mute_role = await guild.create_role(name="Muted")
            for channel in guild.channels:
                try:
                    await channel.set_permissions(mute_role, send_messages=False, speak=False)
                except Exception:
                    pass
        except Exception:
            pass
    try:
        await user.add_roles(mute_role, reason=reason)
    except Exception:
        pass
    await warn_user(user, f"You were muted for {duration} seconds: {reason}")
    await log_to_channel(f"🔇 Muted {user.mention} for {duration}s. Reason: {reason}")
    await asyncio.sleep(duration)
    try:
        await user.remove_roles(mute_role)
    except Exception:
        pass
    await log_to_channel(f"🔊 Unmuted {user.mention} after {duration}s.")

async def log_to_channel(message):
    if LOG_CHANNEL_ID:
        channel = bot.get_channel(LOG_CHANNEL_ID)
        if channel:
            try:
                await channel.send(message)
            except Exception:
                pass

# === Auto-slowmode core ===
def get_delay_from_configs(message_count, configs: dict):
    for limit in sorted(map(int, configs.keys()), reverse=True):
        if message_count >= limit:
            return configs[int(limit)]
    return 0

async def update_slowmode_batched():
    global last_updated, message_cache, previous_delays
    if not message_cache:
        last_updated = time.time()
        return
    changes = []
    for channel_id, msg_count in list(message_cache.items()):
        ch = bot.get_channel(channel_id)
        if not ch or not isinstance(ch, discord.TextChannel):
            continue
        guild_id = ch.guild.id
        settings = get_guild_settings(guild_id)
        if not settings.get("autoslow_enabled", True):
            continue
        bl = settings.get("blacklisted_channels", [])
        if channel_id in bl:
            continue
        configs = settings.get("time_configs", DEFAULT_TIME_CONFIGS)
        parsed_configs = {int(k): int(v) for k, v in configs.items()}
        delay = 0
        for limit in sorted(parsed_configs.keys(), reverse=True):
            if msg_count >= limit:
                delay = parsed_configs[limit]
                break
        prev = previous_delays.get(channel_id, None)
        if prev != delay:
            changes.append((ch, delay, msg_count))
    if not changes:
        message_cache = {}
        last_updated = time.time()
        return
    for channel_obj, delay, msg_count in changes:
        try:
            await channel_obj.edit(slowmode_delay=delay, reason="Auto slowmode adjustment")
            previous_delays[channel_obj.id] = delay
            await log_to_channel(f"⏱️ Set slowmode for #{channel_obj.name} to {delay}s (messages: {msg_count})")
        except Exception as e:
            await log_to_channel(f"⚠️ Failed to set slowmode for #{channel_obj.name}: {e}")
        await asyncio.sleep(SLOWMODE_EDIT_DELAY)
    message_cache = {}
    last_updated = time.time()

# === BOT EVENTS ===
@bot.event
async def on_ready():
    logging.info(f"✅ Bot is ready: {bot.user.name}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    guild = message.guild
    guild_settings = get_guild_settings(guild.id) if guild else None
    if guild_settings and guild_settings.get("moderation_enabled", True):
        content = message.content
        content_lower = content.lower() if content else ""
        author = message.author
        current_time = time.time()
        bad_words = guild_settings.get("bad_words", DEFAULT_BAD_WORDS)
        if any(w in content_lower for w in bad_words):
            try: await message.delete()
            except: pass
            await warn_user(author, "Inappropriate language.")
            return
        caps_threshold = float(guild_settings.get("caps_threshold", DEFAULT_CAPS_THRESHOLD))
        if content and len(content) > 10:
            cap_ratio = sum(1 for c in content if c.isupper()) / max(len(content), 1)
            if cap_ratio > caps_threshold:
                try: await message.delete()
                except: pass
                await warn_user(author, "Too many capital letters.")
                return
        banned_links = guild_settings.get("banned_links", DEFAULT_BANNED_LINKS)
        if any(bad_link in content_lower for bad_link in banned_links):
            try: await message.delete()
            except: pass
            await warn_user(author, "Posting invite or banned links.")
            return
        spam_window = int(guild_settings.get("spam_window", DEFAULT_SPAM_WINDOW))
        spam_threshold = int(guild_settings.get("spam_threshold", DEFAULT_SPAM_THRESHOLD))
        if is_spam(author.id, current_time, spam_window, spam_threshold):
            try: await message.delete()
            except: pass
            await mute_user(author, duration=60, reason="Spamming messages.")
            return
    if guild_settings and guild_settings.get("autoslow_enabled", True):
        ch_id = message.channel.id
        bl = guild_settings.get("blacklisted_channels", [])
        if ch_id in bl:
            await bot.process_commands(message)
            return
        message_cache[ch_id] = message_cache.get(ch_id, 0) + 1
        if time.time() >= last_updated + guild_settings.get("check_frequency", DEFAULT_CHECK_FREQUENCY):
            bot.loop.create_task(update_slowmode_batched())
    await bot.process_commands(message)

# === Commands ===
@bot.command(name="help")
async def bot_help(ctx):
    help_text = (
        "**Available commands**\n\n"
        "**Public**\n"
        "/hello — Say hi (Feature will be removed)\n"
        "/linktwitch — Get OAuth link in DM\n"
        "/twitch <member> — Show linked Twitch\n"
        "/unlinktwitch — Unlink Twitch\n"
        "/linkyoutube — Get OAuth link in DM\n"
        "/youtube <member> — Show linked YouTube\n"
        "/unlinkyoutube — Unlink YouTube\n\n"
        "**Lockdown / Slowmode (Administrator)**\n"
        "/lock1 — Set 15s slowmode on all text channels\n"
        "/lock2 — Set 30s slowmode on all text channels\n"
        "/lock3 — Set 60s slowmode on all text channels\n"
        "/unlock — Remove slowmode on all text channels\n\n"

        "**Auto-slowmode (Administrator)**\n"
        "/autoslow enable|disable|status (Applies to all channels except blacklisted)\n"
        "/autoslow_blacklist add|remove|list #channel (Unable to test)\n"
        "/set_slowmode_thresholds 50:30,20:15,10:5,0:0 — /set_slowmode_thresholds 10:5 -> every 10 messages = 5s slowmode (Testing)\n"
        "/set_check_frequency <seconds> — check how frequently for /set_slowmode_thresholds (Testing)\n\n"
        "**Moderation (Administrator)**\n"
        "/moderation enable|disable\n"
        "/badword add|remove|list <word>\n"
        "/bannedlink add|remove|list <link>\n"
        "/unban <user_id> — Unban a user via their ID\n\n"
        
        "**Anti-Raid (Administrator)**\n"
        "/antiraid enable|disable|status — Toggle raid mode\n\n"

    )
    await ctx.send(help_text)

@bot.command()
async def hello(ctx):
    await ctx.send(f"Hello {ctx.author.mention}!")

# === Twitch Commands ===
@bot.command()
async def linktwitch(ctx):
    if not CLIENT_ID or not REDIRECT_URI:
        await ctx.author.send("OAuth not configured.")
        return
    url = (f"https://discord.com/api/oauth2/authorize"
       f"?client_id={CLIENT_ID}"
       f"&redirect_uri={REDIRECT_URI}"
       f"&response_type=code"
       f"&scope=identify%20connections")
    try:
        await ctx.author.send(f"Click here to link your Twitch: {url}")
        await ctx.send(f"{ctx.author.mention}, check your DMs to link Twitch!")
    except discord.Forbidden:
        await ctx.send("Couldn't DM you. Enable DMs.")

@bot.command()
async def twitch(ctx, member: discord.Member = None):
    member = member or ctx.author
    conn = sqlite3.connect(DB_FILE); cur = conn.cursor()
    cur.execute("SELECT twitch_username FROM users WHERE discord_id = ?", (str(member.id),))
    row = cur.fetchone(); conn.close()
    if row and row[0]:
        await ctx.send(f"{member.display_name}'s Twitch: **{row[0]}**")
    else:
        await ctx.send(f"{member.display_name} has not linked a Twitch account.")

@bot.command()
async def unlinktwitch(ctx):
    conn = sqlite3.connect(DB_FILE); cur = conn.cursor()
    cur.execute("UPDATE users SET twitch_username=NULL WHERE discord_id=?", (str(ctx.author.id),))
    conn.commit(); conn.close()
    await ctx.send(f"{ctx.author.mention}, your Twitch account has been unlinked.")

# === YouTube Commands ===
@bot.command()
async def linkyoutube(ctx):
    if not CLIENT_ID or not REDIRECT_URI:
        await ctx.author.send("OAuth not configured.")
        return
    url = (f"https://discord.com/api/oauth2/authorize"
       f"?client_id={CLIENT_ID}"
       f"&redirect_uri={REDIRECT_URI}"
       f"&response_type=code"
       f"&scope=identify%20connections"
       f"&state=youtube")
    try:
        await ctx.author.send(f"Click here to link your YouTube: {url}")
        await ctx.send(f"{ctx.author.mention}, check your DMs to link YouTube!")
    except discord.Forbidden:
        await ctx.send("Couldn't DM you. Enable DMs.")

@bot.command()
async def youtube(ctx, member: discord.Member = None):
    member = member or ctx.author
    conn = sqlite3.connect(DB_FILE); cur = conn.cursor()
    cur.execute("SELECT youtube_channel FROM users WHERE discord_id = ?", (str(member.id),))
    row = cur.fetchone(); conn.close()
    if row and row[0]:
        await ctx.send(f"{member.display_name}'s YouTube: **{row[0]}**")
    else:
        await ctx.send(f"{member.display_name} has not linked a YouTube account.")

@bot.command()
async def unlinkyoutube(ctx):
    conn = sqlite3.connect(DB_FILE); cur = conn.cursor()
    cur.execute("UPDATE users SET youtube_channel=NULL WHERE discord_id=?", (str(ctx.author.id),))
    conn.commit(); conn.close()
    await ctx.send(f"{ctx.author.mention}, your YouTube account has been unlinked.")

# === Lockdown Commands ===
@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock1(ctx):
    """Set 15s slowmode on all text channels."""
    await apply_lockdown(ctx, 15, "Lockdown level 1 (15s slowmode)")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock2(ctx):
    """Set 30s slowmode on all text channels."""
    await apply_lockdown(ctx, 30, "Lockdown level 2 (30s slowmode)")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock3(ctx):
    """Set 60s slowmode on all text channels."""
    await apply_lockdown(ctx, 60, "Lockdown level 3 (60s slowmode)")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
    """Remove slowmode from all text channels."""
    await apply_lockdown(ctx, 0, "Lockdown lifted (0s slowmode)")

async def apply_lockdown(ctx, delay: int, description: str):
    color = discord.Color.red() if delay > 0 else discord.Color.green()
    embed = discord.Embed(
        title="🔒 Lockdown Update",
        description=description,
        color=color
    )
    await ctx.send(embed=embed)

    for ch in ctx.guild.channels:
        if isinstance(ch, discord.TextChannel):
            try:
                await ch.edit(slowmode_delay=delay, reason=description)
            except discord.Forbidden:
                await log_to_channel(f"⚠️ Missing permission for #{ch.name}")
            except discord.HTTPException as e:
                await log_to_channel(f"⚠️ Failed to set slowmode for #{ch.name}: {e}")
            await asyncio.sleep(SLOWMODE_EDIT_DELAY)

# === Admin Auto-slowmode Commands ===
@bot.command()
@commands.has_permissions(administrator=True)
async def autoslow(ctx, action: str = None):
    settings = get_guild_settings(ctx.guild.id)
    if action == "enable":
        settings["autoslow_enabled"] = True; save_guild_settings(ctx.guild.id, settings)
        await ctx.send("✅ Auto-slowmode enabled.")
    elif action == "disable":
        settings["autoslow_enabled"] = False; save_guild_settings(ctx.guild.id, settings)
        await ctx.send("❌ Auto-slowmode disabled.")
    elif action == "status":
        await ctx.send(f"Auto-slowmode is {'enabled' if settings['autoslow_enabled'] else 'disabled'}.")
    else:
        await ctx.send("Usage: /autoslow enable|disable|status")

@bot.command()
@commands.has_permissions(administrator=True)
async def autoslow_blacklist(ctx, action: str = None, channel: discord.TextChannel = None):
    settings = get_guild_settings(ctx.guild.id)
    bl = settings.get("blacklisted_channels", [])
    if action == "add" and channel:
        if channel.id not in bl: bl.append(channel.id)
        settings["blacklisted_channels"] = bl; save_guild_settings(ctx.guild.id, settings)
        await ctx.send(f"✅ Added {channel.mention} to auto-slowmode blacklist.")
    elif action == "remove" and channel:
        if channel.id in bl: bl.remove(channel.id)
        settings["blacklisted_channels"] = bl; save_guild_settings(ctx.guild.id, settings)
        await ctx.send(f"❌ Removed {channel.mention} from auto-slowmode blacklist.")
    elif action == "list":
        if not bl: await ctx.send("Blacklist is empty.")
        else: await ctx.send("Blacklisted: " + ", ".join(f"<#{c}>" for c in bl))
    else:
        await ctx.send("Usage: /autoslow_blacklist add|remove|list #channel")

@bot.command()
@commands.has_permissions(administrator=True)
async def set_slowmode_thresholds(ctx, *, thresholds: str):
    try:
        pairs = thresholds.split(","); configs = {}
        for pair in pairs:
            limit, delay = pair.split(":")
            configs[int(limit.strip())] = int(delay.strip())
        settings = get_guild_settings(ctx.guild.id)
        settings["time_configs"] = configs; save_guild_settings(ctx.guild.id, settings)
        await ctx.send(f"✅ Thresholds updated: {configs}")
    except Exception as e:
        await ctx.send(f"Error parsing thresholds: {e}")

@bot.command()
@commands.has_permissions(administrator=True)
async def set_check_frequency(ctx, seconds: int):
    settings = get_guild_settings(ctx.guild.id)
    settings["check_frequency"] = seconds; save_guild_settings(ctx.guild.id, settings)
    await ctx.send(f"✅ Check frequency set to {seconds} seconds.")

# === Moderation Commands ===
@bot.command()
@commands.has_permissions(administrator=True)
async def moderation(ctx, action: str = None):
    settings = get_guild_settings(ctx.guild.id)
    if action == "enable":
        settings["moderation_enabled"] = True; save_guild_settings(ctx.guild.id, settings)
        await ctx.send("✅ Moderation enabled.")
    elif action == "disable":
        settings["moderation_enabled"] = False; save_guild_settings(ctx.guild.id, settings)
        await ctx.send("❌ Moderation disabled.")
    else:
        await ctx.send("Usage: /moderation enable|disable")

@bot.command()
@commands.has_permissions(administrator=True)
async def badword(ctx, action: str = None, *, word: str = None):
    settings = get_guild_settings(ctx.guild.id)
    words = settings.get("bad_words", DEFAULT_BAD_WORDS)
    if action == "add" and word:
        words.append(word.lower())
        settings["bad_words"] = words; save_guild_settings(ctx.guild.id, settings)
        await ctx.send(f"✅ Added bad word: {word}")
    elif action == "remove" and word:
        if word.lower() in words: words.remove(word.lower())
        settings["bad_words"] = words; save_guild_settings(ctx.guild.id, settings)
        await ctx.send(f"❌ Removed bad word: {word}")
    elif action == "list":
        await ctx.send("Bad words: " + ", ".join(words))
    else:
        await ctx.send("Usage: /badword add|remove|list <word>")

@bot.command()
@commands.has_permissions(administrator=True)
async def bannedlink(ctx, action: str = None, *, link: str = None):
    settings = get_guild_settings(ctx.guild.id)
    links = settings.get("banned_links", DEFAULT_BANNED_LINKS)
    if action == "add" and link:
        links.append(link.lower())
        settings["banned_links"] = links; save_guild_settings(ctx.guild.id, settings)
        await ctx.send(f"✅ Added banned link: {link}")
    elif action == "remove" and link:
        if link.lower() in links: links.remove(link.lower())
        settings["banned_links"] = links; save_guild_settings(ctx.guild.id, settings)
        await ctx.send(f"❌ Removed banned link: {link}")
    elif action == "list":
        await ctx.send("Banned links: " + ", ".join(links))
    else:
        await ctx.send("Usage: /bannedlink add|remove|list <link>")

@bot.command()
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int):
    """Unban a user by their ID."""
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user)
        await ctx.send(f"✅ Unbanned {user.mention} ({user.id})")
    except discord.NotFound:
        await ctx.send("⚠️ That user was not found in the ban list.")
    except discord.Forbidden:
        await ctx.send("⚠️ I don't have permission to unban.")
    except Exception as e:
        await ctx.send(f"⚠️ Failed to unban: {e}")

# === Anti-Raid Events ===
@bot.event
async def on_member_join(member):
    guild_id = member.guild.id
    settings = get_guild_settings(guild_id)
    now = time.time()
    join_logs[guild_id].append(now)

    # Account age enforcement
    min_age_days = settings.get("min_account_age_days", DEFAULT_ACCOUNT_AGE_DAYS)
    account_age_days = (discord.utils.utcnow() - member.created_at).days
    if account_age_days < min_age_days:
        try:
            until = discord.utils.utcnow() + datetime.timedelta(seconds=300)
            await member.edit(timed_out_until=until, reason="Account too new (anti-raid)")
            await log_to_channel(f"⚠️ {member.mention} auto-timed out (account {account_age_days}d < {min_age_days}d).")
        except Exception:
            pass

    # Raid mode toggle
    if settings.get("antiraid_enabled", False):
        try:
            until = discord.utils.utcnow() + datetime.timedelta(seconds=600)
            await member.edit(timed_out_until=until, reason="Raid mode active")
            await log_to_channel(f"🚨 {member.mention} auto-timed out (raid mode active).")
        except Exception:
            pass

    # Burst join detection
    join_window = settings.get("join_window", DEFAULT_JOIN_WINDOW)
    join_threshold = settings.get("join_threshold", DEFAULT_JOIN_THRESHOLD)
    joins_recent = [t for t in join_logs[guild_id] if now - t < join_window]

    if len(joins_recent) >= join_threshold:
        await log_to_channel(f"🚨 Raid suspected: {len(joins_recent)} joins in {join_window}s in {member.guild.name}. Lockdown applied.")
        for ch in member.guild.text_channels:
            try:
                await ch.edit(slowmode_delay=30, reason="Anti-raid triggered")
            except Exception:
                pass
        await log_to_channel("⏱️ Auto-lockdown applied (30s slowmode).")

# === Anti-Raid Command ===
@bot.command()
@commands.has_permissions(administrator=True)
async def antiraid(ctx, action: str = None):
    """Toggle anti-raid mode (manual)."""
    settings = get_guild_settings(ctx.guild.id)
    if action == "enable":
        settings["antiraid_enabled"] = True
        save_guild_settings(ctx.guild.id, settings)
        await ctx.send("✅ Anti-raid mode enabled. New joins will be auto-timed out.")
    elif action == "disable":
        settings["antiraid_enabled"] = False
        save_guild_settings(ctx.guild.id, settings)
        await ctx.send("❌ Anti-raid mode disabled.")
    elif action == "status":
        state = "enabled" if settings.get("antiraid_enabled", False) else "disabled"
        await ctx.send(f"ℹ️ Anti-raid mode is currently {state}.")
    else:
        await ctx.send("Usage: /antiraid enable|disable|status")

# === Run Flask ===
def run_flask():
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# === Run Discord Bot ===
if not TOKEN:
    print("ERROR: DISCORD_TOKEN not set in environment.")
else:
    bot.run(TOKEN, log_handler=handler, log_level=logging.INFO)