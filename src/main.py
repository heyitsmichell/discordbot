import discord
from discord.ext import commands
import logging
import os
import asyncio
import threading
from dotenv import load_dotenv
from database import init_db, ensure_users_has_twitch_id
from utils.twitch_utils import ban_queue, ban_worker
from web_server import start_flask_server
import config

# Load environment variables
load_dotenv()

# Setup logging
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='a')
logging.basicConfig(level=logging.INFO, handlers=[handler])

# Bot setup
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix='/', intents=intents, help_command=None)

# Load cogs
async def load_extensions():
    cogs_list = [
        'cogs.moderation',
        'cogs.autoslowmode',
        'cogs.antiraid',
        'cogs.twitch',
        'cogs.youtube',
        'cogs.lockdown',
        'cogs.admin',
        'cogs.timezone',
        'cogs.fun'
        # 'cogs.autoban'
    ]
    
    for cog in cogs_list:
        try:
            await bot.load_extension(cog)
            logging.info(f"Loaded {cog}")
        except Exception as e:
            logging.error(f"Failed to load {cog}: {e}")

@bot.event
async def on_ready():
    logging.info(f"✅ {bot.user.name} is ready!")
    
    # Sync slash commands with Discord
    try:
        # Clear guild-specific commands (to remove duplicates from earlier testing)
        guild = discord.Object(id=1301470128004661268)
        bot.tree.clear_commands(guild=guild)
        await bot.tree.sync(guild=guild)
        
        # Sync global commands
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        logging.error(f"Failed to sync slash commands: {e}")
    
    # Start background tasks
    global ban_queue
    if ban_queue is not None:
        try:
            if not getattr(bot, "ban_worker_task", None) or bot.ban_worker_task.done():
                bot.ban_worker_task = bot.loop.create_task(ban_worker(bot))
                logging.info("Started ban_worker task.")
        except Exception as e:
            logging.exception("Failed to start ban_worker: %s", e)

@bot.command(name="help")
async def bot_help(ctx):
    help_text = (
        "**Available commands**\n\n"

        "**Public**\n"
        "/hello – Say hi (Feature will be removed)\n"
        "/linktwitch – Get Discord OAuth link in DM (viewer linking)\n"
        "/linktwitchstreamer – Get Twitch OAuth link in DM (streamer linking)\n"
        "/twitch <member> – Show linked Twitch (shows linked Twitch username)\n"
        "/unlinktwitch – Unlink your Twitch (Viewer)\n"
        "/unlinktwitchstreamer <twitch_id> – Unlink a streamer (Administrator)\n"
        "/gettwid <twitch_username> – Lookup Twitch numeric ID (meant for /subscribeban)\n\n"

        "**Timezone**\n"
        "/settime <city> <country> – Set your timezone\n"
        "/mytime – Show your current local time\n"
        "/time @user – Show another user's local time\n"
        "/removetime – Remove your timezone setting\n"
        "/alltimes – Show auto-updating embed with all times\n\n"

        "**Lookup (Administrator)**\n"
        "/twitchusers – List all users with linked Twitch account\n"
        "/youtubeusers – List all users with linked YouTube account\n\n"

        "**Twitch EventSub / Subscription (Administrator / Streamer)**\n"
        "/subscribeban <twitch_id> – Subscribe this server (via linked streamer) to ban events\n"
        "/unsubscribeban <subscription_id> – Unsubscribe an EventSub subscription\n"
        "/listsubs – List active EventSub subscriptions\n\n"

        "**Lockdown / Slowmode (Administrator)**\n"
        "/lock1 – Set 15s slowmode on all text channels\n"
        "/lock2 – Set 30s slowmode on all text channels\n"
        "/lock3 – Set 60s slowmode on all text channels\n"
        "/unlock – Remove slowmode on all text channels\n\n"

        "**Auto-slowmode (Administrator)**\n"
        "/autoslow enable|disable|status – Toggle auto-slowmode\n"
        "/autoslow_blacklist add|remove|list #channel – Manage auto-slowmode blacklist\n"
        "/set_slowmode_thresholds 50:30,20:15,10:5,0:0 – Configure thresholds\n"
        "/set_check_frequency <seconds> – How often to evaluate channel message counts\n\n"

        "**Moderation (Administrator)**\n"
        "/moderation enable|disable\n"
        "/badword add|remove|list <word>\n"
        "/bannedlink add|remove|list <link>\n"
        "/unban <user_id> – Unban a user via their ID\n\n"

        "**Anti-Raid (Administrator)**\n"
        "/antiraid enable|disable|status – Toggle raid mode\n\n"

        "**Logging (Administrator)**\n"
        "/setlogchannel #channel – Set global log channel (in-memory or persisted)\n"
        "/getlogchannel – Show current global log channel\n"
        "/resetlogchannel – Reset global log channel\n\n"
    )
    await ctx.send(help_text)

@bot.command()
async def hello(ctx):
    await ctx.send(f"Hello {ctx.author.mention}!")

async def main():
    async with bot:
        init_db()
        ensure_users_has_twitch_id()
        start_flask_server()
        await load_extensions()
        await bot.start(config.TOKEN)

if __name__ == "__main__":
    if not config.TOKEN:
        print("ERROR: DISCORD_TOKEN not set in environment.")
    else:
        asyncio.run(main())