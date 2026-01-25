import discord
from discord import app_commands
from discord.ext import commands
from google import genai
from google.genai import types
from collections import deque
import os
import re
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

class AI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
        self.history = {} # Key: channel_id, Value: deque of messages
    
    def get_server_emotes(self, guild: discord.Guild) -> str:
        if not guild or not guild.emojis:
            return "No custom emotes available."
        
        emote_list = []
        for emoji in guild.emojis:
            if emoji.name.startswith(('mongop1', 'nomipu')):
                continue
            emote_list.append(f":{emoji.name}:")
        
        return "Available server emotes: " + ", ".join(emote_list)
    
    def build_system_prompt(self, guild: discord.Guild) -> str:
        emotes = self.get_server_emotes(guild)
        
        return f"""You are just a regular, chill member of this Discord server. 
You hang out, chat with people, and match the energy of the conversation. You're not an "assistant" or a "bot" - you're just another friend in the chat.
Talk like a normal internet user. Use lower case sometimes, use slang if it fits, and be concise. Don't write paragraphs unless necessary.

{emotes}

Feel free to use these emotes to express yourself! Use them to react to what people say or to add flavor to your own messages.
Try to pick emotes that match the specific context of the conversation. If someone mentions a specific game or feeling, look for a matching emote in the list.

If you want to react to your own message with emotes, just add them at the very end like this (invisible to users):
[REACT: emote1, emote2]

For example:
[REACT: :happy:, :thumbsup:]

Only add reactions if you genuinely feel like reacting. Keep it chill, 1-3 max."""

    async def generate_response(self, message: str, guild: discord.Guild, channel_id: int) -> tuple[str, list[str]]:
        if not self.client:
            return "❌ Gemini API key not configured.", []
        
        models = ['gemini-2.5-flash']
        system_prompt = self.build_system_prompt(guild)
        
        # Get or init history for this channel
        if channel_id not in self.history:
            self.history[channel_id] = deque(maxlen=10)
        
        # Prepare content with history
        contents = list(self.history[channel_id])
        contents.append(types.Content(role='user', parts=[types.Part.from_text(text=message)]))
        
        for model_name in models:
            try:
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        tools=[types.Tool(google_search=types.GoogleSearch())]
                    )
                )
                
                response_text = response.text
                
                # Replace :emote: with full emote code
                if guild and guild.emojis:
                    for emoji in guild.emojis:
                        response_text = response_text.replace(f":{emoji.name}:", str(emoji))

                reactions = []
                react_match = re.search(r'\[REACT:\s*(.+?)\]', response_text, re.IGNORECASE)
                if react_match:
                    reaction_str = react_match.group(1)
                    # Find unicode emojis or custom emote names
                    custom_emotes = re.findall(r'<a?:\w+:\d+>', reaction_str)
                    reactions.extend(custom_emotes)
                    response_text = re.sub(r'\[REACT:\s*.+?\]', '', response_text).strip()
                
                # Update history (append user msg and model response)
                self.history[channel_id].append(types.Content(role='user', parts=[types.Part.from_text(text=message)]))
                # Store the model's text response (we strip the internal REACT block first so it doesn't loop)
                self.history[channel_id].append(types.Content(role='model', parts=[types.Part.from_text(text=response_text)]))

                return response_text, reactions[:3]
                
            except Exception as e:
                error_str = str(e).lower()
                print(f"[AI DEBUG] {model_name}: {e}")
                if '429' in error_str or 'quota' in error_str or 'rate' in error_str:
                    continue
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
        
        response_text, reactions = await self.generate_response(question, interaction.guild, interaction.channel_id)
        
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
            response_text, reactions = await self.generate_response(clean_content, message.guild, message.channel.id)
        
        sent_message = await message.reply(response_text, mention_author=False)
        
        if reactions:
            await self.add_reactions(sent_message, reactions)


async def setup(bot):
    await bot.add_cog(AI(bot))
