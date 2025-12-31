import discord
from discord.ext import commands
import time
import asyncio
from database import get_guild_settings, save_guild_settings
from utils.helpers import log_to_channel
from dotenv import load_dotenv
import config

load_dotenv()

def role_check(*role_ids):
    """Check if user has any of the specified roles."""
    def predicate(ctx):
        return any(role.id in role_ids for role in ctx.author.roles)
    return commands.check(predicate)
class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_message_logs = {}
        # Track reactions: key = (channel_id, message_id, user_id, emoji_str), value = timestamp
        self.reaction_timestamps = {}
    
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Track when a user adds a reaction in the watched channel."""
        # Only track in the specified channel
        if not config.REACTION_WATCH_CHANNEL_ID or payload.channel_id != config.REACTION_WATCH_CHANNEL_ID:
            return
        
        # Ignore bot reactions
        if payload.user_id == self.bot.user.id:
            return
        
        # Store the timestamp for this reaction
        key = (payload.channel_id, payload.message_id, payload.user_id, str(payload.emoji))
        self.reaction_timestamps[key] = time.time()
    
    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """Detect when a user removes a reaction within 1 second of adding it."""
        # Only track in the specified channel
        if not config.REACTION_WATCH_CHANNEL_ID or payload.channel_id != config.REACTION_WATCH_CHANNEL_ID:
            return
        
        # Ignore bot reactions
        if payload.user_id == self.bot.user.id:
            return
        
        key = (payload.channel_id, payload.message_id, payload.user_id, str(payload.emoji))
        add_time = self.reaction_timestamps.pop(key, None)
        
        if add_time is None:
            return
        
        # Check if reaction was removed within 1 second
        elapsed = time.time() - add_time
        if elapsed <= 1.0:
            await self._log_quick_reaction(payload, elapsed)
    
    async def _log_quick_reaction(self, payload: discord.RawReactionActionEvent, elapsed: float):
        """Log when a user quickly adds and removes a reaction on another user's message."""
        if not config.REACTION_LOG_CHANNEL_ID:
            return
        
        log_channel = self.bot.get_channel(config.REACTION_LOG_CHANNEL_ID)
        if not log_channel:
            try:
                log_channel = await self.bot.fetch_channel(config.REACTION_LOG_CHANNEL_ID)
            except (discord.NotFound, discord.Forbidden):
                return
        
        # Fetch the message to get the author
        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(payload.channel_id)
            except (discord.NotFound, discord.Forbidden):
                return
        
        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden):
            return
        
        # Only log if the reactor is not the message author (reacting to someone else's message)
        if payload.user_id == message.author.id:
            return
        
        # Fetch the user who reacted
        try:
            reactor = await self.bot.fetch_user(payload.user_id)
        except discord.NotFound:
            reactor = None
        
        reactor_name = f"{reactor.mention} ({reactor.name})" if reactor else f"User ID: {payload.user_id}"
        
        embed = discord.Embed(
            title="⚡ Quick Reaction Detected",
            description=f"A user reacted and removed within {elapsed:.2f}s",
            color=discord.Color.orange()
        )
        embed.add_field(name="Reactor", value=reactor_name, inline=True)
        embed.add_field(name="Emoji", value=str(payload.emoji), inline=True)
        embed.add_field(name="Message Author", value=f"{message.author.mention} ({message.author.name})", inline=True)
        embed.add_field(name="Message", value=f"[Jump to message]({message.jump_url})", inline=False)
        embed.set_footer(text=f"Channel: #{channel.name}")
        
        try:
            await log_channel.send(embed=embed)
        except discord.HTTPException:
            pass
        
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        
        guild = message.guild
        guild_settings = get_guild_settings(guild.id) if guild else None
        
        if guild_settings and guild_settings.get("moderation_enabled", False):
            content = message.content
            content_lower = content.lower() if content else ""
            author = message.author
            current_time = time.time()
            
            bad_words = guild_settings.get("bad_words", config.DEFAULT_BAD_WORDS)
            if any(w in content_lower for w in bad_words):
                try: 
                    await message.delete()
                except: 
                    pass
                await self.warn_user(author, "Inappropriate language.")
                return
            
            caps_threshold = float(guild_settings.get("caps_threshold", config.DEFAULT_CAPS_THRESHOLD))
            if content and len(content) > 10:
                letters = [c for c in content if c.isalpha()]
                if letters:
                    cap_ratio = sum(1 for c in letters if c.isupper()) / max(len(letters), 1)
                    if cap_ratio > caps_threshold:
                        try: 
                            await message.delete()
                        except: 
                            pass
                        await self.warn_user(author, "Too many capital letters.")
                        return
            
            banned_links = guild_settings.get("banned_links", config.DEFAULT_BANNED_LINKS)
            if any(bad_link in content_lower for bad_link in banned_links):
                try: 
                    await message.delete()
                except: 
                    pass
                await self.warn_user(author, "Posting invite or banned links.")
                return
            
            spam_window = int(guild_settings.get("spam_window", config.DEFAULT_SPAM_WINDOW))
            spam_threshold = int(guild_settings.get("spam_threshold", config.DEFAULT_SPAM_THRESHOLD))
            if self.is_spam(guild.id, author.id, current_time, spam_window, spam_threshold):
                try: 
                    await message.delete()
                except: 
                    pass
                await self.mute_user(author, duration=60, reason="Spamming messages.")
                return
    
    @commands.command()
    @role_check(config.ADMIN_ROLE_ID, config.MOD_ROLE_ID)
    async def moderation(self, ctx, action: str = None):
        """Enable or disable moderation."""
        settings = get_guild_settings(ctx.guild.id)
        if action == "enable":
            settings["moderation_enabled"] = True
            save_guild_settings(ctx.guild.id, settings)
            await ctx.send("✅ Moderation enabled.")
        elif action == "disable":
            settings["moderation_enabled"] = False
            save_guild_settings(ctx.guild.id, settings)
            await ctx.send("❌ Moderation disabled.")
        else:
            await ctx.send("Usage: /moderation enable|disable")
    
    @commands.command()
    @role_check(config.ADMIN_ROLE_ID, config.MOD_ROLE_ID)
    async def badword(self, ctx, action: str = None, *, word: str = None):
        """Manage bad words list."""
        settings = get_guild_settings(ctx.guild.id)
        words = settings.get("bad_words", config.DEFAULT_BAD_WORDS)
        if action == "add" and word:
            lw = word.lower()
            if lw not in words:
                words.append(lw)
            settings["bad_words"] = words
            save_guild_settings(ctx.guild.id, settings)
            await ctx.send(f"✅ Added bad word: {word}")
        elif action == "remove" and word:
            if word.lower() in words: 
                words.remove(word.lower())
            settings["bad_words"] = words
            save_guild_settings(ctx.guild.id, settings)
            await ctx.send(f"❌ Removed bad word: {word}")
        elif action == "list":
            await ctx.send("Bad words: " + ", ".join(words))
        else:
            await ctx.send("Usage: /badword add|remove|list <word>")
    
    @commands.command()
    @role_check(config.ADMIN_ROLE_ID, config.MOD_ROLE_ID)
    async def bannedlink(self, ctx, action: str = None, *, link: str = None):
        """Manage banned links list."""
        settings = get_guild_settings(ctx.guild.id)
        links = settings.get("banned_links", config.DEFAULT_BANNED_LINKS)
        if action == "add" and link:
            ll = link.lower()
            if ll not in links:
                links.append(ll)
            settings["banned_links"] = links
            save_guild_settings(ctx.guild.id, settings)
            await ctx.send(f"✅ Added banned link: {link}")
        elif action == "remove" and link:
            if link.lower() in links: 
                links.remove(link.lower())
            settings["banned_links"] = links
            save_guild_settings(ctx.guild.id, settings)
            await ctx.send(f"❌ Removed banned link: {link}")
        elif action == "list":
            await ctx.send("Banned links: " + ", ".join(links))
        else:
            await ctx.send("Usage: /bannedlink add|remove|list <link>")
    
    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: int):
        """Unban a user by their ID."""
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user)
            await ctx.send(f"✅ Unbanned {user.mention} ({user.id})")
        except discord.NotFound:
            await ctx.send("⚠️ That user was not found in the ban list.")
        except discord.Forbidden:
            await ctx.send("⚠️ I don't have permission to unban.")
        except Exception as e:
            await ctx.send(f"⚠️ Failed to unban: {e}")
    
    async def warn_user(self, user, reason):
        """Warn a user."""
        try:
            await user.send(f"⚠️ You have been warned: {reason}")
        except discord.Forbidden:
            pass
        await log_to_channel(self.bot, f"⚠️ Warned {user.mention} for: {reason}")
    
    async def mute_user(self, user, duration=60, reason=""):
        """Mute a user."""
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
        await self.warn_user(user, f"You were muted for {duration} seconds: {reason}")
        await log_to_channel(self.bot, f"🔇 Muted {user.mention} for {duration}s. Reason: {reason}")
        await asyncio.sleep(duration)
        try:
            await user.remove_roles(mute_role)
        except Exception:
            pass
        await log_to_channel(self.bot, f"🔊 Unmuted {user.mention} after {duration}s.")
    
    def is_spam(self, guild_id, user_id, current_time, spam_window, spam_threshold):
        """Check if message is spam."""
        key = (guild_id, user_id)
        message_times = self.user_message_logs.get(key, [])
        message_times.append(current_time)
        self.user_message_logs[key] = [t for t in message_times if current_time - t < spam_window]
        return len(self.user_message_logs[key]) >= spam_threshold

async def setup(bot):
    await bot.add_cog(Moderation(bot))