import discord
from discord.ext import commands
import time
import asyncio
from database import get_guild_settings, save_guild_settings
from utils.helpers import log_to_channel
import config

class AutoSlowmode(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.message_cache = {}
        self.previous_delays = {}
        self.last_updated = 0
        self.update_lock = asyncio.Lock()
    
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        
        guild = message.guild
        if not guild:
            return
            
        guild_settings = get_guild_settings(guild.id)
        if guild_settings and guild_settings.get("autoslow_enabled", True):
            ch_id = message.channel.id
            bl = guild_settings.get("blacklisted_channels", [])
            if ch_id in bl:
                return
            
            self.message_cache[ch_id] = self.message_cache.get(ch_id, 0) + 1
            if time.time() >= self.last_updated + guild_settings.get("check_frequency", config.DEFAULT_CHECK_FREQUENCY):
                if not self.update_lock.locked():
                    self.bot.loop.create_task(self.update_slowmode_batched())
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def autoslow(self, ctx, action: str = None):
        """Enable, disable, or check status of auto-slowmode."""
        settings = get_guild_settings(ctx.guild.id)
        if action == "enable":
            settings["autoslow_enabled"] = True
            save_guild_settings(ctx.guild.id, settings)
            await ctx.send("✅ Auto-slowmode enabled.")
        elif action == "disable":
            settings["autoslow_enabled"] = False
            save_guild_settings(ctx.guild.id, settings)
            await ctx.send("❌ Auto-slowmode disabled.")
        elif action == "status":
            await ctx.send(f"Auto-slowmode is {'enabled' if settings['autoslow_enabled'] else 'disabled'}.")
        else:
            await ctx.send("Usage: /autoslow enable|disable|status")
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def autoslow_blacklist(self, ctx, action: str = None, channel: discord.TextChannel = None):
        """Manage auto-slowmode blacklist."""
        settings = get_guild_settings(ctx.guild.id)
        bl = settings.get("blacklisted_channels", [])
        if action == "add" and channel:
            if channel.id not in bl: 
                bl.append(channel.id)
            settings["blacklisted_channels"] = bl
            save_guild_settings(ctx.guild.id, settings)
            await ctx.send(f"✅ Added {channel.mention} to auto-slowmode blacklist.")
        elif action == "remove" and channel:
            if channel.id in bl: 
                bl.remove(channel.id)
            settings["blacklisted_channels"] = bl
            save_guild_settings(ctx.guild.id, settings)
            await ctx.send(f"❌ Removed {channel.mention} from auto-slowmode blacklist.")
        elif action == "list":
            if not bl: 
                await ctx.send("Blacklist is empty.")
            else: 
                await ctx.send("Blacklisted: " + ", ".join(f"<#{c}>" for c in bl))
        else:
            await ctx.send("Usage: /autoslow_blacklist add|remove|list #channel")
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def set_slowmode_thresholds(self, ctx, *, thresholds: str):
        """Configure slowmode thresholds."""
        try:
            pairs = thresholds.split(",")
            configs = {}
            for pair in pairs:
                limit, delay = pair.split(":")
                configs[int(limit.strip())] = int(delay.strip())
            settings = get_guild_settings(ctx.guild.id)
            settings["time_configs"] = configs
            save_guild_settings(ctx.guild.id, settings)
            await ctx.send(f"✅ Thresholds updated: {configs}")
        except Exception as e:
            await ctx.send(f"Error parsing thresholds: {e}")
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def set_check_frequency(self, ctx, seconds: int):
        """Set check frequency for auto-slowmode."""
        settings = get_guild_settings(ctx.guild.id)
        settings["check_frequency"] = seconds
        save_guild_settings(ctx.guild.id, settings)
        await ctx.send(f"✅ Check frequency set to {seconds} seconds.")
    
    async def update_slowmode_batched(self):
        """Update slowmode for channels in batch."""
        async with self.update_lock:
            if not self.message_cache:
                self.last_updated = time.time()
                return
            
            changes = []
            for channel_id, msg_count in list(self.message_cache.items()):
                ch = self.bot.get_channel(channel_id)
                if not ch or not isinstance(ch, discord.TextChannel):
                    continue
                
                guild_id = ch.guild.id
                settings = get_guild_settings(guild_id)
                if not settings.get("autoslow_enabled", True):
                    continue
                
                bl = settings.get("blacklisted_channels", [])
                if channel_id in bl:
                    continue
                
                configs = settings.get("time_configs", config.DEFAULT_TIME_CONFIGS)
                parsed_configs = {int(k): int(v) for k, v in configs.items()}
                delay = 0
                for limit in sorted(parsed_configs.keys(), reverse=True):
                    if msg_count >= limit:
                        delay = parsed_configs[limit]
                        break
                
                prev = self.previous_delays.get(channel_id, None)
                if prev != delay:
                    changes.append((ch, delay, msg_count))
            
            if not changes:
                self.message_cache = {}
                self.last_updated = time.time()
                return
            
            for channel_obj, delay, msg_count in changes:
                try:
                    await channel_obj.edit(slowmode_delay=delay, reason="Auto slowmode adjustment")
                    self.previous_delays[channel_obj.id] = delay
                    await log_to_channel(self.bot, f"⏱️ Set slowmode for #{channel_obj.name} to {delay}s (messages: {msg_count})")
                except Exception as e:
                    await log_to_channel(self.bot, f"⚠️ Failed to set slowmode for #{channel_obj.name}: {e}")
                await asyncio.sleep(config.SLOWMODE_EDIT_DELAY)
            
            self.message_cache = {}
            self.last_updated = time.time()

async def setup(bot):
    await bot.add_cog(AutoSlowmode(bot))