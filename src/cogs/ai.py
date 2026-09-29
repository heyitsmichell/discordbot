import discord
from discord import app_commands
from discord.ext import commands
from openai import AsyncOpenAI
from collections import deque
import os
import re
import random
import json
from datetime import datetime
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from database import get_ai_history, save_ai_history

load_dotenv()

NVIDIA_API_KEY = os.getenv('NVIDIA_API_KEY')
NVIDIA_MODEL = os.getenv('NVIDIA_MODEL', 'meta/llama-3.1-70b-instruct')

class AI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.client = AsyncOpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=NVIDIA_API_KEY
        ) if NVIDIA_API_KEY else None
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
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        return f"""You are just a regular, chill member of this Discord server. 
You hang out, chat with people, and match the energy of the conversation. You're not an "assistant" or a "bot" - you're just another friend in the chat.
Talk like a normal internet user. Use lower case sometimes, use slang if it fits, and be concise. Don't write paragraphs unless necessary.

Current System Date/Time: {current_time}

NOTE: User messages are prefixed with their channel and name like this: `[#channel] username: message`.
CRITICAL RULE: When you reply, DO NOT prefix your response with your name, the channel, or `[#chat]`. Just write your reply text directly!
CRITICAL RULE: If a user asks a question about current events, news, or weather that you don't know, use your search_web tool!

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
            return "❌ NVIDIA API key not configured.", []
        
        models = [NVIDIA_MODEL]
        system_prompt = self.build_system_prompt(guild)
        
        history_key = channel_id if channel_id != 0 else (guild.id if guild else 0)
        # Get or init per-channel history
        if history_key not in self.history:
            saved_history = get_ai_history(history_key)
            self.history[history_key] = deque(saved_history, maxlen=100)
        
        formatted_user_message = f"[#{channel_name}] {author_name}: {message}"
        
        # Prepare content with per-channel history
        messages = [{"role": "system", "content": system_prompt}] + list(self.history[history_key])
        messages.append({"role": "user", "content": formatted_user_message})
        
        for model_name in models:
            try:
                tools_config = [{
                    "type": "function",
                    "function": {
                        "name": "search_web",
                        "description": "Search the internet for current events, facts, or information you don't know.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "The search query to look up on DuckDuckGo."
                                }
                            },
                            "required": ["query"]
                        }
                    }
                }]
                
                response = await self.client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=1024,
                    tools=tools_config,
                    tool_choice="auto"
                )
                
                response_message = response.choices[0].message
                
                if response_message.tool_calls:
                    messages.append(response_message)
                    for tool_call in response_message.tool_calls:
                        if tool_call.function.name == "search_web":
                            try:
                                args = json.loads(tool_call.function.arguments)
                                query = args.get("query", "")
                                print(f"[AI] Searching web for: {query}")
                                results = DDGS().text(query, max_results=3)
                                search_text = "\n".join([f"Title: {r['title']}\nContent: {r['body']}" for r in results])
                            except Exception as e:
                                search_text = f"Search failed: {e}"
                            
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": search_text
                            })
                    
                    # Second call with tool results
                    response = await self.client.chat.completions.create(
                        model=model_name,
                        messages=messages,
                        temperature=0.7,
                        max_tokens=1024
                    )
                    response_message = response.choices[0].message
                
                response_text = response_message.content or ""
                
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
                self.history[history_key].append({"role": "user", "content": formatted_user_message})
                self.history[history_key].append({"role": "assistant", "content": response_text})
                save_ai_history(history_key, list(self.history[history_key]))

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
            response = await self.client.chat.completions.create(
                model='meta/llama-3.1-8b-instruct',
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=64,
            )
            text = (response.choices[0].message.content or "").strip()
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
            saved_history = get_ai_history(history_key)
            self.history[history_key] = deque(saved_history, maxlen=100)
        self.history[history_key].append({"role": "user", "content": formatted_user_message})
        save_ai_history(history_key, list(self.history[history_key]))
        
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
