import discord
from discord.ext import commands
from discord.utils import escape_markdown
import sqlite3
import asyncio
import config

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    async def send_paginated_embed(self, ctx, title: str, entries: list, per_page: int = 10):
        """Send a paginated embed with reaction controls."""
        if not entries:
            await ctx.send(f"⚠️ No users found for {title}.")
            return
        
        pages = [entries[i:i + per_page] for i in range(0, len(entries), per_page)]
        total_pages = len(pages)
        current_page = 0
        
        def make_embed(page_index: int):
            embed = discord.Embed(
                title=title,
                description="\n".join(pages[page_index]),
                color=discord.Color.purple()
            )
            embed.set_footer(text=f"Page {page_index + 1}/{total_pages}")
            return embed
        
        message = await ctx.send(embed=make_embed(current_page))
        
        if total_pages == 1:
            return
        
        controls = ["⏮️", "◀️", "▶️", "⏭️"]
        for c in controls:
            try:
                await message.add_reaction(c)
            except Exception:
                pass
        
        def check(reaction, user):
            return (
                user == ctx.author
                and str(reaction.emoji) in controls
                and reaction.message.id == message.id
            )
        
        while True:
            try:
                reaction, user = await self.bot.wait_for("reaction_add", timeout=60.0, check=check)
                emoji = str(reaction.emoji)
                
                if emoji == "⏮️":
                    current_page = 0
                elif emoji == "◀️":
                    current_page = (current_page - 1) % total_pages
                elif emoji == "▶️":
                    current_page = (current_page + 1) % total_pages
                elif emoji == "⏭️":
                    current_page = total_pages - 1
                
                await message.edit(embed=make_embed(current_page))
                try:
                    await message.remove_reaction(reaction, user)
                except Exception:
                    pass
            except asyncio.TimeoutError:
                try:
                    await message.clear_reactions()
                except Exception:
                    pass
                break
    
    def format_username(self, member, discord_id: int):
        """Format username display."""
        if member:
            if getattr(member, 'discriminator', "0") != "0":
                name = f"{member.name}#{member.discriminator}"
            else:
                name = member.name
            return f"{name} (<@{discord_id}>)"
        else:
            return f"(Left the server) {discord_id}"
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def twitchusers(self, ctx):
        """List all users with linked Twitch accounts."""
        conn = sqlite3.connect(config.DB_FILE, timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT discord_id, twitch_username FROM users WHERE twitch_username IS NOT NULL")
        rows = cur.fetchall()
        conn.close()
        
        entries = []
        for discord_id, twitch_username in rows:
            member = ctx.guild.get_member(int(discord_id))
            display_name = self.format_username(member, discord_id)
            twitch_url = f"https://twitch.tv/{twitch_username}"
            entries.append((display_name.lower(), f"**{display_name}** — [{twitch_username}]({twitch_url})"))
        
        entries.sort(key=lambda x: x[0])
        formatted_entries = [entry[1] for entry in entries]
        
        await self.send_paginated_embed(ctx, "Users — Twitch", formatted_entries)
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def youtubeusers(self, ctx):
        """List all users with linked YouTube accounts."""
        conn = sqlite3.connect(config.DB_FILE, timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT discord_id, youtube_channel FROM users WHERE youtube_channel IS NOT NULL")
        rows = cur.fetchall()
        conn.close()
        
        entries = []
        for discord_id, youtube_channel in rows:
            member = ctx.guild.get_member(int(discord_id))
            display_name = self.format_username(member, discord_id)
            safe_channel = escape_markdown(str(youtube_channel))
            entries.append((display_name.lower(), f"**{display_name}** — {safe_channel}"))
        
        entries.sort(key=lambda x: x[0])
        formatted_entries = [entry[1] for entry in entries]
        
        await self.send_paginated_embed(ctx, "Users — YouTube", formatted_entries)
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        """Set the global log channel."""
        config.LOG_CHANNEL_ID = channel.id
        await ctx.send(f"✅ Log channel set to {channel.mention} (in-memory)")
    
    @commands.command()
    async def getlogchannel(self, ctx):
        """Get the current log channel."""
        if config.LOG_CHANNEL_ID:
            channel = ctx.guild.get_channel(config.LOG_CHANNEL_ID)
            if channel:
                await ctx.send(f"📌 Current log channel is {channel.mention} (in-memory)")
                return
        await ctx.send("⚠️ No global log channel configured (in-memory).")
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def resetlogchannel(self, ctx):
        """Reset the log channel configuration."""
        config.LOG_CHANNEL_ID = None
        await ctx.send("✅ Global log channel has been reset (in-memory).")

async def setup(bot):
    await bot.add_cog(Admin(bot))