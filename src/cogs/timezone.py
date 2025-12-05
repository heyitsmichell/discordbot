import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime
import asyncio
import pytz
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder
from database import (
    get_user_timezone, set_user_timezone, remove_user_timezone, get_all_user_timezones,
    save_timezone_embed, update_timezone_embed_page, remove_timezone_embed, get_all_timezone_embeds
)
import config

def slash_role_check(*role_ids):
    """Check if user has any of the specified roles (for slash commands)."""
    async def predicate(interaction: discord.Interaction):
        return any(role.id in role_ids for role in interaction.user.roles)
    return app_commands.check(predicate)

class Timezone(commands.Cog):
    PAGE_RESET_DELAY = 20  # seconds before auto-reset to page 1
    
    def __init__(self, bot):
        self.bot = bot
        self.geolocator = Nominatim(user_agent="discord_timezone_bot")
        self.tf = TimezoneFinder()
        self.updating_messages = {}  # guild_id -> {"message": msg, "page": int}
        self.page_reset_tasks = {}  # guild_id -> asyncio.Task for auto-reset
        self.update_time_embeds.start()
    
    def cog_unload(self):
        self.update_time_embeds.cancel()
        # Cancel all pending page reset tasks
        for task in self.page_reset_tasks.values():
            task.cancel()
    
    async def schedule_page_reset(self, guild_id: int):
        """Schedule a page reset to page 1 after delay."""
        # Cancel existing reset task for this guild if any
        if guild_id in self.page_reset_tasks:
            self.page_reset_tasks[guild_id].cancel()
        
        async def reset_page():
            await asyncio.sleep(self.PAGE_RESET_DELAY)
            if guild_id in self.updating_messages:
                current_page = self.updating_messages[guild_id].get("page", 0)
                if current_page != 0:  # Only reset if not already on page 1
                    self.updating_messages[guild_id]["page"] = 0
                    update_timezone_embed_page(str(guild_id), 0)
                    
                    guild = self.bot.get_guild(guild_id)
                    if guild:
                        try:
                            message = self.updating_messages[guild_id]["message"]
                            embed, _ = self.create_times_embed(guild, 0)
                            await message.edit(embed=embed)
                        except Exception as e:
                            print(f"Error resetting page: {e}")
            
            # Clean up task reference
            if guild_id in self.page_reset_tasks:
                del self.page_reset_tasks[guild_id]
        
        # Create and store the task
        self.page_reset_tasks[guild_id] = asyncio.create_task(reset_page())
    
    async def load_persisted_embeds(self):
        """Load persisted embed tracking from database on startup."""
        embeds = get_all_timezone_embeds()
        loaded_count = 0
        
        for embed_data in embeds:
            try:
                guild_id = int(embed_data["guild_id"])
                channel_id = int(embed_data["channel_id"])
                message_id = int(embed_data["message_id"])
                page = embed_data.get("page", 0)
                
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    # Guild no longer accessible, clean up
                    remove_timezone_embed(str(guild_id))
                    continue
                
                channel = guild.get_channel(channel_id)
                if not channel:
                    # Channel no longer exists, clean up
                    remove_timezone_embed(str(guild_id))
                    continue
                
                try:
                    message = await channel.fetch_message(message_id)
                    self.updating_messages[guild_id] = {
                        "message": message,
                        "page": page
                    }
                    loaded_count += 1
                except discord.NotFound:
                    # Message was deleted, clean up
                    remove_timezone_embed(str(guild_id))
                except discord.Forbidden:
                    # No permission to access, clean up
                    remove_timezone_embed(str(guild_id))
            except Exception as e:
                print(f"Error loading embed for guild {embed_data.get('guild_id')}: {e}")
        
        if loaded_count > 0:
            print(f"✅ Loaded {loaded_count} persisted timezone embed(s)")
    
    def get_location_info(self, location_query: str) -> dict | None:
        """Convert location string to timezone info.
        
        Returns dict with timezone, country_code, city, country or None if not found.
        """
        try:
            location = self.geolocator.geocode(
                location_query, 
                timeout=10,
                addressdetails=True,
                language="en"
            )
            if location:
                timezone = self.tf.timezone_at(lat=location.latitude, lng=location.longitude)
                address = location.raw.get("address", {})
                country_code = address.get("country_code", "").upper()
                country = address.get("country", "")
                # Try to get city from various address fields
                city = (address.get("city") or 
                       address.get("town") or 
                       address.get("municipality") or 
                       address.get("state") or 
                       address.get("region") or 
                       "")
                return {
                    "timezone": timezone,
                    "country_code": country_code,
                    "city": city,
                    "country": country
                }
            return None
        except Exception as e:
            print(f"Geocoding error: {e}")
            return None
    
    def get_current_time(self, timezone_str: str) -> str:
        """Get current time in the given timezone."""
        try:
            tz = pytz.timezone(timezone_str)
            now = datetime.now(tz)
            return now.strftime("%I:%M %p • %a, %b %d")  # e.g., "10:45 PM • Wed, Dec 04"
        except Exception:
            return "Unknown"
    
    def country_code_to_flag(self, country_code: str) -> str:
        """Convert ISO country code to flag emoji."""
        if country_code and len(country_code) == 2:
            # Convert country code to flag emoji (regional indicator symbols)
            # A = 🇦, B = 🇧, etc. Regional indicator A starts at U+1F1E6
            try:
                return "".join(chr(ord(c.upper()) + 127397) for c in country_code)
            except Exception:
                pass
        return "🌍"  # Default globe if code not valid
    
    def get_utc_offset(self, timezone_str: str) -> float:
        """Get UTC offset in hours for sorting."""
        try:
            tz = pytz.timezone(timezone_str)
            now = datetime.now(tz)
            offset = now.utcoffset().total_seconds() / 3600
            return offset
        except Exception:
            return 0
    
    def create_times_embed(self, guild, page: int = 0) -> tuple[discord.Embed, int]:
        """Create an embed showing all users' times, sorted by timezone.
        
        Returns tuple of (embed, total_pages).
        """
        USERS_PER_PAGE = 10
        
        embed = discord.Embed(
            title="🕐 Members' Local Time",
            color=discord.Color.blue()
        )
        
        all_timezones = get_all_user_timezones()
        
        if not all_timezones:
            embed.description = "No timezones set yet!\nUse `/settime <location>` to add yours!"
            return embed, 1
        
        # Collect member data with timezone info
        member_data = []
        for tz_data in all_timezones:
            discord_id = tz_data.get("discord_id")
            timezone = tz_data.get("timezone")
            city = tz_data.get("city")
            country = tz_data.get("country")
            country_code = tz_data.get("country_code", "")
            
            member = guild.get_member(int(discord_id))
            if member:
                offset = self.get_utc_offset(timezone)
                member_data.append({
                    "member": member,
                    "timezone": timezone,
                    "city": city,
                    "country": country,
                    "country_code": country_code,
                    "offset": offset
                })
        
        if not member_data:
            embed.description = "No members with timezones are in this server"
            return embed, 1
        
        # Sort by offset (highest first = furthest ahead in time)
        member_data.sort(key=lambda x: -x["offset"])
        
        # Calculate pagination
        total_members = len(member_data)
        total_pages = max(1, (total_members + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
        
        # Clamp page to valid range
        page = max(0, min(page, total_pages - 1))
        
        # Get members for current page
        start_idx = page * USERS_PER_PAGE
        end_idx = start_idx + USERS_PER_PAGE
        page_members = member_data[start_idx:end_idx]
        
        # Build embed description - each user individually
        lines = []
        for data in page_members:
            current_time = self.get_current_time(data["timezone"])
            flag = self.country_code_to_flag(data["country_code"])
            
            # Format UTC offset
            offset = data["offset"]
            if offset >= 0:
                offset_str = f"UTC+{int(offset)}" if offset == int(offset) else f"UTC+{offset:.1f}"
            else:
                offset_str = f"UTC{int(offset)}" if offset == int(offset) else f"UTC{offset:.1f}"
            
            location_display = f"{data['city']}, {data['country']}" if data['city'] else data['country']
            lines.append(f"**{data['member'].display_name}** — {current_time}\n└ {flag} {location_display} ({offset_str})")
        
        embed.description = "\n\n".join(lines)
        
        # Footer with pagination info
        if total_pages > 1:
            embed.set_footer(text=f"Page {page + 1}/{total_pages} • Use ⬅️ ➡️ to navigate")
        else:
            embed.set_footer(text="Updates every minute")
        return embed, total_pages
    
    @tasks.loop(minutes=1)
    async def update_time_embeds(self):
        """Update all active time embed messages."""
        for guild_id, data in list(self.updating_messages.items()):
            try:
                guild = self.bot.get_guild(guild_id)
                if guild:
                    message = data["message"]
                    page = data.get("page", 0)
                    embed, _ = self.create_times_embed(guild, page)
                    await message.edit(embed=embed)
            except discord.NotFound:
                # Message was deleted, clean up from memory and database
                del self.updating_messages[guild_id]
                remove_timezone_embed(str(guild_id))
            except Exception as e:
                print(f"Error updating time embed: {e}")
    
    async def refresh_guild_embed(self, guild):
        """Immediately refresh the embed for a specific guild."""
        if guild.id in self.updating_messages:
            try:
                data = self.updating_messages[guild.id]
                message = data["message"]
                page = data.get("page", 0)
                embed, total_pages = self.create_times_embed(guild, page)
                await message.edit(embed=embed)
                
                # Add pagination reactions if needed and not already present
                if total_pages > 1:
                    existing_reactions = [str(r.emoji) for r in message.reactions]
                    if "⬅️" not in existing_reactions:
                        await message.add_reaction("⬅️")
                    if "➡️" not in existing_reactions:
                        await message.add_reaction("➡️")
            except discord.NotFound:
                del self.updating_messages[guild.id]
                remove_timezone_embed(str(guild.id))
            except Exception as e:
                print(f"Error refreshing time embed: {e}")
    
    @update_time_embeds.before_loop
    async def before_update_time_embeds(self):
        await self.bot.wait_until_ready()
        # Load persisted embeds after bot is ready
        await self.load_persisted_embeds()
    
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Handle reaction navigation for timezone embeds."""
        # Ignore bot reactions
        if payload.user_id == self.bot.user.id:
            return
        
        # Check if this is a tracked message
        guild_id = payload.guild_id
        if guild_id not in self.updating_messages:
            return
        
        data = self.updating_messages[guild_id]
        if payload.message_id != data["message"].id:
            return
        
        emoji = str(payload.emoji)
        
        # Remove any non-navigation reactions
        if emoji not in ["⬅️", "➡️"]:
            try:
                channel = self.bot.get_channel(payload.channel_id)
                message = await channel.fetch_message(payload.message_id)
                guild = self.bot.get_guild(guild_id)
                if guild:
                    member = guild.get_member(payload.user_id)
                    if member:
                        await message.remove_reaction(payload.emoji, member)
            except Exception:
                pass
            return
        
        # Get current page and total pages
        current_page = data.get("page", 0)
        guild = self.bot.get_guild(guild_id)
        
        if not guild:
            return
        
        _, total_pages = self.create_times_embed(guild, current_page)
        
        # Calculate new page
        if emoji == "⬅️":
            new_page = max(0, current_page - 1)
        else:  # ➡️
            new_page = min(total_pages - 1, current_page + 1)
        
        # Only update if page changed
        if new_page != current_page:
            self.updating_messages[guild_id]["page"] = new_page
            # Persist page change to database
            update_timezone_embed_page(str(guild_id), new_page)
            embed, _ = self.create_times_embed(guild, new_page)
            
            try:
                await data["message"].edit(embed=embed)
            except Exception as e:
                print(f"Error updating page: {e}")
            
            # Schedule auto-reset to page 1 if not already on page 1
            if new_page != 0:
                await self.schedule_page_reset(guild_id)
            else:
                # Cancel any pending reset if we're back on page 1
                if guild_id in self.page_reset_tasks:
                    self.page_reset_tasks[guild_id].cancel()
                    del self.page_reset_tasks[guild_id]
        
        # Remove the user's reaction to keep it clean
        try:
            channel = self.bot.get_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
            member = guild.get_member(payload.user_id)
            if member:
                await message.remove_reaction(payload.emoji, member)
        except Exception:
            pass  # Ignore if we can't remove the reaction
    
    # ===================== SLASH COMMANDS =====================
    
    @app_commands.command(name="settime", description="Set your timezone based on your location")
    @app_commands.describe(location="Your city or location (e.g., 'Tokyo, Japan' or 'New York')")
    async def settime(self, interaction: discord.Interaction, location: str):
        """Set your timezone based on location."""
        await interaction.response.defer(thinking=True)
        
        location_info = self.get_location_info(location)
        
        if not location_info or not location_info["timezone"]:
            await interaction.followup.send(f"❌ Couldn't find timezone for **{location}**. Please check the spelling and try again.")
            return
        
        flag = self.country_code_to_flag(location_info["country_code"])
        city = location_info["city"]
        country = location_info["country"]
        timezone = location_info["timezone"]
        country_code = location_info["country_code"]
        
        success = set_user_timezone(str(interaction.user.id), city, country, timezone, country_code)
        
        if success:
            current_time = self.get_current_time(timezone)
            # Show location with city if available
            location_display = f"{city}, {country}" if city else country
            await interaction.followup.send(f"✅ Timezone set!\n{flag} **Location:** {location_display}\n**Timezone:** {timezone}\n**Current time:** {current_time}")
            # Auto-refresh the embed if one exists for this guild
            await self.refresh_guild_embed(interaction.guild)
        else:
            await interaction.followup.send("❌ Failed to save your timezone. Please try again later.")
    
    @app_commands.command(name="mytime", description="Show your current local time")
    async def mytime(self, interaction: discord.Interaction):
        """Show your current local time."""
        tz_data = get_user_timezone(str(interaction.user.id))
        
        if not tz_data:
            await interaction.response.send_message(f"❌ {interaction.user.mention}, you haven't set your timezone yet. Use `/settime` to set it.", ephemeral=True)
            return
        
        current_time = self.get_current_time(tz_data["timezone"])
        flag = self.country_code_to_flag(tz_data.get("country_code", ""))
        offset = self.get_utc_offset(tz_data["timezone"])
        if offset >= 0:
            offset_str = f"UTC+{int(offset)}" if offset == int(offset) else f"UTC+{offset:.1f}"
        else:
            offset_str = f"UTC{int(offset)}" if offset == int(offset) else f"UTC{offset:.1f}"
        location_display = f"{tz_data['city']}, {tz_data['country']}" if tz_data.get('city') else tz_data['country']
        await interaction.response.send_message(f"**{interaction.user.display_name}** — {current_time}\n└ {flag} {location_display} ({offset_str})")
    
    @app_commands.command(name="time", description="Show a user's local time")
    @app_commands.describe(member="The member to check the time for (leave empty for yourself)")
    async def time(self, interaction: discord.Interaction, member: discord.Member = None):
        """Show a user's local time."""
        if member is None:
            member = interaction.user
        
        tz_data = get_user_timezone(str(member.id))
        
        if not tz_data:
            if member == interaction.user:
                await interaction.response.send_message(f"❌ You haven't set your timezone yet. Use `/settime` to set it.", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ **{member.display_name}** hasn't set their timezone yet.", ephemeral=True)
            return
        
        current_time = self.get_current_time(tz_data["timezone"])
        flag = self.country_code_to_flag(tz_data.get("country_code", ""))
        offset = self.get_utc_offset(tz_data["timezone"])
        if offset >= 0:
            offset_str = f"UTC+{int(offset)}" if offset == int(offset) else f"UTC+{offset:.1f}"
        else:
            offset_str = f"UTC{int(offset)}" if offset == int(offset) else f"UTC{offset:.1f}"
        location_display = f"{tz_data['city']}, {tz_data['country']}" if tz_data.get('city') else tz_data['country']
        await interaction.response.send_message(f"**{member.display_name}** — {current_time}\n└ {flag} {location_display} ({offset_str})")
    
    @app_commands.command(name="removetime", description="Remove your timezone setting")
    async def removetime(self, interaction: discord.Interaction):
        """Remove your timezone setting."""
        tz_data = get_user_timezone(str(interaction.user.id))
        
        if not tz_data:
            await interaction.response.send_message(f"ℹ️ {interaction.user.mention}, you don't have a timezone set.", ephemeral=True)
            return
        
        success = remove_user_timezone(str(interaction.user.id))
        
        if success:
            await interaction.response.send_message(f"✅ {interaction.user.mention}, your timezone has been removed.")
            # Auto-refresh the embed if one exists for this guild
            await self.refresh_guild_embed(interaction.guild)
        else:
            await interaction.response.send_message("❌ Failed to remove your timezone. Please try again later.")
    
    @app_commands.command(name="alltimes", description="Show an auto-updating embed with all members' local times")
    @slash_role_check(config.ADMIN_ROLE_ID, config.MOD_ROLE_ID)
    async def alltimes(self, interaction: discord.Interaction):
        """Show an auto-updating embed with all users' local times."""
        embed, total_pages = self.create_times_embed(interaction.guild, page=0)
        await interaction.response.send_message(embed=embed)
        
        # Get the message we just sent - fetch it from channel to get a proper Message object
        # that doesn't rely on interaction webhook tokens (which expire after 15 mins)
        interaction_response = await interaction.original_response()
        message = await interaction.channel.fetch_message(interaction_response.id)
        
        # Store the message for auto-updates with page tracking (in memory)
        self.updating_messages[interaction.guild.id] = {
            "message": message,
            "page": 0
        }
        
        # Persist to database for survival across restarts
        save_timezone_embed(
            str(interaction.guild.id),
            str(interaction.channel.id),
            str(message.id),
            0
        )
        
        # Add navigation reactions if there are multiple pages
        if total_pages > 1:
            await message.add_reaction("⬅️")
            await message.add_reaction("➡️")

async def setup(bot):
    await bot.add_cog(Timezone(bot))
