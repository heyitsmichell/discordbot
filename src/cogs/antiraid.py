import discord
from discord import app_commands
from discord.ext import commands
import time
import datetime
from dotenv import load_dotenv
from collections import defaultdict, deque
from database import get_guild_settings, save_guild_settings
from utils.helpers import log_to_channel
import config

load_dotenv()

def role_check(*role_ids):
    """Check if user has any of the specified roles."""
    def predicate(ctx):
        return any(role.id in role_ids for role in ctx.author.roles)
    return commands.check(predicate)

class AntiRaid(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.join_logs = defaultdict(lambda: deque(maxlen=200))
    
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Handle member join events for anti-raid."""
        guild_id = member.guild.id
        settings = get_guild_settings(guild_id)
        now = time.time()
        self.join_logs[guild_id].append(now)

        # Account age enforcement
        min_age_days = settings.get("min_account_age_days", config.DEFAULT_ACCOUNT_AGE_DAYS)
        account_age_days = (discord.utils.utcnow() - member.created_at).days
        if account_age_days < min_age_days:
            try:
                until = discord.utils.utcnow() + datetime.timedelta(seconds=300)
                await member.edit(timed_out_until=until, reason="Account too new (anti-raid)")
                await log_to_channel(self.bot, f"⚠️ {member.mention} auto-timed out (account {account_age_days}d < {min_age_days}d).")
            except Exception:
                pass

        # Raid mode toggle
        if settings.get("antiraid_enabled", False):
            try:
                until = discord.utils.utcnow() + datetime.timedelta(seconds=600)
                await member.edit(timed_out_until=until, reason="Raid mode active")
                await log_to_channel(self.bot, f"🚨 {member.mention} auto-timed out (raid mode active).")
            except Exception:
                pass

        # Burst join detection
        join_window = settings.get("join_window", config.DEFAULT_JOIN_WINDOW)
        join_threshold = settings.get("join_threshold", config.DEFAULT_JOIN_THRESHOLD)
        joins_recent = [t for t in self.join_logs[guild_id] if now - t < join_window]

        if len(joins_recent) >= join_threshold:
            await log_to_channel(self.bot, f"🚨 Raid suspected: {len(joins_recent)} joins in {join_window}s in {member.guild.name}. Lockdown applied.")
            for ch in member.guild.text_channels:
                try:
                    await ch.edit(slowmode_delay=30, reason="Anti-raid triggered")
                except Exception:
                    pass
            await log_to_channel(self.bot, "⏱️ Auto-lockdown applied (30s slowmode).")
    
    @commands.command()
    @role_check(config.ADMIN_ROLE_ID, config.MOD_ROLE_ID)
    async def antiraid(self, ctx, action: str = None):
        """Toggle anti-raid mode."""
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

    def _check_mod_perms(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        if interaction.user.guild_permissions.administrator:
            return True
        user_roles = {role.id for role in interaction.user.roles}
        return config.ADMIN_ROLE_ID in user_roles or config.MOD_ROLE_ID in user_roles

    # ===================== SLASH COMMANDS =====================

    @app_commands.command(name="antiraid", description="Toggle anti-raid mode")
    @app_commands.describe(action="Enable, disable, or status")
    @app_commands.choices(action=[
        app_commands.Choice(name="Enable", value="enable"),
        app_commands.Choice(name="Disable", value="disable"),
        app_commands.Choice(name="Status", value="status")
    ])
    async def slash_antiraid(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        if not self._check_mod_perms(interaction):
            await interaction.response.send_message("❌ You need Administrator or Moderator permissions.", ephemeral=True)
            return
        settings = get_guild_settings(interaction.guild_id)
        if action.value == "enable":
            settings["antiraid_enabled"] = True
            save_guild_settings(interaction.guild_id, settings)
            await interaction.response.send_message("✅ Anti-raid mode enabled. New joins will be auto-timed out.")
        elif action.value == "disable":
            settings["antiraid_enabled"] = False
            save_guild_settings(interaction.guild_id, settings)
            await interaction.response.send_message("❌ Anti-raid mode disabled.")
        elif action.value == "status":
            state = "enabled" if settings.get("antiraid_enabled", False) else "disabled"
            await interaction.response.send_message(f"ℹ️ Anti-raid mode is currently **{state}**.")

async def setup(bot):
    await bot.add_cog(AntiRaid(bot))