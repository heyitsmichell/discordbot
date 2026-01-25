import discord
from discord import app_commands
from discord.ext import commands
from google import genai
import os
import re
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

class AI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
    
    def get_server_emotes(self, guild: discord.Guild) -> str:
        if not guild or not guild.emojis:
            return "No custom emotes available."
        
        emote_list = []
        for emoji in guild.emojis[:50]:
            emote_list.append(f"<:{emoji.name}:{emoji.id}>")
        
        return "Available server emotes: " + ", ".join(emote_list)
    
    def build_system_prompt(self, guild: discord.Guild) -> str:
        emotes = self.get_server_emotes(guild)
        
        return f"""You are a friendly and helpful Discord bot assistant. Keep your responses concise and conversational.

{emotes}

You can use these emotes naturally in your responses when appropriate. Use them sparingly - only when they add to the message.

If you want to react to your own message with emotes, end your response with a line like:
[REACT: emote1, emote2]

For example:
[REACT: <:happy:123>, <:thumbsup:456>]

Only suggest reactions when it makes sense contextually. Keep reactions to 1-3 emotes maximum."""

    async def generate_response(self, message: str, guild: discord.Guild) -> tuple[str, list[str]]:
        if not self.client:
            return "❌ Gemini API key not configured.", []
        
        models = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro']
        system_prompt = self.build_system_prompt(guild)
        
        for model_name in models:
            try:
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=f"{system_prompt}\n\nUser message: {message}"
                )
                
                response_text = response.text
                
                reactions = []
                react_match = re.search(r'\[REACT:\s*(.+?)\]', response_text, re.IGNORECASE)
                if react_match:
                    reaction_str = react_match.group(1)
                    emote_pattern = r'<a?:\w+:\d+>'
                    reactions = re.findall(emote_pattern, reaction_str)
                    response_text = re.sub(r'\[REACT:\s*.+?\]', '', response_text).strip()
                
                return response_text, reactions[:3]
                
            except Exception as e:
                error_str = str(e).lower()
                if '429' in error_str or 'quota' in error_str or 'rate' in error_str:
                    continue
                print(f"Gemini API error ({model_name}): {e}")
                return f"❌ Failed to generate response: {str(e)}", []
        
        return "⏳ All AI models are currently rate limited. Please try again later.", []
    
    async def add_reactions(self, message: discord.Message, reactions: list[str]):
        for reaction in reactions:
            try:
                match = re.match(r'<a?:(\w+):(\d+)>', reaction)
                if match:
                    emoji_id = int(match.group(2))
                    emoji = self.bot.get_emoji(emoji_id)
                    if emoji:
                        await message.add_reaction(emoji)
            except discord.Forbidden:
                pass
            except discord.NotFound:
                pass
            except Exception as e:
                print(f"Error adding reaction: {e}")

    @app_commands.command(name="ask", description="Ask the AI a question")
    @app_commands.describe(question="Your question for the AI")
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer()
        
        response_text, reactions = await self.generate_response(question, interaction.guild)
        
        sent_message = await interaction.followup.send(response_text)
        
        if reactions:
            await self.add_reactions(sent_message, reactions)
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        
        if not self.bot.user.mentioned_in(message):
            return
        
        if message.mention_everyone:
            return
        
        clean_content = message.content
        for mention in message.mentions:
            if mention.id == self.bot.user.id:
                clean_content = clean_content.replace(f'<@{self.bot.user.id}>', '').replace(f'<@!{self.bot.user.id}>', '')
        
        clean_content = clean_content.strip()
        
        if not clean_content:
            clean_content = "Hello!"
        
        async with message.channel.typing():
            response_text, reactions = await self.generate_response(clean_content, message.guild)
        
        sent_message = await message.reply(response_text, mention_author=False)
        
        if reactions:
            await self.add_reactions(sent_message, reactions)


async def setup(bot):
    await bot.add_cog(AI(bot))
