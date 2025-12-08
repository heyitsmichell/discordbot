import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()

GOAT_USER_ID = int(os.getenv('GOAT_USER_ID', 0))
PROTECTED_USER_ID = int(os.getenv('PROTECTED_USER_ID', 0))


class Fun(commands.Cog):
    """Fun cog for automatic reactions and other fun features."""
    
    def __init__(self, bot):
        self.bot = bot
        self.goat_reactions = ['🐐', '🔥']
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for messages and add reactions to the special user."""
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
    
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Remove specific reactions added to the protected user's messages (works for all messages, including old ones)."""
        if payload.user_id == self.bot.user.id:
            return
        
        emoji_str = str(payload.emoji)
        if emoji_str not in self.goat_reactions:
            return
        
        # Fetch the channel
        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(payload.channel_id)
            except (discord.NotFound, discord.Forbidden):
                return
        
        # Fetch the message
        try:
            message = await channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden):
            return
        
        # Check if message author is the protected user
        if message.author.id == PROTECTED_USER_ID:
            # Fetch the user who added the reaction
            try:
                user = await self.bot.fetch_user(payload.user_id)
                await message.remove_reaction(payload.emoji, user)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass


async def setup(bot):
    await bot.add_cog(Fun(bot))
