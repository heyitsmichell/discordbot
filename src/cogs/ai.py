import discord
from discord import app_commands
from discord.ext import commands
from google import genai
from google.genai import types
from collections import deque
import os
import re
import random
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

IMPORTANT EMOJI & EMOTE RULES:
1. ALWAYS STRONGLY PREFER using this server's custom emotes (listed above like :emotename:) over regular Unicode emojis whenever possible, both in your message text and in your reactions! Using our custom emotes makes you feel like a true regular member of the community.
2. Use custom emotes naturally to add flavor and match the conversation context.

MESSAGE REACTIONS:
If you want to add emoji reactions to your reply, add them at the very end like this (invisible to users):
[REACT: :server_emote1:, :server_emote2:]

For example:
[REACT: :pepehappy:, :catjam:]

Only add reactions if you genuinely feel like reacting. Strongly prefer custom server emotes for reactions over plain Unicode emojis. Keep it chill, 1-3 max."""

    async def generate_response(self, message: str, guild: discord.Guild, author_name: str = "User", channel_name: str = "chat", channel_id: int = 0) -> tuple[str, list[str]]:
        if not self.client:
            return "❌ Gemini API key not configured.", []
        
        models = ['gemini-3.1-flash-lite']
        system_prompt = self.build_system_prompt(guild)
        
        history_key = channel_id if channel_id != 0 else (guild.id if guild else 0)
        # Get or init per-channel history
        if history_key not in self.history:
            self.history[history_key] = deque(maxlen=100)
        
        formatted_user_message = f"[#{channel_name}] {author_name}: {message}"
        
        # Prepare content with per-channel history
        contents = list(self.history[history_key])
        contents.append(types.Content(role='user', parts=[types.Part.from_text(text=formatted_user_message)]))
        
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
                    for r in reaction_str.split(','):
                        cleaned = r.strip()
                        if cleaned:
                            reactions.append(cleaned)
                    response_text = re.sub(r'\[REACT:\s*.+?\]', '', response_text).strip()
                
                # Update per-channel history (append user msg and model response)
                self.history[history_key].append(types.Content(role='user', parts=[types.Part.from_text(text=formatted_user_message)]))
                self.history[history_key].append(types.Content(role='model', parts=[types.Part.from_text(text=response_text)]))

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
                reaction_clean = reaction.strip()
                match = re.match(r'<a?:(\w+):(\d+)>', reaction_clean)
                if match:
                    emoji_id = int(match.group(2))
                    emoji = self.bot.get_emoji(emoji_id)
                    if emoji:
                        await message.add_reaction(emoji)
                else:
                    await message.add_reaction(reaction_clean)
            except Exception as e:
                print(f"Error adding reaction '{reaction}': {e}")

    @app_commands.command(name="ask", description="Ask the AI a question")
    @app_commands.describe(question="Your question for the AI")
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer()
        
        channel_name = getattr(interaction.channel, "name", "chat")
        author_name = interaction.user.display_name
        response_text, reactions = await self.generate_response(question, interaction.guild, author_name, channel_name, interaction.channel_id or 0)
        
        sent_message = await interaction.followup.send(response_text)
        
        if reactions:
            await self.add_reactions(sent_message, reactions)
    
    async def maybe_random_react(self, message: discord.Message):
        if not self.client or not message.guild or not message.content:
            return
        try:
            emotes = self.get_server_emotes(message.guild)
            prompt = f"""You are a chill member of this Discord server reading this chat message by {message.author.display_name}:
"{message.content}"

{emotes}

If you feel like reacting to this message with 1 or 2 of our server's custom emotes that match the vibe/context, respond ONLY with:
[REACT: :server_emote1:]

If you don't feel like reacting or no emote fits well, respond ONLY with:
NONE"""
            response = await self.client.aio.models.generate_content(
                model='gemini-3.1-flash-lite',
                contents=[types.Content(role='user', parts=[types.Part.from_text(text=prompt)])]
            )
            text = (response.text or "").strip()
            react_match = re.search(r'\[REACT:\s*(.+?)\]', text, re.IGNORECASE)
            if react_match:
                reaction_str = react_match.group(1)
                reactions = [r.strip() for r in reaction_str.split(',') if r.strip()]
                if reactions:
                    await self.add_reactions(message, reactions[:2])
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        
        # Always passively record message into per-channel conversational memory
        history_key = message.channel.id
        channel_name = getattr(message.channel, "name", "chat")
        author_name = message.author.display_name
        formatted_user_message = f"[#{channel_name}] {author_name}: {message.content}"
        
        if history_key not in self.history:
            self.history[history_key] = deque(maxlen=100)
        self.history[history_key].append(types.Content(role='user', parts=[types.Part.from_text(text=formatted_user_message)]))
        
        # If bot is not mentioned, 25% chance to randomly react with custom server emotes!
        if not self.bot.user.mentioned_in(message):
            # DISABLED to conserve Free Tier API quota and prevent 429 rate limits:
            # if not message.content.startswith(('/', '!')) and random.random() < 0.25:
            #     await self.maybe_random_react(message)
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
            response_text, reactions = await self.generate_response(clean_content, message.guild, author_name, channel_name, message.channel.id)
        
        sent_message = await message.reply(response_text, mention_author=False)
        
        if reactions:
            await self.add_reactions(sent_message, reactions)


async def setup(bot):
    await bot.add_cog(AI(bot))
