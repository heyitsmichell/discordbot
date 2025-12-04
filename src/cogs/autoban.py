# cogs/autoban.py

# Disabled for now

# import os
# import sqlite3
# import logging
# import discord
# from discord.ext import commands

# DB_PATH = os.getenv("DB_PATH", "bot.db")
# LOG = logging.getLogger(__name__)

# class AutoBan(commands.Cog):
#     """Auto-ban any user who sends a message in the configured channel."""

#     def __init__(self, bot: commands.Bot):
#         self.bot = bot
#         self._ensure_table()

#     def _get_conn(self):
#         return sqlite3.connect(DB_PATH)

#     def _ensure_table(self):
#         with self._get_conn() as conn:
#             cur = conn.cursor()
#             cur.execute(
#                 """CREATE TABLE IF NOT EXISTS guild_settings (
#                     guild_id TEXT PRIMARY KEY
#                 )"""
#             )
#             # Check if column exists, add if missing
#             cur.execute("PRAGMA table_info(guild_settings);")
#             columns = [row[1] for row in cur.fetchall()]
#             if "autoban_channel_id" not in columns:
#                 cur.execute("ALTER TABLE guild_settings ADD COLUMN autoban_channel_id TEXT;")
#                 LOG.info("Added missing column 'autoban_channel_id'")
#             conn.commit()

#     def _set_autoban_channel(self, guild_id: int, channel_id: int):
#         with self._get_conn() as conn:
#             conn.execute(
#                 """INSERT INTO guild_settings (guild_id, autoban_channel_id)
#                    VALUES (?, ?)
#                    ON CONFLICT(guild_id) DO UPDATE SET autoban_channel_id=excluded.autoban_channel_id""",
#                 (str(guild_id), str(channel_id)),
#             )
#             conn.commit()

#     def _clear_autoban_channel(self, guild_id: int):
#         with self._get_conn() as conn:
#             conn.execute(
#                 "UPDATE guild_settings SET autoban_channel_id=NULL WHERE guild_id=?",
#                 (str(guild_id),),
#             )
#             conn.commit()

#     def _get_autoban_channel(self, guild_id: int):
#         with self._get_conn() as conn:
#             cur = conn.execute(
#                 "SELECT autoban_channel_id FROM guild_settings WHERE guild_id=?",
#                 (str(guild_id),),
#             )
#             row = cur.fetchone()
#             return int(row[0]) if row and row[0] else None

#     @commands.command(name="autoban_channel")
#     @commands.has_permissions(administrator=True)
#     async def autoban_channel(self, ctx, *, arg: str = None):
#         """Set or clear the autoban channel for this server."""

#         guild_id = str(ctx.guild.id)

#         if not arg:
#             await ctx.send("⚠️ Please mention a channel or type `clear` to disable.")
#             return

#         arg = arg.lower()

#         if arg in ["clear", "disable", "none"]:
#             with sqlite3.connect(DB_PATH) as conn:
#                 conn.execute(
#                     "UPDATE guild_settings SET autoban_channel_id=NULL WHERE guild_id=?",
#                     (guild_id,),
#                 )
#                 conn.commit()
#             await ctx.send("✅ Autobanning disabled for the selected channel.")
#             return

#         # Otherwise, try to parse as a channel
#         channel = None
#         if ctx.message.channel_mentions:
#             channel = ctx.message.channel_mentions[0]
#         else:
#             # Maybe they passed an ID
#             try:
#                 channel = await commands.TextChannelConverter().convert(ctx, arg)
#             except commands.ChannelNotFound:
#                 pass

#         if not channel:
#             await ctx.send("❌ Invalid channel. Please mention a channel or use `clear`.")
#             return

#         with sqlite3.connect(DB_PATH) as conn:
#             conn.execute(
#                 "INSERT INTO guild_settings (guild_id, autoban_channel_id) VALUES (?, ?) "
#                 "ON CONFLICT(guild_id) DO UPDATE SET autoban_channel_id=excluded.autoban_channel_id",
#                 (guild_id, str(channel.id)),
#             )
#             conn.commit()

#         await ctx.send(f"✅ Autobanning enabled for {channel.mention}.")

#     @commands.Cog.listener()
#     async def on_message(self, message: discord.Message):
#         if not message.guild or message.author.bot:
#             return

#         guild = message.guild
#         channel_id = self._get_autoban_channel(guild.id)
#         if not channel_id or message.channel.id != channel_id:
#             return

#         member = message.author
#         if member == guild.owner or member.guild_permissions.administrator:
#             return

#         try:
#             await message.delete()
#         except Exception:
#             pass

#         try:
#             await guild.ban(
#                 member,
#                 reason="Auto-ban: posted in autoban channel",
#                 delete_message_days=0,
#             )
#             LOG.info(f"Banned {member} in {guild.name} for posting in autoban channel")
#         except Exception as e:
#             LOG.error(f"Failed to autoban {member}: {e}")

# async def setup(bot: commands.Bot):
#     await bot.add_cog(AutoBan(bot))
