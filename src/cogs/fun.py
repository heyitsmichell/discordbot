import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()

GOAT_USER_ID = int(os.getenv('GOAT_USER_ID', 0))
PROTECTED_USER_ID = int(os.getenv('PROTECTED_USER_ID', 0))
OWNER_USER_ID = int(os.getenv('OWNER', 0))


class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.goat_reactions = ['🐐', '🔥']
        self.owner_reaction = '🩷'
    
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        
        if message.author.id == GOAT_USER_ID:
            for emoji in self.goat_reactions:
                try:
                    await message.add_reaction(emoji)
                except discord.Forbidden:
                    # Bot doesn't have permission to add reactions
                    pass
                except discord.NotFound:
                    # Message was deleted before we could react
                    pass
                except discord.HTTPException:
                    # Failed to add reaction for some other reason
                    pass
        
        if message.author.id == OWNER_USER_ID:
            try:
                await message.add_reaction(self.owner_reaction)
            except discord.Forbidden:
                pass
            except discord.NotFound:
                pass
            except discord.HTTPException:
                pass
    
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        
        emoji_str = str(payload.emoji)
        if emoji_str not in self.goat_reactions:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(payload.channel_id)
            except (discord.NotFound, discord.Forbidden):
                return
        
        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden):
            return
        
        if message.author.id == PROTECTED_USER_ID:
            try:
                user = await self.bot.fetch_user(payload.user_id)
                await message.remove_reaction(payload.emoji, user)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass


async def setup(bot):
    await bot.add_cog(Fun(bot))
