import os
import json
from dotenv import load_dotenv
from supabase import create_client, Client
import config

load_dotenv()
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

def init_db():
    try:
        supabase.table("guild_settings").select("guild_id").limit(1).execute()
        print("Connected to Supabase successfully.")
    except Exception as e:
        print(f"Error connecting to Supabase: {e}")

def ensure_users_has_twitch_id():
    # Legacy migration function 
    pass

def get_guild_settings(guild_id: int) -> dict:
    try:
        response = supabase.table("guild_settings").select("*").eq("guild_id", str(guild_id)).execute()
        data = response.data
    except Exception as e:
        print(f"Error fetching guild settings: {e}")
        data = []

    if not data:
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

    row = data[0]

    def _parse(j, default):
        try:
            if isinstance(j, (dict, list)):
                return j
            return json.loads(j) if j else default
        except Exception:
            return default

    return {
        "autoslow_enabled": bool(row.get("autoslow_enabled", 1)),
        "check_frequency": int(row.get("check_frequency") or config.DEFAULT_CHECK_FREQUENCY),
        "time_configs": _parse(row.get("time_configs"), config.DEFAULT_TIME_CONFIGS.copy()),
        "blacklisted_channels": _parse(row.get("blacklisted_channels"), []),
        "moderation_enabled": bool(row.get("moderation_enabled", 1)),
        "bad_words": _parse(row.get("bad_words"), config.DEFAULT_BAD_WORDS.copy()),
        "banned_links": _parse(row.get("banned_links"), config.DEFAULT_BANNED_LINKS.copy()),
        "caps_threshold": float(row.get("caps_threshold") or config.DEFAULT_CAPS_THRESHOLD),
        "spam_window": int(row.get("spam_window") or config.DEFAULT_SPAM_WINDOW),
        "spam_threshold": int(row.get("spam_threshold") or config.DEFAULT_SPAM_THRESHOLD),
        "antiraid_enabled": bool(row.get("antiraid_enabled", 0)),
        "join_threshold": int(row.get("join_threshold") or config.DEFAULT_JOIN_THRESHOLD),
        "join_window": int(row.get("join_window") or config.DEFAULT_JOIN_WINDOW),
        "min_account_age_days": int(row.get("min_account_age_days") or config.DEFAULT_ACCOUNT_AGE_DAYS)
    }

def save_guild_settings(guild_id: int, settings: dict):
    data_to_insert = {
        "guild_id": str(guild_id),
        "autoslow_enabled": 1 if settings.get("autoslow_enabled", True) else 0,
        "check_frequency": int(settings.get("check_frequency", config.DEFAULT_CHECK_FREQUENCY)),
        "time_configs": json.dumps(settings.get("time_configs", config.DEFAULT_TIME_CONFIGS)),
        "blacklisted_channels": json.dumps(settings.get("blacklisted_channels", [])),
        "moderation_enabled": 1 if settings.get("moderation_enabled", True) else 0,
        "bad_words": json.dumps(settings.get("bad_words", config.DEFAULT_BAD_WORDS)),
        "banned_links": json.dumps(settings.get("banned_links", config.DEFAULT_BANNED_LINKS)),
        "caps_threshold": float(settings.get("caps_threshold", config.DEFAULT_CAPS_THRESHOLD)),
        "spam_window": int(settings.get("spam_window", config.DEFAULT_SPAM_WINDOW)),
        "spam_threshold": int(settings.get("spam_threshold", config.DEFAULT_SPAM_THRESHOLD)),
        "antiraid_enabled": 1 if settings.get("antiraid_enabled", False) else 0,
        "join_threshold": int(settings.get("join_threshold", config.DEFAULT_JOIN_THRESHOLD)),
        "join_window": int(settings.get("join_window", config.DEFAULT_JOIN_WINDOW)),
        "min_account_age_days": int(settings.get("min_account_age_days", config.DEFAULT_ACCOUNT_AGE_DAYS))
    }

    try:
        supabase.table("guild_settings").upsert(data_to_insert).execute()
    except Exception as e:
        print(f"Error saving guild settings: {e}")


# ==================== Users Table Functions ====================

def get_user(discord_id: str) -> dict | None:
    """Get a user by Discord ID."""
    try:
        response = supabase.table("users").select("*").eq("discord_id", str(discord_id)).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error fetching user: {e}")
        return None

def get_all_users_with_twitch() -> list:
    """Get all users with linked Twitch accounts."""
    try:
        response = supabase.table("users").select("discord_id, twitch_username").not_.is_("twitch_username", "null").execute()
        return response.data or []
    except Exception as e:
        print(f"Error fetching Twitch users: {e}")
        return []

def get_all_users_with_youtube() -> list:
    """Get all users with linked YouTube accounts."""
    try:
        response = supabase.table("users").select("discord_id, youtube_channel").not_.is_("youtube_channel", "null").execute()
        return response.data or []
    except Exception as e:
        print(f"Error fetching YouTube users: {e}")
        return []

def get_all_twitch_ids() -> list:
    """Get all distinct twitch_ids from users table."""
    try:
        response = supabase.table("users").select("twitch_id").not_.is_("twitch_id", "null").execute()
        return [r["twitch_id"] for r in response.data if r.get("twitch_id")]
    except Exception as e:
        print(f"Error fetching Twitch IDs: {e}")
        return []

def upsert_user(discord_id: str, twitch_username: str = None, youtube_channel: str = None, twitch_id: str = None):
    """Insert or update a user."""
    try:
        # First get existing data to preserve fields not being updated
        existing = get_user(discord_id)
        
        data = {"discord_id": str(discord_id)}
        if twitch_username is not None:
            data["twitch_username"] = twitch_username
        elif existing and existing.get("twitch_username"):
            data["twitch_username"] = existing["twitch_username"]
            
        if youtube_channel is not None:
            data["youtube_channel"] = youtube_channel
        elif existing and existing.get("youtube_channel"):
            data["youtube_channel"] = existing["youtube_channel"]
            
        if twitch_id is not None:
            data["twitch_id"] = twitch_id
        elif existing and existing.get("twitch_id"):
            data["twitch_id"] = existing["twitch_id"]
        
        supabase.table("users").upsert(data).execute()
    except Exception as e:
        print(f"Error upserting user: {e}")

def update_user_twitch(discord_id: str, twitch_username: str = None, twitch_id: str = None):
    """Update Twitch fields for a user."""
    try:
        data = {}
        if twitch_username is not None:
            data["twitch_username"] = twitch_username
        if twitch_id is not None:
            data["twitch_id"] = twitch_id
        
        if data:
            supabase.table("users").update(data).eq("discord_id", str(discord_id)).execute()
    except Exception as e:
        print(f"Error updating user Twitch: {e}")

def update_twitch_username_by_id(twitch_id: str, twitch_username: str):
    """Update twitch_username for all users with a given twitch_id."""
    try:
        supabase.table("users").update({"twitch_username": twitch_username}).eq("twitch_id", twitch_id).execute()
        return True
    except Exception as e:
        print(f"Error updating Twitch username by ID: {e}")
        return False

def clear_user_twitch(discord_id: str):
    """Clear Twitch fields for a user."""
    try:
        supabase.table("users").update({"twitch_username": None, "twitch_id": None}).eq("discord_id", str(discord_id)).execute()
    except Exception as e:
        print(f"Error clearing user Twitch: {e}")

def clear_user_youtube(discord_id: str):
    """Clear YouTube field for a user."""
    try:
        supabase.table("users").update({"youtube_channel": None}).eq("discord_id", str(discord_id)).execute()
    except Exception as e:
        print(f"Error clearing user YouTube: {e}")


# ==================== Streamers Table Functions ====================

def get_streamer(discord_id: str) -> dict | None:
    """Get a streamer by Discord ID."""
    try:
        response = supabase.table("streamers").select("*").eq("discord_id", str(discord_id)).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error fetching streamer: {e}")
        return None

def get_streamer_by_twitch_id(twitch_id: str) -> dict | None:
    """Get a streamer by Twitch ID."""
    try:
        response = supabase.table("streamers").select("*").eq("twitch_id", str(twitch_id)).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error fetching streamer by Twitch ID: {e}")
        return None

def upsert_streamer(discord_id: str, twitch_id: str, twitch_username: str, access_token: str, refresh_token: str):
    """Insert or update a streamer."""
    try:
        data = {
            "discord_id": str(discord_id),
            "twitch_id": twitch_id,
            "twitch_username": twitch_username,
            "access_token": access_token,
            "refresh_token": refresh_token
        }
        supabase.table("streamers").upsert(data).execute()
    except Exception as e:
        print(f"Error upserting streamer: {e}")

def delete_streamer_by_twitch_id(twitch_id: str) -> str | None:
    """Delete a streamer by Twitch ID and return the discord_id."""
    try:
        response = supabase.table("streamers").select("discord_id").eq("twitch_id", str(twitch_id)).execute()
        if response.data:
            discord_id = response.data[0]["discord_id"]
            supabase.table("streamers").delete().eq("twitch_id", str(twitch_id)).execute()
            return discord_id
        return None
    except Exception as e:
        print(f"Error deleting streamer by Twitch ID: {e}")
        return None

def delete_streamer_by_discord_id(discord_id: str) -> str | None:
    """Delete a streamer by Discord ID and return the twitch_id."""
    try:
        response = supabase.table("streamers").select("twitch_id").eq("discord_id", str(discord_id)).execute()
        if response.data:
            twitch_id = response.data[0]["twitch_id"]
            supabase.table("streamers").delete().eq("discord_id", str(discord_id)).execute()
            return twitch_id
        return None
    except Exception as e:
        print(f"Error deleting streamer by Discord ID: {e}")
        return None

def update_streamer_tokens(discord_id: str, access_token: str, refresh_token: str):
    """Update OAuth tokens for a streamer."""
    try:
        supabase.table("streamers").update({
            "access_token": access_token,
            "refresh_token": refresh_token
        }).eq("discord_id", str(discord_id)).execute()
    except Exception as e:
        print(f"Error updating streamer tokens: {e}")


# ==================== Discord ID Lookup Functions ====================

def get_discord_ids_by_twitch(twitch_identifier: str) -> list:
    """Get Discord IDs from Twitch identifier (ID or username)."""
    if not twitch_identifier:
        return []
    
    discord_ids = []
    
    try:
        # Check if it's a numeric ID
        if str(twitch_identifier).isdigit():
            # Search by twitch_id in streamers
            response = supabase.table("streamers").select("discord_id").eq("twitch_id", str(twitch_identifier)).execute()
            discord_ids.extend([r["discord_id"] for r in response.data if r.get("discord_id")])
            
            # Search by twitch_id in users
            response = supabase.table("users").select("discord_id").eq("twitch_id", str(twitch_identifier)).execute()
            discord_ids.extend([r["discord_id"] for r in response.data if r.get("discord_id")])
        
        # If no results, search by username (case-insensitive)
        if not discord_ids:
            # Search in users
            response = supabase.table("users").select("discord_id").ilike("twitch_username", str(twitch_identifier)).execute()
            discord_ids.extend([r["discord_id"] for r in response.data if r.get("discord_id")])
            
            # Search in streamers
            response = supabase.table("streamers").select("discord_id").ilike("twitch_username", str(twitch_identifier)).execute()
            discord_ids.extend([r["discord_id"] for r in response.data if r.get("discord_id")])
    
    except Exception as e:
        print(f"Error looking up Discord IDs by Twitch: {e}")
    
    # Return unique IDs
    seen = set()
    return [d for d in discord_ids if not (d in seen or seen.add(d))]


# ==================== User Timezone Functions ====================

def get_user_timezone(discord_id: str) -> dict | None:
    """Get a user's timezone info."""
    try:
        response = supabase.table("user_timezones").select("*").eq("discord_id", str(discord_id)).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error fetching user timezone: {e}")
        return None

def set_user_timezone(discord_id: str, city: str, country: str, timezone: str, country_code: str = None):
    """Set a user's timezone."""
    try:
        data = {
            "discord_id": str(discord_id),
            "city": city,
            "country": country,
            "timezone": timezone,
            "country_code": country_code or ""
        }
        supabase.table("user_timezones").upsert(data).execute()
        return True
    except Exception as e:
        print(f"Error setting user timezone: {e}")
        return False

def remove_user_timezone(discord_id: str) -> bool:
    """Remove a user's timezone."""
    try:
        supabase.table("user_timezones").delete().eq("discord_id", str(discord_id)).execute()
        return True
    except Exception as e:
        print(f"Error removing user timezone: {e}")
        return False

def get_all_user_timezones() -> list:
    """Get all users with timezones set."""
    try:
        response = supabase.table("user_timezones").select("*").execute()
        return response.data or []
    except Exception as e:
        print(f"Error fetching all user timezones: {e}")
        return []


# ==================== Timezone Embed Tracking Functions ====================

def save_timezone_embed(guild_id: str, channel_id: str, message_id: str, page: int = 0):
    """Save a timezone embed for tracking (persists across restarts)."""
    try:
        data = {
            "guild_id": str(guild_id),
            "channel_id": str(channel_id),
            "message_id": str(message_id),
            "page": page
        }
        supabase.table("timezone_embeds").upsert(data).execute()
        return True
    except Exception as e:
        print(f"Error saving timezone embed: {e}")
        return False

def update_timezone_embed_page(guild_id: str, page: int):
    """Update the page number for a timezone embed."""
    try:
        supabase.table("timezone_embeds").update({"page": page}).eq("guild_id", str(guild_id)).execute()
        return True
    except Exception as e:
        print(f"Error updating timezone embed page: {e}")
        return False

def remove_timezone_embed(guild_id: str):
    """Remove a timezone embed from tracking."""
    try:
        supabase.table("timezone_embeds").delete().eq("guild_id", str(guild_id)).execute()
        return True
    except Exception as e:
        print(f"Error removing timezone embed: {e}")
        return False

def get_all_timezone_embeds() -> list:
    """Get all tracked timezone embeds."""
    try:
        response = supabase.table("timezone_embeds").select("*").execute()
        return response.data or []
    except Exception as e:
        print(f"Error fetching timezone embeds: {e}")
        return []


# ==================== User Birthday Functions ====================

def get_user_birthday(discord_id: str) -> dict | None:
    """Get a user's birthday info."""
    try:
        response = supabase.table("user_birthdays").select("*").eq("discord_id", str(discord_id)).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error fetching user birthday: {e}")
        return None

def set_user_birthday(discord_id: str, display_name: str, day: int, month: int) -> bool:
    """Set a user's birthday."""
    try:
        data = {
            "discord_id": str(discord_id),
            "display_name": display_name,
            "day": day,
            "month": month
        }
        supabase.table("user_birthdays").upsert(data).execute()
        return True
    except Exception as e:
        print(f"Error setting user birthday: {e}")
        return False

def remove_user_birthday(discord_id: str) -> bool:
    """Remove a user's birthday."""
    try:
        supabase.table("user_birthdays").delete().eq("discord_id", str(discord_id)).execute()
        return True
    except Exception as e:
        print(f"Error removing user birthday: {e}")
        return False

def get_all_user_birthdays() -> list:
    """Get all users with birthdays set."""
    try:
        response = supabase.table("user_birthdays").select("*").execute()
        return response.data or []
    except Exception as e:
        print(f"Error fetching all user birthdays: {e}")
        return []


# ==================== Birthday Embed Tracking Functions ====================

def save_birthday_embed(guild_id: str, channel_id: str, message_id: str, page: int = 0):
    """Save a birthday embed for tracking (persists across restarts)."""
    try:
        data = {
            "guild_id": str(guild_id),
            "channel_id": str(channel_id),
            "message_id": str(message_id),
            "page": page
        }
        supabase.table("birthday_embeds").upsert(data).execute()
        return True
    except Exception as e:
        print(f"Error saving birthday embed: {e}")
        return False

def update_birthday_embed_page(guild_id: str, page: int):
    """Update the page number for a birthday embed."""
    try:
        supabase.table("birthday_embeds").update({"page": page}).eq("guild_id", str(guild_id)).execute()
        return True
    except Exception as e:
        print(f"Error updating birthday embed page: {e}")
        return False

def remove_birthday_embed(guild_id: str):
    """Remove a birthday embed from tracking."""
    try:
        supabase.table("birthday_embeds").delete().eq("guild_id", str(guild_id)).execute()
        return True
    except Exception as e:
        print(f"Error removing birthday embed: {e}")
        return False

def get_all_birthday_embeds() -> list:
    """Get all tracked birthday embeds."""
    try:
        response = supabase.table("birthday_embeds").select("*").execute()
        return response.data or []
    except Exception as e:
        print(f"Error fetching birthday embeds: {e}")
        return []