import sqlite3
import json
import config

def init_db():
    conn = sqlite3.connect(config.DB_FILE, timeout=10)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        discord_id TEXT PRIMARY KEY,
        twitch_username TEXT,
        youtube_channel TEXT,
        twitch_id TEXT
    )
    """)

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

def ensure_users_has_twitch_id():
    conn = sqlite3.connect(config.DB_FILE, timeout=10)
    cur = conn.cursor()
    
    cur.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in cur.fetchall()]
    if "twitch_id" not in cols:
        try:
            cur.execute("ALTER TABLE users ADD COLUMN twitch_id TEXT")
            conn.commit()
            print("DB migration: added column users.twitch_id")
        except Exception as e:
            print("DB migration: failed to add twitch_id column:", e)
    conn.close()

def get_guild_settings(guild_id: int) -> dict:
    conn = sqlite3.connect(config.DB_FILE, timeout=10)
    cur = conn.cursor()
    cur.execute("""SELECT autoslow_enabled, check_frequency, time_configs, blacklisted_channels,
                   moderation_enabled, bad_words, banned_links, caps_threshold, spam_window, spam_threshold,
                   antiraid_enabled, join_threshold, join_window, min_account_age_days
                   FROM guild_settings WHERE guild_id = ?""", (str(guild_id),))
    row = cur.fetchone()
    conn.close()
    
    if not row:
        return {
            "autoslow_enabled": True,
            "check_frequency": config.DEFAULT_CHECK_FREQUENCY,
            "time_configs": config.DEFAULT_TIME_CONFIGS.copy(),
            "blacklisted_channels": [],
            "moderation_enabled": True,
            "bad_words": config.DEFAULT_BAD_WORDS.copy(),
            "banned_links": config.DEFAULT_BANNED_LINKS.copy(),
            "caps_threshold": config.DEFAULT_CAPS_THRESHOLD,
            "spam_window": config.DEFAULT_SPAM_WINDOW,
            "spam_threshold": config.DEFAULT_SPAM_THRESHOLD,
            "antiraid_enabled": False,
            "join_threshold": config.DEFAULT_JOIN_THRESHOLD,
            "join_window": config.DEFAULT_JOIN_WINDOW,
            "min_account_age_days": config.DEFAULT_ACCOUNT_AGE_DAYS
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
        "autoslow_enabled": bool(int(autoslow_enabled)),
        "check_frequency": int(check_frequency or config.DEFAULT_CHECK_FREQUENCY),
        "time_configs": _parse(time_configs_json, config.DEFAULT_TIME_CONFIGS.copy()),
        "blacklisted_channels": _parse(blacklisted_json, []),
        "moderation_enabled": bool(int(moderation_enabled)),
        "bad_words": _parse(bad_words_json, config.DEFAULT_BAD_WORDS.copy()),
        "banned_links": _parse(banned_links_json, config.DEFAULT_BANNED_LINKS.copy()),
        "caps_threshold": float(caps_threshold or config.DEFAULT_CAPS_THRESHOLD),
        "spam_window": int(spam_window or config.DEFAULT_SPAM_WINDOW),
        "spam_threshold": int(spam_threshold or config.DEFAULT_SPAM_THRESHOLD),
        "antiraid_enabled": bool(int(antiraid_enabled)),
        "join_threshold": int(join_threshold or config.DEFAULT_JOIN_THRESHOLD),
        "join_window": int(join_window or config.DEFAULT_JOIN_WINDOW),
        "min_account_age_days": int(min_account_age_days or config.DEFAULT_ACCOUNT_AGE_DAYS)
    }

def save_guild_settings(guild_id: int, settings: dict):
    conn = sqlite3.connect(config.DB_FILE, timeout=10)
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO guild_settings (
        guild_id, autoslow_enabled, check_frequency, time_configs, blacklisted_channels,
        moderation_enabled, bad_words, banned_links, caps_threshold,
        spam_window, spam_threshold, antiraid_enabled, join_threshold, join_window, min_account_age_days
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(guild_id),
        1 if settings.get("autoslow_enabled", True) else 0,
        int(settings.get("check_frequency", config.DEFAULT_CHECK_FREQUENCY)),
        json.dumps(settings.get("time_configs", config.DEFAULT_TIME_CONFIGS)),
        json.dumps(settings.get("blacklisted_channels", [])),
        1 if settings.get("moderation_enabled", True) else 0,
        json.dumps(settings.get("bad_words", config.DEFAULT_BAD_WORDS)),
        json.dumps(settings.get("banned_links", config.DEFAULT_BANNED_LINKS)),
        float(settings.get("caps_threshold", config.DEFAULT_CAPS_THRESHOLD)),
        int(settings.get("spam_window", config.DEFAULT_SPAM_WINDOW)),
        int(settings.get("spam_threshold", config.DEFAULT_SPAM_THRESHOLD)),
        1 if settings.get("antiraid_enabled", False) else 0,
        int(settings.get("join_threshold", config.DEFAULT_JOIN_THRESHOLD)),
        int(settings.get("join_window", config.DEFAULT_JOIN_WINDOW)),
        int(settings.get("min_account_age_days", config.DEFAULT_ACCOUNT_AGE_DAYS))
    ))
    conn.commit()
    conn.close()