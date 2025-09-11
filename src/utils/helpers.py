import discord
import config

async def log_to_channel(bot, message):
    """Log message to configured channel."""
    if config.LOG_CHANNEL_ID:
        try:
            channel = bot.get_channel(config.LOG_CHANNEL_ID)
            if channel:
                await channel.send(message)
        except Exception:
            pass

