import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select
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

# Setup logging - output to both file and console (for Render visibility)
file_handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='a')
stream_handler = logging.StreamHandler()
logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])

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
            print(f"✅ Loaded {cog}", flush=True)
        except Exception as e:
            logging.error(f"Failed to load {cog}: {e}")
            print(f"❌ Failed to load {cog}: {e}", flush=True)
            import traceback
            traceback.print_exc()

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

class HelpDropdown(discord.ui.Select):
    def __init__(self, current_category: str = "overview"):
        options = [
            discord.SelectOption(
                label="Overview",
                value="overview",
                description="General categories & quick summary",
                default=(current_category == "overview"),
                emoji="🏠"
            ),
            discord.SelectOption(
                label="Music & Audio",
                value="music",
                description="Playback, Queue, and Song Upload controls",
                default=(current_category == "music"),
                emoji="🎵"
            ),
            discord.SelectOption(
                label="Timezone & Birthday",
                value="time_bday",
                description="Local time tracking and birthday celebrations",
                default=(current_category == "time_bday"),
                emoji="🌍"
            ),
            discord.SelectOption(
                label="Moderation & Slowmode",
                value="admin",
                description="Admin tools, Anti-Raid, and Auto-Slowmode",
                default=(current_category == "admin"),
                emoji="🛡️"
            ),
            discord.SelectOption(
                label="AI & Utility",
                value="ai_util",
                description="AI Assistant, logging, and utilities",
                default=(current_category == "ai_util"),
                emoji="🤖"
            ),
        ]
        super().__init__(placeholder="Select a category to view detailed commands...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        embed = get_help_embed(selected)
        view = HelpView(selected)
        await interaction.response.edit_message(embed=embed, view=view)


class HelpView(discord.ui.View):
    def __init__(self, current_category: str = "overview"):
        super().__init__(timeout=300)
        self.add_item(HelpDropdown(current_category))


def get_help_embed(category: str = "overview") -> discord.Embed:
    if category == "music":
        embed = discord.Embed(
            title="🎵 Music & Audio Guide",
            description="High-fidelity Pure Opus audio playback, custom library uploads, and queue management.\nSelect a category from the dropdown below to explore other commands!",
            color=discord.Color.green()
        )
        embed.add_field(
            name="▶️ Playback & Voice Controls",
            value=(
                "`/join` | `/leave` – Join or leave your voice channel\n"
                "`/play <song/URL/query> [private:True]` – Play local song, YouTube, or query\n"
                "`/nowplaying` (`/np`) – Show current song with interactive buttons\n"
                "`/pause` | `/resume` – Pause or resume music playback\n"
                "`/skip` | `/stop` – Skip the current track or stop playback\n"
                "`/volume <1-100>` – Adjust bot audio volume"
            ),
            inline=False
        )
        embed.add_field(
            name="📑 Queue & Loop Management",
            value=(
                "`/queue` (`/q`) – Show upcoming tracks waiting in line\n"
                "`/shuffle` (`/shuf`) – Randomize all upcoming tracks\n"
                "`/remove <position>` – Remove a specific song from the queue\n"
                "`/loop [OFF/TRACK/QUEUE]` – Toggle loop mode for track or full queue"
            ),
            inline=False
        )
        embed.add_field(
            name="📂 Custom Song Uploads & Library",
            value=(
                "`/uploadmusic <attachment> [title] [private:True]` – Upload your own audio file (`.mp3`, `.wav`, `.flac`, `.ogg`)\n"
                "`/renamemusic <id_or_title> <new_title>` – Rename any song in the library\n"
                "`/listmusic [private_only:True]` – Browse available public or your private songs\n"
                "`/toggleprivacy <id_or_title>` – Toggle your track between Public and Private\n"
                "`/deletemusic <id_or_title>` – Permanently delete your uploaded track"
            ),
            inline=False
        )
    elif category == "time_bday":
        embed = discord.Embed(
            title="🌍 Timezone & Birthday Guide",
            description="Track local times and celebrate member birthdays automatically.\nSelect a category from the dropdown below to switch views!",
            color=discord.Color.gold()
        )
        embed.add_field(
            name="🌍 Timezone Commands",
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
            name="🎂 Birthday Commands",
            value=(
                "`/setbirthday <day> <month>` – Set your birthday\n"
                "`/mybirthday` | `/birthday @user` – Show saved birthday\n"
                "`/removebirthday` – Remove your birthday setting\n"
                "`/allbirthdays` – Show upcoming birthdays embed"
            ),
            inline=False
        )
    elif category == "admin":
        embed = discord.Embed(
            title="🛡️ Moderation & Lockdown Guide (Admin)",
            description="Automated profanity/link filtering, anti-raid protection, and quick lockdowns.\nSelect a category from the dropdown below to switch views!",
            color=discord.Color.red()
        )
        embed.add_field(
            name="🛡️ Moderation & Filter",
            value=(
                "`/moderation action:<Enable/Disable>` – Toggle chat moderation system\n"
                "`/badword action:<Add/Remove/List> word:<word>` – Manage word filter\n"
                "`/bannedlink action:<Add/Remove/List> link:<link>` – Manage link filter\n"
                "`/unban <user_id>` – Unban a user by their Discord ID"
            ),
            inline=False
        )
        embed.add_field(
            name="🔒 Quick Channel Lockdown",
            value=(
                "`/lock1` (10s) | `/lock2` (30s) | `/lock3` (60s) – Apply channel slowmode\n"
                "`/unlock` – Remove slowmode and restore normal chat speed"
            ),
            inline=False
        )
        embed.add_field(
            name="⚙️ Auto-Slowmode & Anti-Raid",
            value=(
                "`/autoslow action:<Enable/Disable/Status>` – Toggle dynamic slowmode\n"
                "`/autoslow_blacklist action:<Add/Remove/List> channel:<#channel>` – Blacklist channel\n"
                "`/set_slowmode_thresholds <config>` – Configure traffic thresholds\n"
                "`/set_check_frequency <seconds>` – Set evaluation interval\n"
                "`/antiraid action:<Enable/Disable/Status>` – Toggle anti-raid emergency mode"
            ),
            inline=False
        )
    elif category == "ai_util":
        embed = discord.Embed(
            title="🤖 AI Assistant & Utility Guide",
            description="Gemini AI chat assistant, server logging, and basic bot utilities.\nSelect a category from the dropdown below to switch views!",
            color=discord.Color.blurple()
        )
        embed.add_field(
            name="🤖 AI Chat Assistant",
            value=(
                "`/ask <question>` – Ask the AI assistant any question\n"
                "`@Bot <message>` – Mention the bot directly in chat to converse naturally"
            ),
            inline=False
        )
        embed.add_field(
            name="📋 Server Logging & Audit (Admin)",
            value=(
                "`/setlogchannel` – Set the channel for bot audit & moderation logs\n"
                "`/getlogchannel` – Check current configured log channel\n"
                "`/resetlogchannel` – Clear and disable server log output"
            ),
            inline=False
        )
        embed.add_field(
            name="🔧 Utility Commands",
            value=(
                "`/hello` | `!hello` – Test if bot is responding and get a greeting\n"
                "`/help` | `!help` – Open this interactive command guide"
            ),
            inline=False
        )
    else:
        # Overview (Default)
        embed = discord.Embed(
            title="🤖 Multi-Function Discord Bot Commands",
            description="Welcome! Use the **interactive dropdown menu below** to browse commands cleanly by category:",
            color=discord.Color.blurple()
        )
        embed.add_field(
            name="🎵 Music & Audio",
            value="High-fidelity Opus audio, `/play`, `/queue`, and custom `/uploadmusic` library.\n👉 **Select `🎵 Music & Audio` below for all 15+ music commands!**",
            inline=False
        )
        embed.add_field(
            name="🌍 Timezone & Birthday",
            value="Track live world times (`/alltimes`) and celebrate member birthdays (`/allbirthdays`).\n👉 **Select `🌍 Timezone & Birthday` below for details!**",
            inline=False
        )
        embed.add_field(
            name="🛡️ Moderation & Slowmode",
            value="Automated filters (`/badword`, `/bannedlink`), quick lockdowns (`/lock1`), and Anti-Raid.\n👉 **Select `🛡️ Moderation & Slowmode` below for Admin guide!**",
            inline=False
        )
        embed.add_field(
            name="🤖 AI & Utility",
            value="Ask questions with `/ask` or `@Bot`, and configure server logging (`/setlogchannel`).\n👉 **Select `🤖 AI & Utility` below for more!**",
            inline=False
        )
    embed.set_footer(text="Use the dropdown select menu below to switch categories anytime.")
    return embed

@bot.tree.command(name="help", description="Show all available commands")
async def bot_help(interaction: discord.Interaction):
    await interaction.response.send_message(embed=get_help_embed("overview"), view=HelpView("overview"), ephemeral=True)

@bot.command(name="help")
async def prefix_help(ctx: commands.Context):
    await ctx.send(embed=get_help_embed("overview"), view=HelpView("overview"))

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