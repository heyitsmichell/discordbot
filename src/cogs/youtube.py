import discord
from discord.ext import commands
import sqlite3
from urllib.parse import quote_plus
import config

class YouTube(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command()
    async def linkyoutube(self, ctx):
        """Link YouTube account."""
        if not config.CLIENT_ID or not config.REDIRECT_URI or str(config.REDIRECT_URI).strip().lower() in {"none", "null", ""}:
            try:
                await ctx.author.send("OAuth not configured.")
            except Exception:
                await ctx.send("OAuth not configured.")
            return
        
        encoded_redirect = quote_plus(config.REDIRECT_URI)
        url = (
            f"https://discord.com/api/oauth2/authorize"
            f"?client_id={config.CLIENT_ID}"
            f"&redirect_uri={encoded_redirect}"
            f"&response_type=code"
            f"&scope=identify%20connections"
            f"&state=youtube"
        )
        
        try:
            await ctx.author.send(f"Click here to link your YouTube: {url}")
            await ctx.send(f"{ctx.author.mention}, check your DMs to link YouTube!")
        except discord.Forbidden:
            await ctx.send("Couldn't DM you. Enable DMs.")
    
    @commands.command()
    async def youtube(self, ctx, member: discord.Member = None):
        """Show linked YouTube account."""
        member = member or ctx.author
        conn = sqlite3.connect(config.DB_FILE, timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT youtube_channel FROM users WHERE discord_id = ?", (str(member.id),))
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            await ctx.send(f"{member.display_name}'s YouTube: **{row[0]}**")
        else:
            await ctx.send(f"{member.display_name} has not linked a YouTube account.")
    
    @commands.command()
    async def unlinkyoutube(self, ctx):
        """Unlink YouTube account."""
        conn = sqlite3.connect(config.DB_FILE, timeout=10)
        cur = conn.cursor()
        cur.execute("UPDATE users SET youtube_channel=NULL WHERE discord_id=?", (str(ctx.author.id),))
        conn.commit()
        conn.close()
        await ctx.send(f"{ctx.author.mention}, your YouTube account has been unlinked.")

async def setup(bot):
    await bot.add_cog(YouTube(bot))
