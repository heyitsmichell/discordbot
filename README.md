# Multi-Function Discord Bot

A Discord bot with moderation, auto-slowmode, Twitch/YouTube integration, and anti-raid features.

## Features

- **OAuth Integration**: Link Twitch and YouTube accounts via Discord OAuth
- **Auto-Slowmode**: Dynamic slowmode adjustment based on message activity
- **Moderation System**: Bad word filtering, caps detection, spam protection
- **Anti-Raid Protection**: Account age verification and burst join detection
- **Twitch EventSub**: Real-time ban synchronization across platforms
- **Lockdown System**: Quick server-wide slowmode controls
- **Timezone Display**: Show users' local times based on city/country
- **Birthday Tracking**: Track and announce member birthdays with auto-updating embeds
- **Fun Reactions**: Auto-react to specific users' messages
- **AI Chat**: Gemini-powered AI responses with server emote support

## Prerequisites

- Python 3.8+
- Discord Token
- Discord (for OAuth)
- Twitch
- Supabase

## Installation

1. Clone the repository:
```bash
git clone https://github.com/heyitsmichell/discordbot
cd discordbot
```

2. Install dependencies:
```bash
pip install discord.py flask requests aiohttp python-dotenv
```

3. Create a `.env` file with the following variables:
```env
# Discord Configuration
DISCORD_TOKEN=your_discord_bot_token
DISCORD_CLIENT_ID=your_discord_client_id
DISCORD_CLIENT_SECRET=your_discord_client_secret
DISCORD_REDIRECT_URI=https://yourdomain.com/callback

# Twitch Configuration
TWITCH_CLIENT_ID=your_twitch_client_id
TWITCH_CLIENT_SECRET=your_twitch_client_secret
TWITCH_EVENTSUB_SECRET=your_webhook_secret (at least 12 letters)
TWITCH_CALLBACK_URL=https://yourdomain.com/twitch/events
TWITCH_STREAMER_REDIRECT_URI=https://yourdomain.com/twitch/streamer/callback

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key

# Flask (uncomment if for running locally)
# PORT=5000

# Gemini AI
GEMINI_API_KEY=your_gemini_api_key
```

4. Run the bot:
```bash
python main.py
```

## Configuration

### Discord Application Setup

1. Create a Discord application at https://discord.com/developers/applications
2. Create a bot user and copy the token
3. Set up OAuth2 redirects for user linking
4. Add bot to your server with appropriate permissions

### Twitch Application Setup

1. Create a Twitch application at https://dev.twitch.tv/console
2. Configure OAuth redirect URIs
3. Set up EventSub webhooks for ban synchronization

### Required Bot Permissions

- Manage Channels (for slowmode)
- Ban Members (for ban synchronization)
- Manage Roles (for muting)
- Send Messages
- Read Message History
- Add Reactions (for pagination)

## Commands Reference

### Public Commands

|        Command        |            Description             |         Usage         |
|-----------------------|------------------------------------|-----------------------|
|       `/hello`        |      Basic greeting (legacy)       |       `/hello`        |
|     `/linktwitch`     |      Link your Twitch account      |     `/linktwitch`     |
|    `/linkyoutube`     |     Link your YouTube account      |    `/linkyoutube`     |
|       `/twitch`       |     Show linked Twitch account     |   `/twitch <@user>`   |
|      `/youtube`       |    Show linked YouTube account     |  `/youtube <@user>`   |
|    `/unlinktwitch`    |     Unlink your Twitch account     |    `/unlinktwitch`    |
|   `/unlinkyoutube`    |    Unlink your YouTube account     |   `/unlinkyoutube`    |
| `/linktwitchstreamer` | Link Twitch (streamer permissions) | `/linktwitchstreamer` |
|      `/gettwid`       |  Get Twitch user ID from username  |  `/gettwid username`  |

### Timezone Commands
|    Command    |              Description                |           Usage             |
|---------------|-----------------------------------------|-----------------------------|
|  `/settime`   | Set your timezone based on city/country | `/settime <city> <country>` |
|   `/mytime`   |       Show your current local time      |         `/mytime`           |
|    `/time`    |      Show another user's local time     |       `/time @user`         |
| `/removetime` |        Remove your timezone setting     |       `/removetime`         |
|  `/alltimes`  | Show auto-updating embed with all times |        `/alltimes`          |

### Birthday Commands
|      Command       |              Description                |           Usage            |
|--------------------|----------------------------------------|----------------------------|
|  `/setbirthday`    | Set your birthday (day and month)      | `/setbirthday <day> <month>` |
|   `/mybirthday`    |       Show your saved birthday         |       `/mybirthday`        |
|    `/birthday`     |      Show another user's birthday      |     `/birthday @user`      |
| `/removebirthday`  |       Remove your birthday setting     |     `/removebirthday`      |

### AI Commands
|  Command   |           Description           |       Usage        |
|------------|--------------------------------|--------------------||
|  `/ask`    | Ask the AI a question          | `/ask <question>`  |
| `@Bot`     | Mention the bot to chat        | `@Bot hello!`      |

### Administrator Commands

#### User Management
|         Command         |          Description           |            Usage             |
|-------------------------|--------------------------------|------------------------------|
|         `/help`         |       Show all commands        |           `/help`            |
|     `/twitchusers`      | List users with linked Twitch  |        `/twitchusers`        |
|     `/youtubeusers`     | List users with linked YouTube |       `/youtubeusers`        |
| `/unlinktwitchstreamer` |   Unlink a streamer account.   | `/unlinktwitchstreamer <id>` |

#### Twitch EventSub
|      Command      |            Description             |            Usage            |
|-------------------|------------------------------------|-----------------------------|
|  `/subscribeban`  |   Subscribe to Twitch ban events   | `/subscribeban <twitch_id>` |
| `/unsubscribeban` |    Unsubscribe from ban events     | `/unsubscribeban <sub_id>`  |
|    `/listsubs`    | List active EventSub subscriptions |         `/listsubs`         |

#### Lockdown & Slowmode
|  Command  |          Description           |   Usage   |
|-----------|--------------------------------|-----------|
| `/lock1`  | Apply 15s slowmode server-wide | `/lock1`  |
| `/lock2`  | Apply 30s slowmode server-wide | `/lock2`  |
| `/lock3`  | Apply 60s slowmode server-wide | `/lock3`  |
| `/unlock` |  Remove slowmode server-wide   | `/unlock` |

#### Auto-Slowmode
|          Command           |         Description          |                      Usage                       |
|----------------------------|------------------------------|--------------------------------------------------|
|        `/autoslow`         |     Toggle auto-slowmode     |       `/autoslow enable\|disable\|status`        |
|   `/autoslow_blacklist`    | Manage blacklisted channels  | `/autoslow_blacklist add\|remove\|list #channel` |
| `/set_slowmode_thresholds` | Configure message thresholds | `/set_slowmode_thresholds 50:30,20:15,10:5,0:0`  |
|   `/set_check_frequency`   |   Set evaluation frequency   |         `/set_check_frequency <seconds>`         |

#### Moderation
|    Command    |        Description         | Usage |
|---------------|----------------------------|----------------------------------------|
| `/moderation` | Toggle moderation features |     `/moderation enable\|disable`      |
|  `/badword`   |    Manage bad word list    |  `/badword add\|remove\|list <word>`   |
| `/bannedlink` |  Manage banned link list   | `/bannedlink add\|remove\|list <link>` |
|   `/unban`    |      Unban user by ID      |           `/unban <user_id>`           |

#### Anti-Raid
|   Command   |      Description      |                Usage                |
|-------------|-----------------------|-------------------------------------|
| `/antiraid` | Toggle anti-raid mode | `/antiraid enable\|disable\|status` |

#### Logging
|      Command       |        Description         |           Usage           |
|--------------------|----------------------------|---------------------------|
|  `/setlogchannel`  | Set moderation log channel | `/setlogchannel #channel` |
|  `/getlogchannel`  |  Show current log channel  |     `/getlogchannel`      |
| `/resetlogchannel` |      Reset log channel     |    `/resetlogchannel`     |

#### Birthday Management
|        Command         |            Description             |             Usage              |
|------------------------|------------------------------------|--------------------------------|
| `/setbirthdaychannel`  | Set birthday announcement channel  | `/setbirthdaychannel #channel` |
|    `/allbirthdays`     | Show auto-updating birthday embed  |        `/allbirthdays`         |

## Features Deep Dive

### Auto-Slowmode System

Automatically adjusts channel slowmode based on message activity:
- Configurable thresholds (messages → delay)
- Channel blacklisting
- Guild-specific settings
- Batch processing to avoid rate limits

**Default Thresholds:**
- 50+ messages: 30s slowmode
- 20+ messages: 15s slowmode  
- 10+ messages: 5s slowmode
- <10 messages: 0s slowmode

### Moderation Features

- **Bad Word Filtering**: Customizable word list with auto-deletion
- **Caps Detection**: Configurable threshold for excessive capitals
- **Spam Protection**: Time-based message frequency limits
- **Link Filtering**: Block specific domains/invite links

### Anti-Raid Protection

- **Account Age Verification**: Auto-timeout new accounts
- **Burst Join Detection**: Automatic lockdown on rapid joins
- **Manual Raid Mode**: Emergency protection toggle

### Twitch Integration

- **User Linking**: Connect Discord accounts to Twitch profiles
- **Streamer Authentication**: OAuth for full Twitch permissions
- **Ban Synchronization**: Real-time ban events via EventSub webhooks
- **Cross-Platform Enforcement**: Automatically ban linked accounts

### Birthday System

- **Birthday Tracking**: Users can set their birthday (day and month)
- **Auto-Updating Embed**: Live embed showing upcoming birthdays sorted by proximity
- **Birthday Announcements**: Automatic announcements on users' birthdays (respects user timezone)
- **Pagination**: Navigate through birthdays with reaction controls
- **Page Auto-Reset**: Returns to first page after 20 seconds of inactivity

### Fun Features

- **Auto-Reactions**: Automatically adds 🐐 and 🔥 reactions to specified user's messages
- **Owner Reactions**: Adds 🩷 reaction to bot owner's messages
- **Reaction Protection**: Removes 🐐/🔥 reactions from protected user's messages

## Database Schema

### Tables

**users**
- `discord_id` (TEXT PRIMARY KEY)
- `twitch_username` (TEXT)
- `twitch_id` (TEXT)
- `youtube_channel` (TEXT)

**streamers**
- `discord_id` (TEXT PRIMARY KEY)
- `twitch_id` (TEXT)
- `twitch_username` (TEXT)
- `access_token` (TEXT)
- `refresh_token` (TEXT)

**guild_settings**
- `guild_id` (TEXT PRIMARY KEY)
- Various configuration fields for each guild

**user_timezones**
- `discord_id` (TEXT PRIMARY KEY)
- `city` (TEXT)
- `country` (TEXT)
- `timezone` (TEXT)
- `country_code` (TEXT)

**user_birthdays**
- `discord_id` (TEXT PRIMARY KEY)
- `display_name` (TEXT)
- `day` (INTEGER)
- `month` (INTEGER)
- `last_announced_year` (INTEGER)

**birthday_embeds**
- `guild_id` (TEXT PRIMARY KEY)
- `channel_id` (TEXT)
- `message_id` (TEXT)
- `page` (INTEGER)

**birthday_channels**
- `guild_id` (TEXT PRIMARY KEY)
- `channel_id` (TEXT)

## API Endpoints

### OAuth Callbacks
- `GET /` - Health check
- `GET /callback` - Discord OAuth callback
- `GET /twitch/streamer/callback` - Twitch streamer OAuth callback

### Webhooks
- `POST /twitch/events` - Twitch EventSub webhook endpoint

## Deployment

### Environment Setup

1. Set up a web server with HTTPS (required for Discord OAuth)
2. Ensure webhook endpoints are publicly accessible (Not localhost)

### Production Considerations

- Use environment variables for all secrets
- Implement proper logging and monitoring
- Set up database backups
- Consider load balancing for high-traffic servers
- Monitor rate limits and API quotas

### Logging

The bot logs to `discord.log` with INFO level by default. Check this file for detailed error information and operational status.

## License

MIT License