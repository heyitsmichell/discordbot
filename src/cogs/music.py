import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button
import asyncio
import os
import json
import time
import random
import logging
import urllib.parse
import urllib.request
import re
import concurrent.futures
from datetime import timedelta
import database

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

# Setup directory structure for local music storage
MUSIC_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'music')
MUSIC_FILES_DIR = os.path.join(MUSIC_DATA_DIR, 'files')
MUSIC_INDEX_FILE = os.path.join(MUSIC_DATA_DIR, 'library.json')

os.makedirs(MUSIC_FILES_DIR, exist_ok=True)


def load_music_index() -> dict:
    data = {"tracks": {}, "next_id": 1}
    if os.path.exists(MUSIC_INDEX_FILE):
        try:
            with open(MUSIC_INDEX_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "tracks" not in data:
                    data["tracks"] = {}
                if "next_id" not in data:
                    data["next_id"] = 1
        except Exception as e:
            logging.error(f"Failed to load music index from disk: {e}")

    # Sync/merge with Supabase cloud database
    try:
        cloud_tracks = database.get_all_music_tracks()
        max_id = int(data.get("next_id", 1)) - 1
        for ct in cloud_tracks:
            tid = str(ct.get("track_id"))
            if tid.isdigit() and int(tid) > max_id:
                max_id = int(tid)
            if tid not in data["tracks"]:
                filename = ct.get("filename", "")
                filepath = os.path.join(MUSIC_FILES_DIR, filename)
                data["tracks"][tid] = {
                    "id": tid,
                    "title": ct.get("title", ""),
                    "filename": filename,
                    "filepath": filepath,
                    "uploader_id": str(ct.get("uploader_id", "")),
                    "uploader_name": ct.get("uploader_name", ""),
                    "uploaded_at": int(ct.get("uploaded_at", 0)),
                    "duration": int(ct.get("duration", 0)),
                    "is_private": bool(ct.get("is_private", False))
                }
        data["next_id"] = max(max_id + 1, int(data.get("next_id", 1)))
    except Exception as e:
        logging.warning(f"Could not merge cloud tracks from Supabase: {e}")

    return data


def save_music_index(data: dict):
    try:
        with open(MUSIC_INDEX_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Failed to save music index: {e}")


def get_ffmpeg_path() -> str:
    if imageio_ffmpeg:
        try:
            exe = imageio_ffmpeg.get_ffmpeg_exe()
            if exe and os.path.exists(exe) and os.access(exe, os.X_OK):
                return exe
        except Exception as e:
            logging.warning(f"Could not load bundled ffmpeg from imageio_ffmpeg: {e}")

    import shutil
    for path in ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg']:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path

    which_ffmpeg = shutil.which('ffmpeg')
    if which_ffmpeg and os.access(which_ffmpeg, os.X_OK):
        return which_ffmpeg

    return 'ffmpeg'


def ensure_opus_loaded():
    if not discord.opus.is_loaded():
        try:
            discord.opus._load_default()
        except Exception:
            pass
    if not discord.opus.is_loaded():
        import ctypes.util
        found = ctypes.util.find_library('opus')
        for path in [
            found,
            '/usr/lib/x86_64-linux-gnu/libopus.so.0',
            '/usr/lib/aarch64-linux-gnu/libopus.so.0',
            '/usr/lib64/libopus.so.0',
            '/lib/x86_64-linux-gnu/libopus.so.0',
            '/opt/homebrew/lib/libopus.dylib',
            '/opt/homebrew/lib/libopus.0.dylib',
            '/usr/local/lib/libopus.dylib',
            '/usr/local/lib/libopus.0.dylib',
            'libopus.dylib',
            'libopus.so.0',
            'libopus.so',
            'opus.dll'
        ]:
            if path and (os.path.exists(path) or path in ('libopus.so.0', 'libopus.so', 'opus.dll', found)):
                try:
                    discord.opus.load_opus(path)
                    logging.info(f"Loaded Opus library from {path}")
                    break
                except Exception as e:
                    logging.warning(f"Failed to load Opus from {path}: {e}")

ensure_opus_loaded()


def get_ydl_opts(extract_flat: bool = False) -> dict:
    opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'extract_flat': extract_flat,
        'extractor_args': {
            'youtube': {
                'player_client': ['mweb', 'android', 'ios']
            }
        }
    }
    cookies_browser = os.getenv('YT_COOKIES_BROWSER')
    cookies_file = os.getenv('YT_COOKIES_FILE')
    if cookies_browser:
        opts['cookiesfrombrowser'] = (cookies_browser,)
    elif cookies_file and os.path.exists(cookies_file):
        opts['cookiefile'] = cookies_file
    return opts


def format_duration(seconds: int | float) -> str:
    if not seconds or seconds <= 0:
        return "Unknown / Live"
    seconds = int(seconds)
    if seconds >= 3600:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02}:{minutes:02}:{secs:02}"
    else:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:02}:{secs:02}"


class NowPlayingView(View):
    def __init__(self, player: 'GuildMusicPlayer'):
        super().__init__(timeout=None)
        self.player = player
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        
        # Pause/Resume Button
        pause_label = "Resume" if self.player.is_paused else "Pause"
        pause_style = discord.ButtonStyle.green if self.player.is_paused else discord.ButtonStyle.secondary
        pause_emoji = "▶️" if self.player.is_paused else "⏸️"
        
        btn_pause = Button(label=pause_label, style=pause_style, emoji=pause_emoji, custom_id=f"np_pause_{self.player.guild_id}")
        btn_pause.callback = self.on_pause_resume
        self.add_item(btn_pause)

        # Skip Button
        btn_skip = Button(label="Skip", style=discord.ButtonStyle.primary, emoji="⏭️", custom_id=f"np_skip_{self.player.guild_id}")
        btn_skip.callback = self.on_skip
        self.add_item(btn_skip)

        # Loop Button
        loop_emoji = "🔁" if self.player.loop_mode == "QUEUE" else ("🔂" if self.player.loop_mode == "TRACK" else "➡️")
        loop_style = discord.ButtonStyle.success if self.player.loop_mode != "OFF" else discord.ButtonStyle.secondary
        btn_loop = Button(label=f"Loop: {self.player.loop_mode}", style=loop_style, emoji=loop_emoji, custom_id=f"np_loop_{self.player.guild_id}")
        btn_loop.callback = self.on_loop
        self.add_item(btn_loop)

        # Stop Button
        btn_stop = Button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️", custom_id=f"np_stop_{self.player.guild_id}")
        btn_stop.callback = self.on_stop
        self.add_item(btn_stop)

    async def on_pause_resume(self, interaction: discord.Interaction):
        if not self.player.voice_client or not self.player.current_track:
            return await interaction.response.send_message("❌ Nothing is currently playing.", ephemeral=True)
        
        if self.player.is_paused:
            self.player.voice_client.resume()
            self.player.is_paused = False
            await interaction.response.send_message("▶️ Resumed playback!", ephemeral=True)
        else:
            self.player.voice_client.pause()
            self.player.is_paused = True
            await interaction.response.send_message("⏸️ Paused playback!", ephemeral=True)
        
        self.update_buttons()
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

    async def on_skip(self, interaction: discord.Interaction):
        if not self.player.voice_client or not self.player.current_track:
            return await interaction.response.send_message("❌ Nothing is currently playing.", ephemeral=True)
        
        await interaction.response.send_message("⏭️ Skipped current track!", ephemeral=True)
        self.player.voice_client.stop()

    async def on_loop(self, interaction: discord.Interaction):
        if self.player.loop_mode == "OFF":
            self.player.loop_mode = "TRACK"
        elif self.player.loop_mode == "TRACK":
            self.player.loop_mode = "QUEUE"
        else:
            self.player.loop_mode = "OFF"
            
        self.update_buttons()
        await interaction.response.send_message(f"🔁 Loop mode set to: **{self.player.loop_mode}**", ephemeral=True)
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

    async def on_stop(self, interaction: discord.Interaction):
        if not self.player.voice_client:
            return await interaction.response.send_message("❌ Bot is not in a voice channel.", ephemeral=True)
        
        self.player.queue.clear()
        if self.player.voice_client.is_playing() or self.player.voice_client.is_paused():
            self.player.voice_client.stop()
            
        await interaction.response.send_message("⏹️ Stopped playback and cleared the queue.", ephemeral=True)


class GuildMusicPlayer:
    def __init__(self, bot: commands.Bot, guild_id: int):
        self.bot = bot
        self.guild_id = guild_id
        self.queue: list[dict] = []
        self.current_track: dict | None = None
        self.voice_client: discord.VoiceClient | None = None
        self.is_playing: bool = False
        self.is_paused: bool = False
        self.loop_mode: str = "OFF"  # OFF, TRACK, QUEUE
        self.volume: float = 1.0
        self.inactivity_task: asyncio.Task | None = None
        self.channel_for_updates: discord.TextChannel | None = None

    async def connect(self, voice_channel: discord.VoiceChannel):
        if self.voice_client and self.voice_client.is_connected():
            if self.voice_client.channel.id != voice_channel.id:
                await self.voice_client.move_to(voice_channel)
        else:
            self.voice_client = await voice_channel.connect()
        self.reset_inactivity_timer()

    async def disconnect(self):
        if self.inactivity_task:
            self.inactivity_task.cancel()
            self.inactivity_task = None
        self.queue.clear()
        self.current_track = None
        self.is_playing = False
        self.is_paused = False
        if self.voice_client and self.voice_client.is_connected():
            await self.voice_client.disconnect()
        self.voice_client = None

    def reset_inactivity_timer(self):
        if self.inactivity_task:
            self.inactivity_task.cancel()
        self.inactivity_task = self.bot.loop.create_task(self.inactivity_check())

    async def inactivity_check(self):
        await asyncio.sleep(300)  # 5 minutes idle timeout
        if not self.is_playing and (not self.voice_client or not self.voice_client.is_playing()):
            if self.channel_for_updates:
                try:
                    await self.channel_for_updates.send("💤 Left voice channel due to 5 minutes of inactivity.")
                except Exception:
                    pass
            await self.disconnect()

    def add_to_queue(self, track: dict):
        self.queue.append(track)
        if self.inactivity_task:
            self.inactivity_task.cancel()

    def create_audio_source(self, track: dict) -> discord.AudioSource:
        ffmpeg_executable = get_ffmpeg_path()
        if track.get('is_local'):
            source = discord.FFmpegPCMAudio(track['source'], executable=ffmpeg_executable)
        else:
            before_opts = '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
            http_headers = track.get('http_headers')
            if http_headers and isinstance(http_headers, dict):
                user_agent = http_headers.get('User-Agent')
                if user_agent:
                    before_opts += f' -user_agent "{user_agent}"'
                headers_str = "".join(f"{k}: {v}\r\n" for k, v in http_headers.items() if k.lower() != 'user-agent')
                if headers_str:
                    before_opts += f' -headers "{headers_str}"'

            ffmpeg_options = {
                'before_options': before_opts,
                'options': '-vn'
            }
            source = discord.FFmpegPCMAudio(track['source'], executable=ffmpeg_executable, **ffmpeg_options)
        
        return discord.PCMVolumeTransformer(source, volume=self.volume)

    def after_play_callback(self, error):
        if error:
            logging.error(f"Error playing track {self.current_track.get('title') if self.current_track else 'unknown'}: {error}")
        asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

    async def play_next(self):
        if not self.voice_client or not self.voice_client.is_connected():
            self.is_playing = False
            return

        # Handle loop modes
        if self.loop_mode == "TRACK" and self.current_track:
            track_to_play = self.current_track
        elif self.loop_mode == "QUEUE" and self.current_track:
            self.queue.append(self.current_track)
            if self.queue:
                track_to_play = self.queue.pop(0)
            else:
                track_to_play = None
        else:
            if self.queue:
                track_to_play = self.queue.pop(0)
            else:
                track_to_play = None

        if not track_to_play:
            self.current_track = None
            self.is_playing = False
            self.is_paused = False
            self.reset_inactivity_timer()
            return

        self.current_track = track_to_play
        self.is_playing = True
        self.is_paused = False
        if self.inactivity_task:
            self.inactivity_task.cancel()

        # Check if we need to refresh stream URL (for non-local tracks older than 1 hour or expired URLs)
        if not track_to_play.get('is_local') and yt_dlp:
            try:
                loop = asyncio.get_event_loop()
                ydl_opts = get_ydl_opts()
                info = await loop.run_in_executor(
                    None,
                    lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(track_to_play['webpage_url'], download=False)
                )
                if not info:
                    raise ValueError("Empty info returned")
                entry = info['entries'][0] if 'entries' in info and info['entries'] else info
                if entry and entry.get('url'):
                    track_to_play['source'] = entry['url']
                    if entry.get('http_headers'):
                        track_to_play['http_headers'] = entry.get('http_headers')
            except Exception as e:
                logging.warning(f"Could not refresh YouTube stream URL for {track_to_play.get('title')}: {e}")

        try:
            source = self.create_audio_source(track_to_play)
            self.voice_client.play(source, after=self.after_play_callback)
            
            # Send Now Playing announcement
            if self.channel_for_updates:
                embed = discord.Embed(
                    title="🎶 Now Playing",
                    description=f"**[{track_to_play['title']}]({track_to_play.get('webpage_url', '')})**" if not track_to_play.get('is_local') else f"**{track_to_play['title']}** (Local Upload)",
                    color=discord.Color.from_rgb(255, 105, 180)
                )
                embed.add_field(name="⏱️ Duration", value=format_duration(track_to_play.get('duration', 0)), inline=True)
                embed.add_field(name="👤 Requested By", value=track_to_play.get('uploader_name', 'Unknown'), inline=True)
                if track_to_play.get('is_local'):
                    embed.set_footer(text="📁 Played from Bot Local Music Library")
                else:
                    embed.set_footer(text="🌐 Streamed via YouTube / Web")
                
                view = NowPlayingView(self)
                try:
                    await self.channel_for_updates.send(embed=embed, view=view)
                except Exception:
                    pass
        except Exception as e:
            logging.error(f"Failed to play track {track_to_play.get('title')}: {e}")
            if self.channel_for_updates:
                try:
                    await self.channel_for_updates.send(f"⚠️ Failed to play **{track_to_play.get('title')}**: `{e}`. Skipping to next...")
                except Exception:
                    pass
            await self.play_next()


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: dict[int, GuildMusicPlayer] = {}

    def get_player(self, guild: discord.Guild) -> GuildMusicPlayer:
        if guild.id not in self.players:
            self.players[guild.id] = GuildMusicPlayer(self.bot, guild.id)
        return self.players[guild.id]

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        # If the bot itself was forcibly disconnected from voice by a moderator or server event
        if member.id == self.bot.user.id:
            if before.channel and not after.channel:
                if before.channel.guild.id in self.players:
                    player = self.players[before.channel.guild.id]
                    await player.disconnect()
            return

        # If a user left the channel the bot is currently inside
        if before.channel and member.id != self.bot.user.id:
            if before.channel.guild.id in self.players:
                player = self.players[before.channel.guild.id]
                if player.voice_client and player.voice_client.channel and player.voice_client.channel.id == before.channel.id:
                    # Check if only bots remain in the channel
                    non_bots = [m for m in before.channel.members if not m.bot]
                    if len(non_bots) == 0:
                        if player.channel_for_updates:
                            try:
                                await player.channel_for_updates.send("💤 All users left the voice channel. Disconnecting to save resources.")
                            except Exception:
                                pass
                        await player.disconnect()

def fetch_spotify_queries(query: str) -> list[str]:
    """Extract clean search strings (Song Title + Artist) from a Spotify URL."""
    queries = []
    try:
        req = urllib.request.Request(
            query,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        if "/track/" in query:
            i = html.find('<title>')
            j = html.find('</title>', i)
            if i != -1 and j != -1:
                html_title = html[i+7:j].strip().replace(' | Spotify', '').replace(' - song and lyrics by ', ' - ').replace(' - Song by ', ' - ')
                if html_title and "Spotify" not in html_title:
                    return [html_title]

            try:
                oembed_url = f"https://open.spotify.com/oembed?url={urllib.parse.quote(query)}"
                with urllib.request.urlopen(urllib.request.Request(oembed_url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=5) as oresp:
                    otitle = json.loads(oresp.read().decode()).get("title")
                    if otitle:
                        return [otitle]
            except Exception:
                pass

        elif "/playlist/" in query or "/album/" in query:
            track_ids = []
            for tid in re.findall(r'https://open\.spotify\.com/track/([a-zA-Z0-9]{22})', html):
                if tid not in track_ids:
                    track_ids.append(tid)

            if not track_ids:
                try:
                    oembed_url = f"https://open.spotify.com/oembed?url={urllib.parse.quote(query)}"
                    with urllib.request.urlopen(urllib.request.Request(oembed_url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=5) as oresp:
                        otitle = json.loads(oresp.read().decode()).get("title")
                        if otitle:
                            return [otitle]
                except Exception:
                    pass
                return []

            def get_otitle(tid):
                try:
                    oembed_url = f"https://open.spotify.com/oembed?url=https://open.spotify.com/track/{tid}"
                    with urllib.request.urlopen(urllib.request.Request(oembed_url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=5) as oresp:
                        return json.loads(oresp.read().decode()).get("title")
                except Exception:
                    return None

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                results = list(executor.map(get_otitle, track_ids[:15]))

            queries = [r for r in results if r]
    except Exception as e:
        logging.warning(f"Failed to fetch Spotify metadata for '{query}': {e}")

    return queries


    async def extract_web_track(self, query: str, requester: discord.Member) -> list[dict]:
        if not yt_dlp:
            raise RuntimeError("yt-dlp is not installed or available on this bot.")

        loop = asyncio.get_event_loop()
        ydl_opts = get_ydl_opts()

        is_url = query.startswith("http://") or query.startswith("https://")

        # Check for Spotify links and bridge via YouTube search
        if is_url and "spotify.com/" in query:
            spotify_queries = await loop.run_in_executor(None, lambda: fetch_spotify_queries(query))
            if not spotify_queries:
                raise RuntimeError("Could not extract track metadata from that Spotify link.")

            all_tracks = []
            for sq in spotify_queries:
                try:
                    info = await loop.run_in_executor(
                        None,
                        lambda sq=sq: yt_dlp.YoutubeDL(ydl_opts).extract_info(f"ytsearch1:{sq}", download=False)
                    )
                    if info:
                        entries = info.get('entries', [info]) if 'entries' in info else [info]
                        for entry in entries:
                            if not entry:
                                continue
                            all_tracks.append({
                                'title': entry.get('title', sq),
                                'source': entry.get('url'),
                                'webpage_url': entry.get('webpage_url', f"https://www.youtube.com/results?search_query={urllib.parse.quote(sq)}"),
                                'duration': entry.get('duration', 0),
                                'uploader_id': str(requester.id),
                                'uploader_name': requester.display_name,
                                'is_local': False,
                                'http_headers': entry.get('http_headers')
                            })
                except Exception as yt_err:
                    logging.warning(f"Failed to bridge Spotify song '{sq}' to YouTube: {yt_err}")

            if not all_tracks:
                raise RuntimeError(f"Could not find matching YouTube audio for Spotify link: {query}")
            return all_tracks

        search_query = query if is_url else f"ytsearch1:{query}"

        try:
            info = await loop.run_in_executor(
                None,
                lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(search_query, download=False)
            )
        except Exception as e:
            logging.error(f"YouTube extraction failed for '{query}': {e}")
            raise e

        if not info:
            return []

        entries = info.get('entries', [info]) if 'entries' in info else [info]
        tracks = []
        for entry in entries:
            if not entry:
                continue
            tracks.append({
                'title': entry.get('title', 'Unknown Title'),
                'source': entry.get('url'),
                'webpage_url': entry.get('webpage_url', query),
                'duration': entry.get('duration', 0),
                'uploader_id': str(requester.id),
                'uploader_name': requester.display_name,
                'is_local': False,
                'http_headers': entry.get('http_headers')
            })
        return tracks

    # ==================== Upload & Library Management Commands ====================

    @commands.hybrid_command(name="uploadmusic", description="Upload your own music file (.mp3, .wav, .flac, .ogg, .m4a) to the bot")
    @app_commands.describe(
        attachment="The audio file attachment to upload",
        title="Optional custom name for this song",
        private="Set to True if you want only yourself to be able to browse or play this song"
    )
    async def uploadmusic(self, ctx: commands.Context, attachment: discord.Attachment, title: str = None, private: bool = False):
        """Upload your own music to the bot's library."""
        allowed_extensions = ('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.mp4', '.webm')
        if not any(attachment.filename.lower().endswith(ext) for ext in allowed_extensions) and not (attachment.content_type and any(attachment.content_type.startswith(t) for t in ('audio/', 'video/'))):
            return await ctx.send("❌ Unsupported file format! Please upload an audio file (`.mp3`, `.wav`, `.ogg`, `.flac`, `.m4a`).", ephemeral=True)

        if attachment.size > 50 * 1024 * 1024:  # 50MB safety limit
            return await ctx.send("❌ File is too large! Please upload files under 50 MB.", ephemeral=True)

        await ctx.defer()

        index = load_music_index()
        track_id = str(index.get("next_id", 1))
        index["next_id"] = int(track_id) + 1

        clean_name = f"{track_id}_{int(time.time())}_{attachment.filename}"
        filepath = os.path.join(MUSIC_FILES_DIR, clean_name)

        try:
            await attachment.save(filepath)
        except Exception as e:
            logging.error(f"Failed to save uploaded music file: {e}")
            return await ctx.send(f"❌ Failed to save file: `{e}`")

        song_title = title.strip() if title else os.path.splitext(attachment.filename)[0]

        index["tracks"][track_id] = {
            "id": track_id,
            "title": song_title,
            "filename": clean_name,
            "filepath": filepath,
            "uploader_id": str(ctx.author.id),
            "uploader_name": ctx.author.display_name,
            "uploaded_at": int(time.time()),
            "duration": 0,
            "is_private": bool(private)
        }
        save_music_index(index)

        # Background sync to Supabase database table & storage bucket
        asyncio.create_task(asyncio.to_thread(database.upsert_music_track, index["tracks"][track_id]))
        asyncio.create_task(asyncio.to_thread(database.upload_music_storage, clean_name, filepath))

        embed = discord.Embed(
            title="✅ Music Uploaded Successfully!",
            description=f"**Title:** {song_title}\n**Track ID:** `#`{track_id}",
            color=discord.Color.green() if not private else discord.Color.gold()
        )
        embed.add_field(name="📁 Filename", value=f"`{attachment.filename}`", inline=True)
        embed.add_field(name="👤 Uploaded By", value=ctx.author.mention, inline=True)
        embed.add_field(name="🔒 Privacy", value="**Private** (Only you can play/browse)" if private else "**Public** (Shared with server)", inline=True)
        embed.set_footer(text=f"Use /play {song_title} or /play #{track_id} to play this song!")

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="listmusic", aliases=["mymusic", "uploads"], description="Show music tracks uploaded to the bot")
    @app_commands.describe(private_only="If True, only show your own private/personal uploads")
    async def listmusic(self, ctx: commands.Context, private_only: bool = False):
        """Show uploaded local music tracks."""
        if ctx.interaction:
            await ctx.defer()
        index = load_music_index()
        all_tracks = list(index.get("tracks", {}).values())

        is_admin = ctx.author.guild_permissions.administrator or (ctx.guild and ctx.author == ctx.guild.owner)
        visible_tracks = []
        for t in all_tracks:
            is_priv = t.get("is_private", False)
            is_owner = (t.get("uploader_id") == str(ctx.author.id))
            if private_only:
                if is_owner and is_priv:
                    visible_tracks.append(t)
            else:
                if not is_priv or is_owner or is_admin:
                    visible_tracks.append(t)

        if not visible_tracks:
            embed = discord.Embed(
                title="📂 Bot Music Library",
                description="No matching music files found! Use `/uploadmusic` to add some songs.",
                color=discord.Color.blurple()
            )
            return await ctx.send(embed=embed)

        title_suffix = " (Your Private Uploads)" if private_only else " (Local Uploads)"
        embed = discord.Embed(
            title=f"📂 Bot Music Library{title_suffix}",
            description=f"Showing **{len(visible_tracks)}** track(s). Play them anytime using `/play <title>` or `/play #<ID>`!",
            color=discord.Color.blurple()
        )

        for t in visible_tracks[:15]:
            priv_badge = "🔒 [Private] " if t.get("is_private") else ""
            embed.add_field(
                name=f"Track #{t['id']} — {priv_badge}{t['title']}",
                value=f"👤 Uploaded by **{t['uploader_name']}** • `<{t['filename']}>`",
                inline=False
            )

        if len(visible_tracks) > 15:
            embed.set_footer(text=f"And {len(visible_tracks) - 15} more track(s)...")

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="deletemusic", description="Delete an uploaded music track by ID or exact title")
    @app_commands.describe(track_identifier="The track ID (e.g. 1) or exact song title to delete")
    async def deletemusic(self, ctx: commands.Context, track_identifier: str):
        """Delete an uploaded track."""
        if ctx.interaction:
            await ctx.defer()
        index = load_music_index()
        tracks = index.get("tracks", {})

        target_id = None
        if track_identifier.startswith("#") and track_identifier[1:].isdigit():
            target_id = track_identifier[1:]
        elif track_identifier.isdigit() and track_identifier in tracks:
            target_id = track_identifier
        else:
            for tid, tinfo in tracks.items():
                if tinfo["title"].lower() == track_identifier.lower():
                    target_id = tid
                    break

        if not target_id or target_id not in tracks:
            return await ctx.send("❌ Track not found! Please check `/listmusic` for valid IDs and titles.", ephemeral=True)

        track_info = tracks[target_id]
        # Allow uploader or server administrator to delete
        is_mod = ctx.author.guild_permissions.administrator or (ctx.guild and ctx.author == ctx.guild.owner)
        if track_info["uploader_id"] != str(ctx.author.id) and not is_mod:
            return await ctx.send("❌ You do not have permission to delete this track. Only the uploader or an Admin can delete it.", ephemeral=True)

        # Remove file from disk
        try:
            if os.path.exists(track_info["filepath"]):
                os.remove(track_info["filepath"])
        except Exception as e:
            logging.warning(f"Could not delete physical file for track {target_id}: {e}")

        deleted_title = track_info["title"]
        deleted_filename = track_info.get("filename", "")
        del tracks[target_id]
        save_music_index(index)

        # Sync deletion to Supabase
        asyncio.create_task(asyncio.to_thread(database.delete_music_track, target_id, deleted_filename))

        await ctx.send(f"🗑️ Successfully deleted track **#{target_id} — {deleted_title}**.")

    @commands.hybrid_command(name="toggleprivacy", description="Toggle an uploaded track between Public and Private")
    @app_commands.describe(track_identifier="The track ID (e.g. 1) or exact song title to toggle")
    async def toggleprivacy(self, ctx: commands.Context, track_identifier: str):
        """Toggle an uploaded track's privacy status."""
        if ctx.interaction:
            await ctx.defer()
        index = load_music_index()
        tracks = index.get("tracks", {})

        target_id = None
        if track_identifier.startswith("#") and track_identifier[1:].isdigit():
            target_id = track_identifier[1:]
        elif track_identifier.isdigit() and track_identifier in tracks:
            target_id = track_identifier
        else:
            for tid, tinfo in tracks.items():
                if tinfo["title"].lower() == track_identifier.lower():
                    target_id = tid
                    break

        if not target_id or target_id not in tracks:
            return await ctx.send("❌ Track not found! Please check `/listmusic` for valid IDs and titles.", ephemeral=True)

        track_info = tracks[target_id]
        is_mod = ctx.author.guild_permissions.administrator or (ctx.guild and ctx.author == ctx.guild.owner)
        if track_info["uploader_id"] != str(ctx.author.id) and not is_mod:
            return await ctx.send("❌ You do not have permission to modify this track's privacy. Only the uploader or an Admin can change it.", ephemeral=True)

        track_info["is_private"] = not track_info.get("is_private", False)
        save_music_index(index)

        # Sync privacy status to Supabase
        asyncio.create_task(asyncio.to_thread(database.upsert_music_track, track_info))

        status = "🔒 **Private** (Only you can play/browse)" if track_info["is_private"] else "🌐 **Public** (Shared with server)"
        await ctx.send(f"✅ Privacy updated for track **#{target_id} — {track_info['title']}**:\nNew Status: {status}")

    # ==================== Playback Commands ====================

    @commands.hybrid_command(name="join", description="Make the bot join your current voice channel")
    async def join(self, ctx: commands.Context):
        """Join author's voice channel."""
        if ctx.interaction:
            await ctx.defer()

        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("❌ You must be in a voice channel first!", ephemeral=True)

        player = self.get_player(ctx.guild)
        player.channel_for_updates = ctx.channel
        try:
            await player.connect(ctx.author.voice.channel)
            await ctx.send(f"🔊 Joined **{ctx.author.voice.channel.name}**!")
        except Exception as e:
            logging.error(f"Voice connect error: {e}")
            await ctx.send(f"❌ Could not connect to voice: `{e}`")

    @commands.hybrid_command(name="leave", aliases=["disconnect"], description="Disconnect the bot from voice and clear the queue")
    async def leave(self, ctx: commands.Context):
        """Leave voice channel."""
        if ctx.interaction:
            await ctx.defer()

        player = self.get_player(ctx.guild)
        if not player.voice_client or not player.voice_client.is_connected():
            return await ctx.send("❌ Bot is not currently in a voice channel.", ephemeral=True)

        channel_name = player.voice_client.channel.name
        await player.disconnect()
        await ctx.send(f"👋 Disconnected from **{channel_name}** and cleared the queue.")

    @commands.hybrid_command(name="play", aliases=["p"], description="Play a local uploaded song, YouTube link, search query, or attached file")
    @app_commands.describe(
        query="Song title from local library, YouTube URL, or search query",
        attachment="Optional audio file attachment to play directly",
        private="Set to True if uploading via attachment and you want it marked Private"
    )
    async def play(self, ctx: commands.Context, query: str = None, attachment: discord.Attachment = None, private: bool = False):
        """Play audio from upload, library, or YouTube."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("❌ You must be inside a voice channel to play music!", ephemeral=True)

        if not query and not attachment:
            return await ctx.send("❌ Please provide either a song title/URL/query or attach an audio file to play!", ephemeral=True)

        await ctx.defer()

        player = self.get_player(ctx.guild)
        player.channel_for_updates = ctx.channel
        if not player.voice_client or not player.voice_client.is_connected():
            await player.connect(ctx.author.voice.channel)

        tracks_to_add = []

        # 1. Check if attachment is provided directly
        if attachment:
            allowed_extensions = ('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.mp4', '.webm')
            if not any(attachment.filename.lower().endswith(ext) for ext in allowed_extensions) and not (attachment.content_type and any(attachment.content_type.startswith(t) for t in ('audio/', 'video/'))):
                return await ctx.send("❌ Unsupported attachment format! Please attach an audio file.")

            # Save temporarily or into library
            index = load_music_index()
            track_id = str(index.get("next_id", 1))
            index["next_id"] = int(track_id) + 1
            clean_name = f"{track_id}_{int(time.time())}_{attachment.filename}"
            filepath = os.path.join(MUSIC_FILES_DIR, clean_name)

            try:
                await attachment.save(filepath)
                song_title = os.path.splitext(attachment.filename)[0]
                index["tracks"][track_id] = {
                    "id": track_id,
                    "title": song_title,
                    "filename": clean_name,
                    "filepath": filepath,
                    "uploader_id": str(ctx.author.id),
                    "uploader_name": ctx.author.display_name,
                    "uploaded_at": int(time.time()),
                    "duration": 0,
                    "is_private": bool(private)
                }
                save_music_index(index)

                # Background sync to Supabase
                asyncio.create_task(asyncio.to_thread(database.upsert_music_track, index["tracks"][track_id]))
                asyncio.create_task(asyncio.to_thread(database.upload_music_storage, clean_name, filepath))

                tracks_to_add.append({
                    'title': song_title,
                    'source': filepath,
                    'webpage_url': '',
                    'duration': 0,
                    'uploader_id': str(ctx.author.id),
                    'uploader_name': ctx.author.display_name,
                    'is_local': True
                })
            except Exception as e:
                return await ctx.send(f"❌ Failed to download attachment: `{e}`")

        # 2. Check query against local library or YouTube
        if query:
            index = load_music_index()
            local_match = None

            # Check if query matches ID (#1 or 1)
            clean_query = query.strip()
            if clean_query.startswith("#") and clean_query[1:].isdigit():
                tid = clean_query[1:]
                if tid in index["tracks"]:
                    local_match = index["tracks"][tid]
            elif clean_query.isdigit() and clean_query in index["tracks"]:
                local_match = index["tracks"][clean_query]
            else:
                # Search exact or partial title
                for tid, tinfo in index["tracks"].items():
                    if tinfo["title"].lower() == clean_query.lower():
                        local_match = tinfo
                        break
                if not local_match:
                    for tid, tinfo in index["tracks"].items():
                        if clean_query.lower() in tinfo["title"].lower():
                            local_match = tinfo
                            break

            if local_match:
                is_priv = local_match.get("is_private", False)
                is_owner = (local_match.get("uploader_id") == str(ctx.author.id))
                is_admin = ctx.author.guild_permissions.administrator or (ctx.guild and ctx.author == ctx.guild.owner)
                if is_priv and not is_owner and not is_admin:
                    return await ctx.send(f"🔒 **{local_match['title']}** (Track #{local_match['id']}) is marked as **Private** by its uploader (`{local_match['uploader_name']}`) and cannot be played by others.", ephemeral=True)

                # If local file is missing, attempt auto-recovery from Supabase storage
                if not os.path.exists(local_match["filepath"]):
                    await ctx.send(f"📥 Downloading **{local_match['title']}** from Supabase cloud storage...")
                    await asyncio.to_thread(database.download_music_storage, local_match["filename"], local_match["filepath"])

                # Ensure physical file still exists after attempted download
                if os.path.exists(local_match["filepath"]):
                    tracks_to_add.append({
                        'title': local_match["title"],
                        'source': local_match["filepath"],
                        'webpage_url': '',
                        'duration': local_match.get("duration", 0),
                        'uploader_id': local_match["uploader_id"],
                        'uploader_name': local_match["uploader_name"],
                        'is_local': True
                    })
                else:
                    await ctx.send(f"⚠️ Cloud file for **{local_match['title']}** was missing. Searching YouTube instead...")
                    local_match = None

            if not local_match and not attachment:
                # Extract via yt-dlp (YouTube link or search)
                try:
                    extracted = await self.extract_web_track(query, ctx.author)
                    if not extracted:
                        return await ctx.send(f"❌ Could not find any tracks matching `{query}` on YouTube.")
                    tracks_to_add.extend(extracted)
                except Exception as e:
                    return await ctx.send(f"❌ Failed to extract audio: `{e}`")

        # Add all discovered tracks to player queue
        for t in tracks_to_add:
            player.add_to_queue(t)

        if len(tracks_to_add) == 1:
            track = tracks_to_add[0]
            if not player.is_playing:
                await player.play_next()
                await ctx.send(f"▶️ Starting playback for **{track['title']}**", ephemeral=True if ctx.interaction else False)
            else:
                embed = discord.Embed(
                    title="➕ Added to Queue",
                    description=f"**[{track['title']}]({track['webpage_url']})**" if not track.get('is_local') else f"**{track['title']}** (Local Upload)",
                    color=discord.Color.from_rgb(100, 149, 237)
                )
                embed.add_field(name="⏱️ Duration", value=format_duration(track.get('duration', 0)), inline=True)
                embed.add_field(name="📋 Position in Queue", value=f"#{len(player.queue)}", inline=True)
                await ctx.send(embed=embed)
        else:
            if not player.is_playing:
                await player.play_next()
            embed = discord.Embed(
                title="➕ Playlist / Multiple Tracks Added",
                description=f"Added **{len(tracks_to_add)}** tracks to the queue!",
                color=discord.Color.from_rgb(100, 149, 237)
            )
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="nowplaying", aliases=["np"], description="Show currently playing track and interactive controls")
    async def nowplaying(self, ctx: commands.Context):
        """Show currently playing song."""
        if ctx.interaction:
            await ctx.defer()

        player = self.get_player(ctx.guild)
        if not player.current_track:
            return await ctx.send("❌ Nothing is currently playing right now.", ephemeral=True)

        t = player.current_track
        embed = discord.Embed(
            title="🎶 Currently Playing",
            description=f"**[{t['title']}]({t.get('webpage_url', '')})**" if not t.get('is_local') else f"**{t['title']}** (Local Upload)",
            color=discord.Color.from_rgb(255, 105, 180)
        )
        embed.add_field(name="⏱️ Duration", value=format_duration(t.get('duration', 0)), inline=True)
        embed.add_field(name="👤 Requested By", value=t.get('uploader_name', 'Unknown'), inline=True)
        embed.add_field(name="🔁 Loop Mode", value=f"`{player.loop_mode}`", inline=True)
        embed.add_field(name="🔊 Volume", value=f"`{int(player.volume * 100)}%`", inline=True)

        if t.get('is_local'):
            embed.set_footer(text="📁 Played from Bot Local Music Library")
        else:
            embed.set_footer(text="🌐 Streamed via YouTube / Web")

        view = NowPlayingView(player)
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="queue", aliases=["q"], description="Show the current music queue")
    async def queue(self, ctx: commands.Context):
        """Show the current queue."""
        if ctx.interaction:
            await ctx.defer()

        player = self.get_player(ctx.guild)
        if not player.current_track and not player.queue:
            return await ctx.send("📭 The music queue is completely empty right now. Add songs using `/play`!")

        embed = discord.Embed(
            title="📋 Current Music Queue",
            color=discord.Color.blurple()
        )

        if player.current_track:
            ct = player.current_track
            embed.add_field(
                name="▶️ Now Playing",
                value=f"**{ct['title']}** (`{format_duration(ct.get('duration', 0))}`) — Requested by **{ct.get('uploader_name', 'Unknown')}**",
                inline=False
            )

        if player.queue:
            queue_lines = []
            for idx, t in enumerate(player.queue[:10], start=1):
                queue_lines.append(f"`{idx}.` **{t['title']}** (`{format_duration(t.get('duration', 0))}`) • **{t.get('uploader_name', 'Unknown')}**")
            
            embed.add_field(name=f"⏭️ Up Next ({len(player.queue)} track(s))", value="\n".join(queue_lines), inline=False)
            if len(player.queue) > 10:
                embed.set_footer(text=f"And {len(player.queue) - 10} more song(s) waiting in line...")
        else:
            embed.add_field(name="⏭️ Up Next", value="*No upcoming songs in the queue.*", inline=False)

        embed.add_field(name="⚙️ Settings", value=f"**Loop Mode:** `{player.loop_mode}` | **Volume:** `{int(player.volume * 100)}%`", inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="shuffle", aliases=["shuf"], description="Randomly shuffle all tracks waiting in the queue")
    async def shuffle(self, ctx: commands.Context):
        """Shuffle the current music queue."""
        if ctx.interaction:
            await ctx.defer()

        player = self.get_player(ctx.guild)
        if not player.queue or len(player.queue) < 2:
            return await ctx.send("⚠️ You need at least 2 tracks in the queue to shuffle!", ephemeral=True)

        random.shuffle(player.queue)
        await ctx.send(f"🔀 Shuffled **{len(player.queue)}** tracks in the queue!")

    @commands.hybrid_command(name="remove", aliases=["rmqueue", "rq"], description="Remove a specific song from the queue by its position number")
    @app_commands.describe(position="The number of the song in the queue (e.g. 1 for next song)")
    async def remove(self, ctx: commands.Context, position: int):
        """Remove a track from the queue by position."""
        if ctx.interaction:
            await ctx.defer()

        player = self.get_player(ctx.guild)
        if not player.queue:
            return await ctx.send("❌ The queue is empty right now.", ephemeral=True)

        if position < 1 or position > len(player.queue):
            return await ctx.send(f"❌ Invalid position! Please choose a number between 1 and {len(player.queue)}.", ephemeral=True)

        removed = player.queue.pop(position - 1)
        await ctx.send(f"🗑️ Removed **{removed['title']}** from position #{position} in the queue.")

    @commands.hybrid_command(name="skip", aliases=["fs", "s"], description="Skip the currently playing song")
    async def skip(self, ctx: commands.Context):
        """Skip currently playing track."""
        if ctx.interaction:
            await ctx.defer()

        player = self.get_player(ctx.guild)
        if not player.voice_client or not player.current_track:
            return await ctx.send("❌ Nothing is playing right now.", ephemeral=True)

        title = player.current_track['title']
        player.voice_client.stop()
        await ctx.send(f"⏭️ Skipped **{title}**!")

    @commands.hybrid_command(name="pause", description="Pause current music playback")
    async def pause(self, ctx: commands.Context):
        """Pause playback."""
        if ctx.interaction:
            await ctx.defer()

        player = self.get_player(ctx.guild)
        if not player.voice_client or not player.current_track:
            return await ctx.send("❌ Nothing is playing right now.", ephemeral=True)
        if player.is_paused:
            return await ctx.send("⚠️ Playback is already paused! Use `/resume` to continue.", ephemeral=True)

        player.voice_client.pause()
        player.is_paused = True
        await ctx.send("⏸️ Paused music playback. Use `/resume` when you're ready to continue.")

    @commands.hybrid_command(name="resume", description="Resume paused music playback")
    async def resume(self, ctx: commands.Context):
        """Resume paused playback."""
        if ctx.interaction:
            await ctx.defer()

        player = self.get_player(ctx.guild)
        if not player.voice_client or not player.current_track:
            return await ctx.send("❌ Nothing is playing right now.", ephemeral=True)
        if not player.is_paused:
            return await ctx.send("⚠️ Playback is already playing smoothly!", ephemeral=True)

        player.voice_client.resume()
        player.is_paused = False
        await ctx.send("▶️ Resumed music playback!")

    @commands.hybrid_command(name="stop", description="Stop playback and clear the entire music queue")
    async def stop(self, ctx: commands.Context):
        """Stop playing and clear queue."""
        if ctx.interaction:
            await ctx.defer()

        player = self.get_player(ctx.guild)
        if not player.voice_client:
            return await ctx.send("❌ Bot is not in a voice channel.", ephemeral=True)

        player.queue.clear()
        if player.voice_client.is_playing() or player.voice_client.is_paused():
            player.voice_client.stop()
        await ctx.send("⏹️ Stopped playback and cleared the entire music queue.")

    @commands.hybrid_command(name="loop", description="Toggle loop mode between Off, Single Track, and Queue")
    @app_commands.describe(mode="Optional specific loop mode: OFF, TRACK, or QUEUE")
    async def loop(self, ctx: commands.Context, mode: str = None):
        """Toggle loop mode."""
        if ctx.interaction:
            await ctx.defer()

        player = self.get_player(ctx.guild)
        if mode:
            mode_upper = mode.upper()
            if mode_upper not in ("OFF", "TRACK", "QUEUE"):
                return await ctx.send("❌ Invalid mode! Choose from `OFF`, `TRACK`, or `QUEUE`.", ephemeral=True)
            player.loop_mode = mode_upper
        else:
            if player.loop_mode == "OFF":
                player.loop_mode = "TRACK"
            elif player.loop_mode == "TRACK":
                player.loop_mode = "QUEUE"
            else:
                player.loop_mode = "OFF"

        emoji = "🔁" if player.loop_mode == "QUEUE" else ("🔂" if player.loop_mode == "TRACK" else "➡️")
        await ctx.send(f"{emoji} Loop mode is now set to: **{player.loop_mode}**")

    @commands.hybrid_command(name="volume", aliases=["vol"], description="Adjust music playback volume (1-100%)")
    @app_commands.describe(level="Volume percentage between 1 and 100")
    async def volume(self, ctx: commands.Context, level: int):
        """Adjust volume."""
        if ctx.interaction:
            await ctx.defer()

        if level < 1 or level > 100:
            return await ctx.send("❌ Volume must be between 1 and 100!", ephemeral=True)

        player = self.get_player(ctx.guild)
        player.volume = level / 100.0
        if player.voice_client and player.voice_client.source and isinstance(player.voice_client.source, discord.PCMVolumeTransformer):
            player.voice_client.source.volume = player.volume

        await ctx.send(f"🔊 Playback volume set to **{level}%**!")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
