import discord
from discord import app_commands
from discord.ext import commands
import logging
import os
import asyncio
import threading
from dotenv import load_dotenv
from database import init_db, ensure_users_has_twitch_id, get_guild_settings, save_guild_settings
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
        # 'cogs.twitch',
        # 'cogs.youtube',
        'cogs.lockdown',
        'cogs.admin',
        'cogs.timezone',
        # 'cogs.fun',
        'cogs.birthday',
        'cogs.ai',
        'cogs.music'
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
    
    try:
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        logging.error(f"Failed to sync slash commands: {e}")
    
    # global ban_queue
    # if ban_queue is not None:
    #     try:
    #         if not getattr(bot, "ban_worker_task", None) or bot.ban_worker_task.done():
    #             bot.ban_worker_task = bot.loop.create_task(ban_worker(bot))
    #             logging.info("Started ban_worker task.")
    #     except Exception as e:
    #         logging.exception("Failed to start ban_worker: %s", e)

def get_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🤖 Multi-Function Discord Bot Commands",
        description="Here are all available commands organized by category:",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🌍 Timezone",
        value=(
            "`/settime <city> <country>` – Set your local timezone\n"
            "`/mytime` – Show your current local time\n"
            "`/time @user` – Show another user's local time\n"
            "`/removetime` – Remove your timezone setting\n"
            "`/alltimes` – Show auto-updating live times embed"
        ),
        inline=False
    )

    embed.add_field(
        name="🎂 Birthday",
        value=(
            "`/setbirthday <day> <month>` – Set your birthday\n"
            "`/mybirthday` | `/birthday @user` – Show saved birthday\n"
            "`/removebirthday` – Remove your birthday setting\n"
            "`/allbirthdays` – Show upcoming birthdays embed"
        ),
        inline=False
    )

    embed.add_field(
        name="🤖 AI Chat",
        value=(
            "`/ask <question>` – Ask the AI assistant a question\n"
            "`@Bot <message>` – Mention the bot directly to chat"
        ),
        inline=False
    )

    embed.add_field(
        name="🎵 Music & Audio",
        value=(
            "`/join` | `/leave` – Join or leave your voice channel\n"
            "`/play <song/URL/query>` – Play uploaded song, YouTube link, or query\n"
            "`/uploadmusic <file> [title]` – Upload your own music file (`.mp3`, etc.)\n"
            "`/listmusic` | `/deletemusic <id>` – Browse or delete uploaded songs\n"
            "`/nowplaying` (`/np`) – Show current song with interactive controls\n"
            "`/queue` (`/q`) – Show upcoming songs waiting in line\n"
            "`/pause` | `/resume` – Pause or continue music playback\n"
            "`/skip` | `/stop` – Skip current track or stop playing\n"
            "`/loop [OFF/TRACK/QUEUE]` – Toggle loop mode\n"
            "`/volume <1-100>` – Adjust playback volume"
        ),
        inline=False
    )

    embed.add_field(
        name="🛡️ Moderation & Lockdown (Admin)",
        value=(
            "`/moderation action:<Enable/Disable>` – Toggle moderation system\n"
            "`/badword action:<Add/Remove/List> word:<word>` – Manage word filter\n"
            "`/bannedlink action:<Add/Remove/List> link:<link>` – Manage link filter\n"
            "`/unban <user_id>` – Unban a user by their ID\n"
            "`/lock1` | `/lock2` | `/lock3` | `/unlock` – Quick channel slowmode"
        ),
        inline=False
    )

    embed.add_field(
        name="⚙️ Auto-Slowmode & Anti-Raid (Admin)",
        value=(
            "`/autoslow action:<Enable/Disable/Status>` – Toggle auto-slowmode\n"
            "`/autoslow_blacklist action:<Add/Remove/List> channel:<#channel>` – Blacklist channel\n"
            "`/set_slowmode_thresholds <config>` – Configure thresholds\n"
            "`/set_check_frequency <seconds>` – Set evaluation frequency\n"
            "`/antiraid action:<Enable/Disable/Status>` – Toggle anti-raid mode"
        ),
        inline=False
    )

    embed.add_field(
        name="📋 Logging & Audit (Admin)",
        value=(
            "`/setlogchannel` | `/getlogchannel` | `/resetlogchannel` – Manage server logs"
        ),
        inline=False
    )

    embed.set_footer(text="Use /help anytime to view this guide.")
    return embed

@bot.tree.command(name="help", description="Show all available commands")
async def bot_help(interaction: discord.Interaction):
    await interaction.response.send_message(embed=get_help_embed(), ephemeral=True)

@bot.command(name="help")
async def prefix_help(ctx: commands.Context):
    await ctx.send(embed=get_help_embed())

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