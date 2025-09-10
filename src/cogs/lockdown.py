import discord
from discord.ext import commands
import asyncio
from utils.helpers import log_to_channel
import config

class Lockdown(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    async def apply_lockdown(self, ctx, delay: int, description: str):
        """Apply lockdown to all text channels."""
        color = discord.Color.red() if delay > 0 else discord.Color.green()
        embed = discord.Embed(
            title="🔒 Lockdown Update",
            description=description,
            color=color
        )
        await ctx.send(embed=embed)
        
        for ch in ctx.guild.channels:
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.edit(slowmode_delay=delay, reason=description)
                except discord.Forbidden:
                    await log_to_channel(self.bot, f"⚠️ Missing permission for #{ch.name}")
                except discord.HTTPException as e:
                    await log_to_channel(self.bot, f"⚠️ Failed to set slowmode for #{ch.name}: {e}")
                await asyncio.sleep(config.SLOWMODE_EDIT_DELAY)
    
    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def lock1(self, ctx):
        """Set 15s slowmode on all text channels."""
        await self.apply_lockdown(ctx, 15, "Lockdown level 1 (15s slowmode)")
    
    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def lock2(self, ctx):
        """Set 30s slowmode on all text channels."""
        await self.apply_lockdown(ctx, 30, "Lockdown level 2 (30s slowmode)")
    
    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def lock3(self, ctx):
        """Set 60s slowmode on all text channels."""
        await self.apply_lockdown(ctx, 60, "Lockdown level 3 (60s slowmode)")
    
    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx):
        """Remove slowmode from all text channels."""
        await self.apply_lockdown(ctx, 0, "Lockdown lifted (0s slowmode)")

async def setup(bot):
    await bot.add_cog(Lockdown(bot))