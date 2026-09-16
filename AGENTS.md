# AGENTS.md — Card Wars Kingdom Server

Reference for AI coding agents working on this codebase.

## Project Overview

A Flask-based backend server for the mobile game **Card Wars Kingdom**. Handles game persistence, multiplayer, PVP leaderboards, friend systems, and provides a full admin web panel. Single-file architecture (`app.py`, ~2150 lines).

## Tech Stack

- **Python 3.11+**, Flask, SQLAlchemy (SQLite), Flask-Login, Flask-Bcrypt
- **Database**: SQLite at `instance/cardwarskingdom.db`
- **Frontend**: Bootstrap 5 admin panel (light/dark theme)
- **Dependencies**: `flask`, `flask_sqlalchemy`, `flask_login`, `flask_bcrypt`, `schedule`, `discord-webhook`

## File Structure

```
cwk-server/
├── app.py                          # Main application (all routes, models, logic)
├── flaskkey                        # Flask secret key (auto-generated, gitignored)
├── requirements.txt                # Python dependencies
├── sync_blueprints.py              # Sync blueprints from remote server
├── instance/
│   └── cardwarskingdom.db          # SQLite database
├── data/persist/
│   ├── version.txt                 # PC version string
│   ├── android_version.txt         # Android version string
│   ├── manifest.json               # Client manifest
│   ├── Blueprints/                 # 81 game data JSON files (creatures, cards, etc.)
│   └── logs/                       # Daily log files (YYYY-MM-DD.txt)
├── static/admin/                   # Bootstrap CSS/JS assets
├── templates/                      # 15 Jinja2 admin templates
└── backup/                         # Auto-backup zip files (every 4 hours)
```

## Database Models

### Player
| Field | Type | Description |
|-------|------|-------------|
| `username` | String(80), PK | Player UUID |
| `game` | String(8192) | Encrypted game save (base64+gzip JSON) |
| `multiplayer_name` | String(128) | Display name |
| `icon` | String(128) | Player icon |
| `deck` | String(1024) | Deck data |
| `deck_rank` | String(16) | Deck rank |
| `landscapes` | String(1024) | Landscape data |
| `helper_creature` | String(1024) | Helper creature |
| `leader` | String(128) | Leader character |
| `leader_level` | Integer | Rank/level |
| `allyboxspace` | Integer | Ally box capacity |
| `level` | Integer | Player level |
| `friends` | String(8192), default="[]" | JSON array of friend UUIDs |
| `friend_requests` | String(8192), default="[]" | JSON array of pending request UUIDs |
| `last_online` | Integer | Unix timestamp |
| `helpcount` | Integer | Help count |
| `anonymoushelpcount` | Integer | Anonymous help count |
| `devicename` | String(128) | Bound device name |

### Admin
| Field | Type | Description |
|-------|------|-------------|
| `username` | String(80), PK | Admin username |
| `password` | String(80) | Bcrypt password hash |
| `rank` | Integer | 0 = superadmin |

### Bans
| Field | Type | Description |
|-------|------|-------------|
| `username` | String(80), PK | Player UUID or IP address |
| `bantype` | String(80) | `"userid"` or `"ip"` |
| `author` | String(80) | Admin username or `"SYSTEM"` |
| `time` | Integer | Unix timestamp |

### Logs
| Field | Type | Description |
|-------|------|-------------|
| `id` | Integer, PK | Auto-increment |
| `date` | String(80) | `"YYYY-MM-DD"` |
| `time` | String(80) | `"HH:MM:SS"` |
| `player` | String(80) | Player UUID |
| `ip` | String(80) | Client IP |
| `message` | String(8192) | Log message |

### UpsightLogs
| Field | Type | Description |
|-------|------|-------------|
| `id` | Integer, PK | Auto-increment |
| `player_id` | String(80) | Player UUID |
| `time` | Integer | Unix timestamp |
| `event` | String(80) | Event type |
| `action` | String(80) | Event action |
| `message` | String(1024) | Event data |

### AdminActivity
| Field | Type | Description |
|-------|------|-------------|
| `id` | Integer, PK | Auto-increment |
| `time` | Integer | Unix timestamp |
| `message` | String(8192) | Activity description |

## Game Data Format

Player game data is stored in the `Player.game` column as:

```
username=<uuid>&data=<base64(gzip(json))>
```

- `DecryptGameData(game)` → parses and returns a dict
- `EncryptGameData(game, username)` → returns bytes in the above format
- The JSON contains: `SoftCurrency`, `HardCurrency` (split into `PaidHardCurrency` + `FreeHardCurrency`), `PvpCurrency`, `EvolutionShards`, `InventorySpace`, `MultiplayerLevel`, `RankXP`, `Zxcvbnm` (PVP ban flag), `Inventory` (array), `CardCollection` (array), `BattleHistory`, etc.

### Inventory Items

Each item in `Inventory` has a `_T` type discriminator:
- `"CR"` — Creature (has `ID`, `Xp`, `StarRating`, `UniqueID`, `Favorite`, `Passive`)
- `"XP"` — XP Material (has `ID`)

### CardCollection Items

Each card has: `{"ID": "<card_id>", "Stat": <level>}`

## Route Reference

### Game API Routes (client-facing)

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Health check |
| GET | `/time/` | Server time |
| GET | `/static/version.txt` | Version info + maintenance status |
| GET | `/persist/static/manifest.json` | Client manifest |
| GET | `/persist/static/blueprints` | All blueprints (v1.18.0+) |
| GET | `/persist/static/Blueprints/<file>` | Individual blueprint |
| GET/PUT | `/persist/game` | Game save (uses `Player-Id` header) |
| GET/PUT | `/persist/<uuid>/game` | Game save by UUID |
| GET | `/persist/friends/<uuid>` | Friend list |
| POST | `/persist/friends_informationDW/` | Friend info |
| POST | `/persist/friends_find_candidatesDW/` | Find friend candidates |
| POST | `/persist/friends_request_withmyinfoDW/` | Send friend request |
| POST | `/persist/friends_confirm_request_withmyinfoDW/` | Accept friend request |
| GET | `/persist/friends_deny_request/<uuid>/<invite_id>` | Deny friend request |
| GET | `/persist/friends_remove/<uuid>/<invite_id>` | Remove friend |
| GET | `/persist/friends_all_requests_received/<uuid>` | Pending requests |
| POST | `/persist/friends_use_friendDW/` | Use ally (increment help) |
| POST | `/persist/friends_use_playerDW/` | Use anonymous helper |
| GET | `/persist/messages_received_ids` | Message IDs |
| GET | `/persist/messages_get/<message>` | Get message |
| GET | `/persist/getcc/` | Country code |
| POST | `/account/preAuth/` | Pre-auth nonce |
| POST | `/account/gcAuth/` | Game Center auth |
| POST | `/persist/user_action2/` | User action tracking |
| POST | `/analytics/upsight` | Analytics receiver |
| POST | `/analytics/pvpmatch` | PVP match data |
| POST | `/multiplayer/new_player/` | Set multiplayer profile |
| POST | `/multiplayer/update_deck_name/` | Update deck/profile |
| POST | `/dw_leaderboard/fetchentries/` | PVP leaderboard |

### Admin Routes

| Method | Route | Description |
|--------|-------|-------------|
| GET/POST | `/admin` | Login (auto-creates first admin) |
| GET | `/admin/home` | Dashboard |
| GET | `/admin/logout` | Logout |
| GET | `/admin/versions` | Version management |
| GET/POST | `/admin/versions` | Update versions |
| GET | `/admin/server` | Server/backups |
| GET | `/admin/server/backup` | Trigger backup |
| GET | `/admin/server/pull` | Git pull |
| GET/POST | `/admin/createadmin` | Create admin |
| GET | `/admin/players` | Player list (sortable) |
| GET | `/admin/players/<uuid>` | Player detail |
| GET | `/admin/players/<uuid>/game` | Raw game data |
| POST | `/admin/players/<uuid>/game/edit` | Overwrite raw data |
| POST | `/admin/players/<uuid>/edit` | Edit resources |
| POST | `/admin/players/<uuid>/add_creature` | Add creature |
| POST | `/admin/players/<uuid>/delete_creature/<idx>` | Delete creature |
| POST | `/admin/players/<uuid>/add_card` | Add action card |
| POST | `/admin/players/<uuid>/delete_card/<idx>` | Delete action card |
| GET | `/admin/players/<uuid>/ban` | Ban player |
| GET | `/admin/players/<uuid>/unban` | Unban player |
| GET | `/admin/bannedplayers` | Banned players list |
| GET | `/admin/bannedips` | Banned IPs list |
| POST | `/admin/ipban` | Ban IP |
| GET | `/admin/ipban/<ip>/unban` | Unban IP |
| GET | `/admin/maintenance` | Maintenance toggle |
| GET | `/admin/logs` | Player logs (paginated) |
| GET | `/admin/upsight` | Analytics logs (paginated) |
| GET | `/admin/misc` | Misc tools |

## Key Functions

| Function | Location | Description |
|----------|----------|-------------|
| `DecryptGameData(game)` | app.py | Decode base64+gzip game save to dict |
| `EncryptGameData(game, username)` | app.py | Encode dict to base64+gzip game save |
| `Backup()` | app.py | Zip DB + persist folder to `backup/` |
| `Log(category, message)` | app.py | Write to daily log file |
| `PlayerLog(ip, player, message)` | app.py | Create Logs DB entry |
| `DiscordWebhookMessage(message)` | app.py | Send Discord webhook + log to AdminActivity |
| `IsUserBanned(username, ip)` | app.py | Check ban list |
| `SystemBan(username)` | app.py | Auto-ban (anti-cheat) |
| `UpdateLastOnline(player_id)` | app.py | Update last_online timestamp |
| `GetAllyInfo(player_id, isally)` | app.py | Build ally info dict |
| `GetPlayerWins(player_id)` | app.py | Count PVP wins this season |
| `InvalidUsername(username)` | app.py | Validate username |
| `IPFromRequest(request)` | app.py | Extract client IP |

## Anti-Cheat / Security

1. **Leader level validation** — Auto-bans if fresh account sets level > 5 or level jumps by > 10
2. **ACTk detection** — Auto-bans on anti-cheat trigger from Upsight analytics
3. **Device binding** — First `X-Nick-Description` header is stored; subsequent saves must match
4. **Header validation** — PUT requires: `Player-Id`, `Age`, `User-Agent`, `Platform`, `Version`, `X-Nick-Description`
5. **Username validation** — Blocks special characters and reserved names ("ua", "guest")
6. **PVP ban** — `Zxcvbnm` flag in game data blocks save operations

## Conventions

- **New routes**: Add after the last route in the same category section in `app.py`
- **New models**: Add before `db.create_all()` (line ~2034)
- **New admin pages**: Create template in `templates/`, add route in app.py, add nav link in `admin_base.html`
- **Game data changes**: Always use `EncryptGameData(game, player)` to save — it handles the `username=&data=` format
- **Logging**: Use `Log("category", "message")` for file logs, `DiscordWebhookMessage()` for alerts
- **Admin access**: All admin routes check `@login_required` + `isAdmin(current_user)`
- **No Flask Blueprints**: The project uses a single flat Flask app — do not add Blueprint objects

## Running

```bash
pip install -r requirements.txt
python app.py                    # Default port 5000
python app.py --port 8080        # Custom port
python app.py --debug            # Debug mode
gunicorn app:app                 # Production (port 8000)
```

The first admin account is auto-created on first login — check console output for the random password.
