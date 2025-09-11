import discord
from discord.ext import commands, tasks
from discord.ui import View, Button
import sqlite3
import aiohttp
import asyncio
import re
from dotenv import load_dotenv
from urllib.parse import quote_plus
from database import get_guild_settings
from utils.helpers import log_to_channel
from utils.twitch_utils import (
    get_twitch_app_token, 
    twitch_get_user_by_login,
    refresh_streamer_token,
    ban_queue
)
import config

load_dotenv()

def role_check(*role_ids):
    """Check if user has any of the specified roles."""
    def predicate(ctx):
        return any(role.id in role_ids for role in ctx.author.roles)
    return commands.check(predicate)

class Twitch(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sync_twitch_usernames.start()
    
    def cog_unload(self):
        self.sync_twitch_usernames.cancel()
    
    @tasks.loop(hours=6)
    async def sync_twitch_usernames(self):
        """Sync stored twitch_id -> twitch_username for all users."""
        conn = sqlite3.connect(config.DB_FILE, timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT twitch_id FROM users WHERE twitch_id IS NOT NULL AND twitch_id != ''")
        rows = cur.fetchall()
        conn.close()
        ids = [r[0] for r in rows if r and r[0]]
        
        if not ids:
            return
        
        batch_size = 100
        for i in range(0, len(ids), batch_size):
            batch = ids[i:i+batch_size]
            token = await get_twitch_app_token()
            headers = {"Client-ID": config.TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
            
            params = [("id", tid) for tid in batch]
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.twitch.tv/helix/users", params=params, headers=headers) as resp:
                    try:
                        data = await resp.json()
                    except Exception:
                        data = {}
            
            for u in data.get("data", []):
                tid = u.get("id")
                login = u.get("login")
                if not tid or not login:
                    continue
                try:
                    conn = sqlite3.connect(config.DB_FILE, timeout=10)
                    cur = conn.cursor()
                    cur.execute("UPDATE users SET twitch_username = ? WHERE twitch_id = ?", (login, tid))
                    if conn.total_changes > 0:
                        print(f"Updated username for twitch_id {tid} -> {login}")
                        await log_to_channel(self.bot, f"[sync] Updated Twitch username for twitch_id {tid} -> {login}")
                    conn.commit()
                    conn.close()
                except Exception as e:
                    print("DB error during twitch sync:", e)
    
    @sync_twitch_usernames.before_loop
    async def before_sync_twitch_usernames(self):
        await self.bot.wait_until_ready()
    
    @commands.command()
    async def linktwitch(self, ctx):
        """Send OAuth link for viewers to connect their Twitch account."""
        if not config.CLIENT_ID or not config.REDIRECT_URI or str(config.REDIRECT_URI).strip().lower() in {"none", "null", ""}:
            try:
                await ctx.author.send("⚠️ OAuth not configured.")
            except Exception:
                await ctx.send("⚠️ OAuth not configured.")
            return
        
        encoded_redirect = quote_plus(config.REDIRECT_URI)
        url = (
            f"https://discord.com/api/oauth2/authorize"
            f"?client_id={config.CLIENT_ID}"
            f"&redirect_uri={encoded_redirect}"
            f"&response_type=code"
            f"&scope=identify%20connections"
        )
        
        view = View()
        view.add_item(Button(label="Link Twitch", url=url))
        
        try:
            await ctx.author.send("🔗 Click below to link your Twitch account:", view=view)
            await ctx.send(f"{ctx.author.mention}, check your DMs to link Twitch!")
        except discord.Forbidden:
            await ctx.send("❌ Couldn't DM you. Please enable DMs to receive the link.")
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def linktwitchstreamer(self, ctx):
        """Link Twitch streamer account with OAuth."""
        client_id = config.TWITCH_CLIENT_ID
        redirect_uri = config.TWITCH_STREAMER_REDIRECT_URI
        scopes = "channel:moderate moderator:read:banned_users"
        
        if not client_id or not redirect_uri or str(redirect_uri).strip().lower() in {"none", "null", ""}:
            try:
                await ctx.author.send("⚠️ Twitch OAuth for streamers is not configured.")
            except Exception:
                await ctx.send("⚠️ Twitch OAuth for streamers is not configured.")
            return
        
        encoded_redirect = quote_plus(redirect_uri)
        encoded_scopes = quote_plus(scopes)
        
        oauth_url = (
            f"https://id.twitch.tv/oauth2/authorize"
            f"?client_id={client_id}"
            f"&redirect_uri={encoded_redirect}"
            f"&response_type=code"
            f"&scope={encoded_scopes}"
            f"&state={ctx.author.id}"
        )
        
        view = View()
        view.add_item(Button(label="Link Twitch (Streamer)", url=oauth_url))
        
        try:
            await ctx.author.send("🔗 Click the button below to link your Twitch (Streamer):", view=view)
            await ctx.send(f"{ctx.author.mention}, I sent you a DM with the Twitch streamer link.")
        except discord.Forbidden:
            await ctx.send("❌ Couldn't DM you. Please enable DMs to receive the OAuth link.")
    
    @commands.command()
    async def twitch(self, ctx, member: discord.Member = None):
        """Show linked Twitch account for a member."""
        member = member or ctx.author
        conn = sqlite3.connect(config.DB_FILE, timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT twitch_username FROM users WHERE discord_id = ?", (str(member.id),))
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            await ctx.send(f"{member.display_name}'s Twitch: **{row[0]}**")
        else:
            await ctx.send(f"{member.display_name} has not linked a Twitch account.")
    
    @commands.command()
    async def unlinktwitch(self, ctx):
        """Unlink your Twitch account."""
        try:
            conn = sqlite3.connect(config.DB_FILE, timeout=10)
            cur = conn.cursor()
            cur.execute("UPDATE users SET twitch_username=NULL, twitch_id=NULL WHERE discord_id=?", (str(ctx.author.id),))
            changes = conn.total_changes
            conn.commit()
            conn.close()
            
            if changes > 0:
                msg = f"✅ {ctx.author.mention}, your Twitch account has been unlinked."
                await ctx.send(msg)
                await log_to_channel(self.bot, f"[unlinktwitch] {ctx.author} ({ctx.author.id}) — unlinked their Twitch account.")
            else:
                info = f"ℹ️ {ctx.author.mention}, no Twitch account was linked."
                await ctx.send(info)
                await log_to_channel(self.bot, f"[unlinktwitch] {ctx.author} ({ctx.author.id}) — attempted unlink but no linked account found.")
        except Exception as e:
            err_msg = "❌ Database error while unlinking your Twitch account."
            await ctx.send(err_msg)
            await log_to_channel(self.bot, f"[unlinktwitch] ERROR: {ctx.author} ({ctx.author.id}) — {e}")
            print(f"DB error in unlinktwitch: {e}")
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def unlinktwitchstreamer(self, ctx, identifier: str = None):
        """Unlink a streamer's Twitch account."""
        if not identifier:
            await ctx.send("Usage: `/unlinktwitchstreamer <twitch_id | @discord_mention | discord_id>`")
            return
        
        m = re.match(r"^<@!?(\d+)>$", identifier)
        if m:
            identifier = m.group(1)
        
        try:
            conn = sqlite3.connect(config.DB_FILE, timeout=10)
            cur = conn.cursor()
            
            cur.execute("SELECT discord_id FROM streamers WHERE twitch_id = ?", (identifier,))
            row = cur.fetchone()
            if row:
                discord_id = row[0]
                cur.execute("DELETE FROM streamers WHERE twitch_id = ?", (identifier,))
                cur.execute("UPDATE users SET twitch_username = NULL, twitch_id = NULL WHERE discord_id = ?", (str(discord_id),))
                conn.commit()
                conn.close()
                
                msg = (f"✅ {ctx.author.mention} unlinked streamer with Twitch ID `{identifier}` "
                       f"and cleared linked Twitch for Discord ID `{discord_id}`.")
                await ctx.send(msg)
                await log_to_channel(self.bot, f"[unlinktwitchstreamer] {ctx.author} ({ctx.author.id}) — {msg}")
                return
            
            cur.execute("SELECT twitch_id FROM streamers WHERE discord_id = ?", (str(identifier),))
            row2 = cur.fetchone()
            if row2:
                twitch_id = row2[0]
                cur.execute("DELETE FROM streamers WHERE discord_id = ?", (str(identifier),))
                cur.execute("UPDATE users SET twitch_username = NULL, twitch_id = NULL WHERE discord_id = ?", (str(identifier),))
                conn.commit()
                conn.close()
                
                msg = (f"✅ {ctx.author.mention} unlinked streamer for Discord ID `{identifier}` "
                       f"(Twitch ID: `{twitch_id}`) and cleared linked Twitch username.")
                await ctx.send(msg)
                await log_to_channel(self.bot, f"[unlinktwitchstreamer] {ctx.author} ({ctx.author.id}) — {msg}")
                return
            
            conn.close()
            info_msg = f"ℹ️ No streamer found with Twitch ID or Discord ID/mention `{identifier}`."
            await ctx.send(info_msg)
            await log_to_channel(self.bot, f"[unlinktwitchstreamer] {ctx.author} ({ctx.author.id}) — attempted unlink for `{identifier}`: not found")
            
        except Exception as e:
            err_msg = "❌ Database error while unlinking Twitch streamer."
            await ctx.send(err_msg)
            await log_to_channel(self.bot, f"[unlinktwitchstreamer] ERROR: {ctx.author} ({ctx.author.id}) — {e}")
            print(f"DB error in unlink_twitch_streamer: {e}")
    
    @commands.command()
    @role_check(config.ADMIN_ROLE_ID, config.MOD_ROLE_ID)
    async def gettwid(self, ctx, twitch_username: str):
        """Lookup Twitch numeric ID."""
        token = await get_twitch_app_token()
        headers = {"Client-ID": config.TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.twitch.tv/helix/users",
                params={"login": twitch_username},
                headers=headers
            ) as resp:
                data = await resp.json()
        
        if not data.get("data"):
            await ctx.send(f"❌ No Twitch user found for `{twitch_username}`")
            return
        
        user = data["data"][0]
        twitch_id = user["id"]
        display_name = user["display_name"]
        await ctx.send(f"✅ Twitch user `{display_name}` → ID `{twitch_id}`")
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def subscribeban(self, ctx, twitch_id: str):
        """Subscribe to Twitch ban events for a channel."""
        callback_url = config.TWITCH_CALLBACK_URL
        token = await get_twitch_app_token()
        
        headers = {
            "Client-ID": config.TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        body = {
            "type": "channel.ban",
            "version": "1",
            "condition": {"broadcaster_user_id": twitch_id},
            "transport": {
                "method": "webhook",
                "callback": callback_url,
                "secret": config.TWITCH_EVENTSUB_SECRET,
            },
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.twitch.tv/helix/eventsub/subscriptions",
                headers=headers,
                json=body,
            ) as resp:
                data = await resp.json()
        
        if "error" in data:
            await ctx.send(f"❌ Failed to subscribe: {data}")
        else:
            await ctx.send(f"✅ Subscribed to ban events for Twitch channel `{twitch_id}`")
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def unsubscribeban(self, ctx, identifier: str):
        """Unsubscribe from EventSub subscription."""
        token = await get_twitch_app_token()
        headers = {
            "Client-ID": config.TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {token}"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.twitch.tv/helix/eventsub/subscriptions",
                headers=headers
            ) as resp:
                subs_data = await resp.json()
            
            subs = subs_data.get("data", [])
            if not subs:
                await ctx.send("📭 No active subscriptions.")
                return
            
            to_delete = []
            for sub in subs:
                if sub["id"] == identifier or sub["condition"].get("broadcaster_user_id") == identifier:
                    to_delete.append(sub["id"])
            
            if not to_delete:
                await ctx.send(f"❌ No subscription found for `{identifier}`")
                return
            
            results = []
            for sub_id in to_delete:
                async with session.delete(
                    f"https://api.twitch.tv/helix/eventsub/subscriptions?id={sub_id}",
                    headers=headers
                ) as del_resp:
                    if del_resp.status == 204:
                        results.append(f"✅ Unsubscribed from `{sub_id}`")
                    else:
                        error_data = await del_resp.json()
                        results.append(f"❌ Failed to unsubscribe `{sub_id}`: {error_data}")
            
            await ctx.send("\n".join(results))
    
    @commands.command()
    @role_check(config.ADMIN_ROLE_ID, config.MOD_ROLE_ID)
    async def listsubs(self, ctx):
        """List active EventSub subscriptions."""
        token = await get_twitch_app_token()
        headers = {
            "Client-ID": config.TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {token}"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.twitch.tv/helix/eventsub/subscriptions",
                headers=headers
            ) as resp:
                data = await resp.json()
        
        subs = data.get("data", [])
        if not subs:
            await ctx.send("📭 No active subscriptions.")
            return
        
        msg_lines = []
        for sub in subs:
            sub_id = sub.get("id")
            sub_type = sub.get("type")
            broadcaster = sub.get("condition", {}).get("broadcaster_user_id")
            status = sub.get("status")
            msg_lines.append(f"• `{sub_id}` — {sub_type} for broadcaster `{broadcaster}` (status: {status})")
        
        await ctx.send("📋 Active Subscriptions:\n" + "\n".join(msg_lines))

async def setup(bot):
    await bot.add_cog(Twitch(bot))