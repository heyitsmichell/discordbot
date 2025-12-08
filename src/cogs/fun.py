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
    async def on_reaction_add(self, reaction, user):
        """Remove specific reactions added to the protected user's messages."""
        if user.bot:
            return
        
        # Check if the message belongs to the protected user and reaction is in goat_reactions
        if reaction.message.author.id == PROTECTED_USER_ID:
            # Get the emoji string (handles both unicode and custom emojis)
            emoji_str = str(reaction.emoji)
            if emoji_str in self.goat_reactions:
                try:
                    await reaction.remove(user)
                except discord.Forbidden:
                    pass
                except discord.NotFound:
                    pass
                except discord.HTTPException:
                    pass


async def setup(bot):
    await bot.add_cog(Fun(bot))
