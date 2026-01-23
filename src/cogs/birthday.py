import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime
import asyncio
from database import (
    get_user_birthday, set_user_birthday, remove_user_birthday, get_all_user_birthdays,
    save_birthday_embed, update_birthday_embed_page, remove_birthday_embed, get_all_birthday_embeds,
    get_birthdays_to_announce, update_birthday_announced, get_birthday_channel, set_birthday_channel,
    get_user_timezone
)
import pytz
import config

# Month names for display
MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]

# Days in each month (non-leap year)
DAYS_IN_MONTH = {
    1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31
}

def slash_role_check(*role_ids):
    """Check if user has any of the specified roles (for slash commands)."""
    async def predicate(interaction: discord.Interaction):
        return any(role.id in role_ids for role in interaction.user.roles)
    return app_commands.check(predicate)


class Birthday(commands.Cog):
    PAGE_RESET_DELAY = 20  # seconds before auto-reset to page 1

    def __init__(self, bot):
        self.bot = bot
        self.updating_messages = {}  # guild_id -> {"message": msg, "page": int}
        self.page_reset_tasks = {}  # guild_id -> asyncio.Task for auto-reset
        self.update_birthday_embeds.start()
        self.check_birthdays.start()

    def cog_unload(self):
        self.check_birthdays.cancel()
        self.update_birthday_embeds.cancel()
        for task in self.page_reset_tasks.values():
            task.cancel()

    async def schedule_page_reset(self, guild_id: int):
        """Schedule a page reset to page 1 after delay."""
        if guild_id in self.page_reset_tasks:
            self.page_reset_tasks[guild_id].cancel()

        async def reset_page():
            await asyncio.sleep(self.PAGE_RESET_DELAY)
            if guild_id in self.updating_messages:
                current_page = self.updating_messages[guild_id].get("page", 0)
                if current_page != 0:
                    self.updating_messages[guild_id]["page"] = 0
                    update_birthday_embed_page(str(guild_id), 0)

                    guild = self.bot.get_guild(guild_id)
                    if guild:
                        try:
                            message = self.updating_messages[guild_id]["message"]
                            embed, _ = self.create_birthdays_embed(guild, 0)
                            await message.edit(embed=embed)
                        except Exception as e:
                            print(f"Error resetting birthday page: {e}")

            if guild_id in self.page_reset_tasks:
                del self.page_reset_tasks[guild_id]

        self.page_reset_tasks[guild_id] = asyncio.create_task(reset_page())

    async def load_persisted_embeds(self):
        """Load persisted embed tracking from database on startup."""
        embeds = get_all_birthday_embeds()
        loaded_count = 0

        for embed_data in embeds:
            try:
                guild_id = int(embed_data["guild_id"])
                channel_id = int(embed_data["channel_id"])
                message_id = int(embed_data["message_id"])
                page = embed_data.get("page", 0)

                guild = self.bot.get_guild(guild_id)
                if not guild:
                    remove_birthday_embed(str(guild_id))
                    continue

                channel = guild.get_channel(channel_id)
                if not channel:
                    remove_birthday_embed(str(guild_id))
                    continue

                try:
                    message = await channel.fetch_message(message_id)
                    self.updating_messages[guild_id] = {
                        "message": message,
                        "page": page
                    }
                    loaded_count += 1
                except discord.NotFound:
                    remove_birthday_embed(str(guild_id))
                except discord.Forbidden:
                    remove_birthday_embed(str(guild_id))
            except Exception as e:
                print(f"Error loading birthday embed for guild {embed_data.get('guild_id')}: {e}")

        if loaded_count > 0:
            print(f"✅ Loaded {loaded_count} persisted birthday embed(s)")

    def format_birthday(self, day: int, month: int) -> str:
        """Format birthday as 'day Month' (e.g., '28 March')."""
        return f"{day} {MONTH_NAMES[month]}"
    
    def days_until_birthday(self, day: int, month: int) -> int:
        """Calculate days until the next occurrence of this birthday."""
        today = datetime.now()
        current_year = today.year
        
        try:
            birthday_this_year = datetime(current_year, month, day)
        except ValueError:
            # Handle Feb 29 on non-leap years
            birthday_this_year = datetime(current_year, month, 28)
        
        if birthday_this_year.date() < today.date():
            try:
                birthday_this_year = datetime(current_year + 1, month, day)
            except ValueError:
                birthday_this_year = datetime(current_year + 1, month, 28)
        
        delta = birthday_this_year.date() - today.date()
        return delta.days
    
    def create_birthdays_embed(self, guild, page: int = 0) -> tuple[discord.Embed, int]:
        """Create an embed showing upcoming birthdays sorted by proximity."""
        USERS_PER_PAGE = 10
        
        embed = discord.Embed(
            title="🎂 Upcoming Birthdays",
            color=discord.Color.purple()
        )
        
        all_birthdays = get_all_user_birthdays()
        
        if not all_birthdays:
            embed.description = "No birthdays set yet!\nUse `/setbirthday` to add yours!"
            return embed, 1
        
        member_data = []
        for bday_data in all_birthdays:
            discord_id = bday_data.get("discord_id")
            day = bday_data.get("day")
            month = bday_data.get("month")
            
            member = guild.get_member(int(discord_id))
            if member:
                days_until = self.days_until_birthday(day, month)
                member_data.append({
                    "member": member,
                    "day": day,
                    "month": month,
                    "days_until": days_until
                })
        
        if not member_data:
            embed.description = "No members with birthdays are in this server"
            return embed, 1
        
        # Sort by days until birthday (closest first)
        member_data.sort(key=lambda x: x["days_until"])
        
        # Calculate pagination
        total_members = len(member_data)
        total_pages = max(1, (total_members + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
        
        # Clamp page
        page = max(0, min(page, total_pages - 1))
        
        # Get members for current page
        start_idx = page * USERS_PER_PAGE
        end_idx = start_idx + USERS_PER_PAGE
        page_members = member_data[start_idx:end_idx]
        
        # Build embed description
        lines = []
        for data in page_members:
            birthday_str = self.format_birthday(data["day"], data["month"])
            lines.append(f"**{data['member'].display_name}** — {birthday_str}")
        
        embed.description = "\n".join(lines)
        
        if total_pages > 1:
            embed.set_footer(text=f"Page {page + 1}/{total_pages} • Use ⬅️ ➡️ to navigate")
        # else: default footer or empty
        
        return embed, total_pages

    @tasks.loop(hours=1)
    async def update_birthday_embeds(self):
        """Update all active birthday embed messages."""
        for guild_id, data in list(self.updating_messages.items()):
            try:
                guild = self.bot.get_guild(guild_id)
                if guild:
                    message = data["message"]
                    page = data.get("page", 0)
                    embed, _ = self.create_birthdays_embed(guild, page)
                    await message.edit(embed=embed)
            except discord.NotFound:
                del self.updating_messages[guild_id]
                remove_birthday_embed(str(guild_id))
            except Exception as e:
                print(f"Error updating birthday embed: {e}")

    @tasks.loop(minutes=5)
    async def check_birthdays(self):
        """Check for birthdays to announce based on user timezones."""
        # Get all users with birthdays (we need to check everyone's timezone)
        all_birthdays = get_all_user_birthdays()
        current_utc = datetime.now(pytz.UTC)
        
        for bday_data in all_birthdays:
            discord_id = bday_data["discord_id"]
            day = bday_data["day"]
            month = bday_data["month"]
            last_year = bday_data.get("last_announced_year", 0)
            
            # 1. Get user timezone
            tz_data = get_user_timezone(discord_id)
            if tz_data and tz_data.get("timezone"):
                user_tz_str = tz_data["timezone"]
            else:
                user_tz_str = "Australia/Sydney"  # Default
                
            try:
                user_tz = pytz.timezone(user_tz_str)
                user_now = current_utc.astimezone(user_tz)
                
                # Check if it's their birthday TODAY in their timezone
                if user_now.day == day and user_now.month == month:
                    # Check if already announced for this year (use user's year)
                    if last_year != user_now.year:
                        # ANNOUNCE!
                        await self.announce_birthday(discord_id, user_now.year, user_tz_str)
            except Exception as e:
                print(f"Error checking birthday for {discord_id}: {e}")

    @check_birthdays.before_loop
    async def before_check_birthdays(self):
        await self.bot.wait_until_ready()

    async def announce_birthday(self, discord_id: str, year: int, timezone_str: str):
        """Send birthday announcement to the configured channel."""
        # Update DB first to prevent double-pings if sending fails
        success = update_birthday_announced(discord_id, year)
        if not success:
            return

        # Find mutual guilds with the user to announce in
        # We need to find ONE valid channel to send the announcement.
        # Prioritize the channel set by /setbirthdaychannel.
        
        user = self.bot.get_user(int(discord_id))
        if not user:
            try:
                user = await self.bot.fetch_user(int(discord_id))
            except Exception:
                return # User not found at all
        
        # We need to find which guild to announce in. 
        # A user might be in multiple guilds the bot is in.
        # We check all mutual guilds for a configured birthday channel.
        
        for guild in self.bot.guilds:
            member = guild.get_member(int(discord_id))
            if not member:
                continue
                
            channel_id = get_birthday_channel(str(guild.id))
            if not channel_id:
                continue
                
            channel = guild.get_channel(int(channel_id))
            if not channel:
                continue
                
            # Send the message
            try:
                msg = (
                    f"🎂 **Happy Birthday {member.mention}!** 🥳\n"
                    f"Hope you have a fantastic day! ({timezone_str})"
                )
                await channel.send(msg)
            except Exception as e:
                print(f"Failed to send birthday msg in {guild.name}: {e}")

    @update_birthday_embeds.before_loop
    async def before_update_birthday_embeds(self):
        await self.bot.wait_until_ready()
        await self.load_persisted_embeds()

    async def refresh_guild_embed(self, guild):
        """Immediately refresh the embed for a specific guild."""
        if guild.id in self.updating_messages:
            try:
                data = self.updating_messages[guild.id]
                message = data["message"]
                page = data.get("page", 0)
                embed, total_pages = self.create_birthdays_embed(guild, page)
                await message.edit(embed=embed)
                
                if total_pages > 1:
                    existing_reactions = [str(r.emoji) for r in message.reactions]
                    if "⬅️" not in existing_reactions:
                        await message.add_reaction("⬅️")
                    if "➡️" not in existing_reactions:
                        await message.add_reaction("➡️")
            except discord.NotFound:
                del self.updating_messages[guild.id]
                remove_birthday_embed(str(guild.id))
            except Exception as e:
                print(f"Error refreshing birthday embed: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Handle reaction navigation for birthday embeds."""
        if payload.user_id == self.bot.user.id:
            return
        
        guild_id = payload.guild_id
        if guild_id not in self.updating_messages:
            return
        
        data = self.updating_messages[guild_id]
        if payload.message_id != data["message"].id:
            return
        
        emoji = str(payload.emoji)
        
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
        
        current_page = data.get("page", 0)
        guild = self.bot.get_guild(guild_id)
        
        if not guild:
            return
        
        _, total_pages = self.create_birthdays_embed(guild, current_page)
        
        if emoji == "⬅️":
            new_page = max(0, current_page - 1)
        else:
            new_page = min(total_pages - 1, current_page + 1)
        
        if new_page != current_page:
            self.updating_messages[guild_id]["page"] = new_page
            update_birthday_embed_page(str(guild_id), new_page)
            embed, _ = self.create_birthdays_embed(guild, new_page)
            
            try:
                await data["message"].edit(embed=embed)
            except Exception as e:
                print(f"Error updating birthday page: {e}")
            
            if new_page != 0:
                await self.schedule_page_reset(guild_id)
            else:
                if guild_id in self.page_reset_tasks:
                    self.page_reset_tasks[guild_id].cancel()
                    del self.page_reset_tasks[guild_id]
        
        try:
            channel = self.bot.get_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
            member = guild.get_member(payload.user_id)
            if member:
                await message.remove_reaction(payload.emoji, member)
        except Exception:
            pass
    
    # ===================== SLASH COMMANDS =====================
    
    @app_commands.command(name="setbirthday", description="Set your birthday")
    @app_commands.describe(
        day="Day of the month (1-31)",
        month="Month (1-12)"
    )
    async def setbirthday(self, interaction: discord.Interaction, day: int, month: int):
        """Set your birthday."""
        if month < 1 or month > 12:
            await interaction.response.send_message("❌ Invalid month. Please use 1-12.", ephemeral=True)
            return
        
        max_days = DAYS_IN_MONTH.get(month, 31)
        if day < 1 or day > max_days:
            await interaction.response.send_message(
                f"❌ Invalid day for {MONTH_NAMES[month]}. Please use 1-{max_days}.", 
                ephemeral=True
            )
            return
        
        success = set_user_birthday(
            str(interaction.user.id),
            interaction.user.display_name,
            day,
            month
        )
        
        if success:
            birthday_str = self.format_birthday(day, month)
            await interaction.response.send_message(f"✅ Birthday set to **{birthday_str}**!")
            await self.refresh_guild_embed(interaction.guild)
        else:
            await interaction.response.send_message("❌ Failed to save your birthday. Please try again later.", ephemeral=True)
    
    @app_commands.command(name="mybirthday", description="Show your birthday")
    async def mybirthday(self, interaction: discord.Interaction):
        """Show your birthday."""
        bday_data = get_user_birthday(str(interaction.user.id))
        
        if not bday_data:
            await interaction.response.send_message(
                "❌ You haven't set your birthday yet. Use `/setbirthday` to set it.", 
                ephemeral=True
            )
            return
        
        birthday_str = self.format_birthday(bday_data["day"], bday_data["month"])
        await interaction.response.send_message(f"**{interaction.user.display_name}** — {birthday_str}")
    
    @app_commands.command(name="birthday", description="Show a user's birthday")
    @app_commands.describe(member="The member to check the birthday for")
    async def birthday(self, interaction: discord.Interaction, member: discord.Member = None):
        """Show a user's birthday."""
        if member is None:
            member = interaction.user
        
        bday_data = get_user_birthday(str(member.id))
        
        if not bday_data:
            if member == interaction.user:
                await interaction.response.send_message(
                    "❌ You haven't set your birthday yet. Use `/setbirthday` to set it.", 
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"❌ **{member.display_name}** hasn't set their birthday yet.", 
                    ephemeral=True
                )
            return
        
        birthday_str = self.format_birthday(bday_data["day"], bday_data["month"])
        await interaction.response.send_message(f"**{member.display_name}** — {birthday_str}")
    
    @app_commands.command(name="removebirthday", description="Remove your birthday setting")
    async def removebirthday(self, interaction: discord.Interaction):
        """Remove your birthday setting."""
        bday_data = get_user_birthday(str(interaction.user.id))
        
        if not bday_data:
            await interaction.response.send_message(
                "ℹ️ You don't have a birthday set.", 
                ephemeral=True
            )
            return
        
        success = remove_user_birthday(str(interaction.user.id))
        
        if success:
            await interaction.response.send_message("✅ Your birthday has been removed.")
            await self.refresh_guild_embed(interaction.guild)
        else:
            await interaction.response.send_message("❌ Failed to remove your birthday. Please try again later.", ephemeral=True)
            
    @app_commands.command(name="setbirthdaychannel", description="Set the channel for birthday announcements")
    @slash_role_check(config.ADMIN_ROLE_ID, config.MOD_ROLE_ID)
    @app_commands.describe(channel="The text channel to send announcements to")
    async def setbirthdaychannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set the channel where birthday announcements will be sent."""
        success = set_birthday_channel(str(interaction.guild.id), str(channel.id))
        
        if success:
            await interaction.response.send_message(f"✅ Birthday announcements will now be sent to {channel.mention}")
        else:
            await interaction.response.send_message("❌ Failed to set birthday channel.", ephemeral=True)
    
    @app_commands.command(name="allbirthdays", description="Show all upcoming birthdays")
    @slash_role_check(config.ADMIN_ROLE_ID, config.MOD_ROLE_ID)
    async def allbirthdays(self, interaction: discord.Interaction):
        """Show an auto-updating embed with all upcoming birthdays."""
        embed, total_pages = self.create_birthdays_embed(interaction.guild, page=0)
        await interaction.response.send_message(embed=embed)
        
        interaction_response = await interaction.original_response()
        message = await interaction.channel.fetch_message(interaction_response.id)
        
        self.updating_messages[interaction.guild.id] = {
            "message": message,
            "page": 0
        }
        
        save_birthday_embed(
            str(interaction.guild.id),
            str(interaction.channel.id),
            str(message.id),
            0
        )
        
        if total_pages > 1:
            await message.add_reaction("⬅️")
            await message.add_reaction("➡️")


async def setup(bot):
    await bot.add_cog(Birthday(bot))
