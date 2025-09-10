import discord
from discord.ext import commands
import time
import datetime
from collections import defaultdict, deque
from database import get_guild_settings, save_guild_settings
from utils.helpers import log_to_channel
import config

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
    @commands.has_permissions(administrator=True)
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

async def setup(bot):
    await bot.add_cog(AntiRaid(bot))