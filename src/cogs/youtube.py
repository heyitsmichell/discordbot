import discord
from discord.ext import commands
from discord.ui import View, Button
from urllib.parse import quote_plus
import config
from database import get_user, clear_user_youtube

class YouTube(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command()
    async def linkyoutube(self, ctx):
        """Link YouTube account."""
        if not config.CLIENT_ID or not config.REDIRECT_URI or str(config.REDIRECT_URI).strip().lower() in {"none", "null", ""}:
            try:
                await ctx.author.send("⚠️ OAuth not configured.")
            except Exception:
                await ctx.send("⚠️ OAuth not configured.")
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
        
        view = View()
        view.add_item(Button(label="Link YouTube", url=url))
        
        try:
            await ctx.author.send("🔗 Click below to link your YouTube account:", view=view)
            await ctx.send(f"{ctx.author.mention}, check your DMs to link YouTube!")
        except discord.Forbidden:
            await ctx.send("❌ Couldn't DM you. Please enable DMs to receive the link.")
    
    @commands.command()
    async def youtube(self, ctx, member: discord.Member = None):
        """Show linked YouTube account."""
        member = member or ctx.author
        user = get_user(str(member.id))
        
        if user and user.get("youtube_channel"):
            await ctx.send(f"{member.display_name}'s YouTube: **{user['youtube_channel']}**")
        else:
            await ctx.send(f"{member.display_name} has not linked a YouTube account.")
    
    @commands.command()
    async def unlinkyoutube(self, ctx):
        """Unlink YouTube account."""
        clear_user_youtube(str(ctx.author.id))
        await ctx.send(f"{ctx.author.mention}, your YouTube account has been unlinked.")

async def setup(bot):
    await bot.add_cog(YouTube(bot))
