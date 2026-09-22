# AGENTS.md — Card Wars Kingdom Server

Reference for AI coding agents working on this codebase.

## Project Overview

A Flask-based backend server for the mobile game **Card Wars Kingdom**. Handles game persistence, multiplayer, PVP leaderboards, friend systems, and provides a full admin web panel. Modular package architecture under `app/`.

## Tech Stack

- **Python 3.11+**, Flask, SQLAlchemy (SQLite), Flask-Login, Flask-Bcrypt
- **Database**: SQLite at `instance/cardwarskingdom.db`
- **Frontend**: Tailwind CSS (CDN) + Lucide Icons + shadcn/ui design system (modern, responsive grid, light/dark mode)
- **Dependencies**: `flask`, `flask_sqlalchemy`, `flask_login`, `flask_bcrypt`, `schedule`, `discord-webhook`

## File Structure

```
cwk-server/
├── app.py                          # Thin entry point (18 lines)
├── app/
│   ├── __init__.py                 # Flask app factory, db, globals, scheduler
│   ├── models.py                   # All DB models
│   ├── utils.py                    # All helpers (encrypt/decrypt, logging, etc.)
│   └── routes/
│       ├── __init__.py             # Blueprint registration
│       ├── game.py                 # Game API routes (client-facing)
│       ├── admin.py                # Admin panel routes
│       ├── multiplayer.py          # Multiplayer routes
│       ├── friends.py              # Friend system routes
│       └── analytics.py            # Analytics + leaderboard routes
├── flaskkey                        # Flask secret key (auto-generated)
├── requirements.txt                # Python dependencies
├── instance/
│   └── cardwarskingdom.db          # SQLite database
├── data/persist/
│   ├── version.txt                 # PC version string
│   ├── android_version.txt         # Android version string
│   ├── manifest.json               # Client manifest
│   ├── Blueprints/                 # Game data JSON files (creatures, cards, etc.)
│   └── logs/                       # Daily log files (YYYY-MM-DD.txt)
├── static/admin/                   # Bootstrap CSS/JS assets (legacy)
├── templates/                      # 21 Jinja2 admin templates
│   ├── admin_base.html             # Base layout (Tailwind + shadcn/ui sidebar & theme toggle)
│   ├── admin_login.html            # Login page
│   ├── admin_home.html             # Dashboard
│   ├── admin_player.html           # Player detail/edit
│   ├── admin_player_game.html      # Game data viewer
│   ├── admin_players.html          # Player list
│   ├── admin_creatures.html        # Creature book (searchable reference)
│   ├── admin_cards.html            # Action card book (searchable reference)
│   ├── admin_leaders.html          # Leader book (searchable reference)
│   ├── admin_top_pvp.html          # Top PVP players (by Multiplayer Level)
│   ├── admin_redeemcodes.html      # Redeem codes CRUD
│   ├── admin_versions.html         # Version management
│   ├── admin_server.html           # Server/backups
│   ├── admin_createadmin.html      # Create admin
│   ├── admin_bannedplayers.html    # Banned players
│   ├── admin_bannedips.html        # Banned IPs
│   ├── admin_maintenance.html      # Maintenance toggle
│   ├── admin_logs.html             # Player logs
│   ├── admin_upsight.html          # Analytics logs
│   └── admin_misc.html             # Misc tools
└── backup/                         # Auto-backup zip files (every 4 hours)
```

## Database Models

### Player
| Field | Type | Description |
|-------|------|-------------|
| `username` | String(80), PK | Player UUID |
| `game` | Text | Encrypted game save (base64+gzip JSON) |
| `multiplayer_name` | String(128) | Display name |
| `icon` | String(128) | Player icon |
| `deck` | String(1024) | Deck data |
| `deck_rank` | String(16) | Deck rank |
| `landscapes` | String(1024) | Landscape data |
| `helper_creature` | String(1024) | Helper creature (JSON) |
| `leader` | String(128) | Leader character |
| `leader_level` | Integer | Rank/level |
| `allyboxspace` | Integer | Ally box capacity |
| `level` | Integer | Player level |
| `friends` | Text, default="[]" | JSON array of friend UUIDs |
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
| `expires` | Integer | Unix expiry timestamp; `0`/NULL = permanent |

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

### RedeemCode
| Field | Type | Description |
|-------|------|-------------|
| `code` | String(128), PK | Redeem code (uppercase) |
| `reward_type` | String(128) | Currency or item type (`SoftCurrency`, `HardCurrency`, `FreeHardCurrency`, `PvpCurrency`, `EvolutionShards`, `Creature`, `ActionCard`, `Leader`) |
| `reward_amount` | Integer | Amount (or Star Rating for Creature, Copies for Action Card) |
| `reward_item` | String(128) | Creature ID, Action Card ID, or Leader ID (for item rewards) |
| `enabled` | Boolean | Active status |
| `created_by` | String(128) | Admin who created |

## Game Data Format

Player game data is stored in the `Player.game` column as:

```
username=<uuid>&data=<base64(gzip(json))>
```

- `DecryptGameData(game)` → parses and returns a dict
- `EncryptGameData(game, username)` → returns bytes in the above format
- The JSON contains: `SoftCurrency`, `HardCurrency` (split into `PaidHardCurrency` + `FreeHardCurrency`), `PvpCurrency`, `EvolutionShards`, `InventorySpace`, `MultiplayerLevel`, `RankXP`, `Zxcvbnm` (PVP ban flag), `Inventory` (array), `CardCollection` (array), `BattleHistory`, `Leaders`, etc.

### Inventory Items

Each item in `Inventory` has a `_T` type discriminator:
- `"CR"` — Creature (has `ID`, `Xp`, `StarRating`, `UniqueID`, `Favorite`, `Passive`)
- `"CA"` — Action Card (has `ID`, `CreatureUID`, `CreatureSlot`)
- `"XP"` — XP Material (has `ID`)

### CardCollection Items

Each card has: `{"ID": "<card_id>", "Stat": <level>}`

### Leader Items

Each base hero has: `{"ID": "Leader_Finn", "Skin": "Leader_Finn", "OwnedSkins": ["Leader_FinnPajama", ...]}`

Skins are stored inside their base hero's `OwnedSkins` — they must never be added as independent entries in `Leaders` (the client flags this). `db_Leaders.json` contains 32 base heroes and 51 skins; a skin entry has a `SkinOf` field pointing at its base hero.

## Route Reference

### Game API Routes (`app/routes/game.py`)

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Health check |
| GET | `/time/` | Server time |
| GET | `/static/version.txt` | Version info + maintenance status |
| GET | `/persist/static/manifest.json` | Client manifest |
| GET | `/persist/static/blueprints` | All blueprints (v1.18.0+) |
| GET | `/persist/static/Blueprints/<file>` | Individual blueprint |
| GET | `/persist/static/monthly_store` | Monthly store configuration |
| GET/POST | `/persist/static/pvp_banlist` | PVP ban list & active bans |
| GET/PUT | `/persist/game` | Game save (uses `Player-Id` header) |
| GET/PUT | `/persist/<uuid>/game` | Game save by UUID |
| GET | `/persist/messages_received_ids` | Message IDs |
| GET | `/persist/messages_get/<message>` | Get message |
| GET | `/persist/getcc/` | Country code |
| POST | `/account/preAuth/` | Pre-auth nonce |
| POST | `/account/gcAuth/` | Game Center auth |
| POST | `/persist/user_action2/` | User action tracking |

### Friend Routes (`app/routes/friends.py`)

| Method | Route | Description |
|--------|-------|-------------|
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

### Multiplayer Routes (`app/routes/multiplayer.py`)

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/multiplayer/new_player/` | Set multiplayer profile |
| POST | `/multiplayer/update_deck_name/` | Update deck/profile |
| POST | `/multiplayer/redeemcodeDW/` | Redeem code API |

### Analytics Routes (`app/routes/analytics.py`)

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/analytics/upsight` | Analytics receiver |
| POST | `/analytics/pvpmatch` | PVP match data |
| POST | `/dw_leaderboard/fetchentries/` | PVP leaderboard |

### Admin Routes (`app/routes/admin.py`)

| Method | Route | Description |
|--------|-------|-------------|
| GET/POST | `/admin` | Login (auto-creates first admin) |
| GET | `/admin/home` | Dashboard |
| GET | `/admin/logout` | Logout |
| GET/POST | `/admin/versions` | Version management |
| GET | `/admin/server` | Server/backups |
| GET | `/admin/server/backup` | Trigger backup |
| GET | `/admin/server/pull` | Git pull |
| GET/POST | `/admin/createadmin` | Create admin |
| GET | `/admin/players` | Player list (sortable) |
| GET | `/admin/top_pvp` | Top PVP players ranked by Multiplayer Level (1 = Super Amadeus best, 25 = Dweeb) |
| GET | `/admin/players/<uuid>` | Player detail |
| GET | `/admin/players/<uuid>/game` | Game data viewer |
| POST | `/admin/players/<uuid>/game/edit` | Overwrite raw data |
| POST | `/admin/players/<uuid>/edit` | Edit resources (incl. `MultiplayerName` to rename player) |
| POST | `/admin/players/<uuid>/add_creature` | Add creature |
| POST | `/admin/players/<uuid>/delete_creature/<idx>` | Delete creature |
| POST | `/admin/players/<uuid>/delete_all_creatures` | Delete all creatures |
| POST | `/admin/players/<uuid>/delete_creatures_bulk` | Multi-delete selected creatures |
| POST | `/admin/players/<uuid>/max_creature/<idx>` | Max single creature to 5★ |
| POST | `/admin/players/<uuid>/add_card` | Add action card |
| POST | `/admin/players/<uuid>/delete_card/<idx>` | Delete action card |
| POST | `/admin/players/<uuid>/delete_all_cards` | Delete all action cards |
| POST | `/admin/players/<uuid>/delete_cards_bulk` | Multi-delete selected action cards |
| POST | `/admin/players/<uuid>/add_all_creatures` | Add all 625 collectible creatures (skips `TutorialOnly`) |
| POST | `/admin/players/<uuid>/remove_invalid_creatures` | Remove tutorial-only creatures & clear `Zxcvbnm` PVP ban flag |
| POST | `/admin/players/<uuid>/max_all_creatures` | Max all creatures to 5★ |
| POST | `/admin/players/<uuid>/add_max_creature` | Add single max creature |
| POST | `/admin/players/<uuid>/add_all_cards` | Add all 695 action cards |
| POST | `/admin/players/<uuid>/add_all_leaders` | Add all 32 base heroes (skips skins) |
| POST | `/admin/players/<uuid>/add_leader` | Add single hero; a skin ID is attached to its base hero's `OwnedSkins` |
| POST | `/admin/players/<uuid>/delete_leader/<idx>` | Delete single leader |
| POST | `/admin/players/<uuid>/delete_all_leaders` | Delete all leaders |
| POST | `/admin/players/<uuid>/delete_leaders_bulk` | Multi-delete selected leaders |
| POST | `/admin/players/<uuid>/add_all_skins` | Attach all skins to the player's owned heroes via `OwnedSkins` |
| POST | `/admin/players/<uuid>/max_resources` | Max all currencies preset |
| GET | `/admin/players/<uuid>/export_save` | Download save as JSON |
| POST | `/admin/players/<uuid>/import_save` | Upload & replace save JSON |
| POST | `/admin/players/<uuid>/fix_save` | Detect & repair broken save fields / duplicate creature IDs (deletes nothing) |
| POST | `/admin/players/<uuid>/transfer_progress` | Copy progress to target UUID (keeps target name & currencies; source untouched) |
| POST | `/admin/players/<uuid>/reset_save` | Reset save to starter values |
| POST | `/admin/players/<uuid>/delete` | Delete player account |
| POST | `/admin/players/bulk_action` | Bulk ban, unban, or delete players |
| GET | `/admin/players/<uuid>/ban` | Ban player |
| GET | `/admin/players/<uuid>/unban` | Unban player |
| GET | `/admin/bannedplayers` | Banned players list |
| GET | `/admin/bannedips` | Banned IPs list |
| POST | `/admin/ipban` | Ban IP |
| GET | `/admin/ipban/<ip>/unban` | Unban IP |
| GET | `/admin/pvp_banlist` | PVP creature & leader ban list manager |
| POST | `/admin/pvp_banlist/add_creature` | Add creature to PVP ban list |
| POST | `/admin/pvp_banlist/remove_creature/<id>` | Remove creature from PVP ban list |
| POST | `/admin/pvp_banlist/add_leader` | Add leader to PVP ban list |
| POST | `/admin/pvp_banlist/remove_leader/<id>` | Remove leader from PVP ban list |
| POST | `/admin/pvp_banlist/edit_raw` | Save raw JSON for PVP ban list |
| GET | `/admin/maintenance` | Maintenance toggle |
| GET | `/admin/logs` | Player logs (paginated) |
| GET | `/admin/upsight` | Analytics logs (paginated) |
| GET | `/admin/misc` | Misc tools |
| GET | `/admin/redeemcodes` | Redeem codes list |
| POST | `/admin/redeemcodes/add` | Add/update redeem code |
| POST | `/admin/redeemcodes/delete/<code>` | Delete redeem code |
| POST | `/admin/redeemcodes/toggle/<code>` | Toggle redeem code |
| GET | `/admin/creatures` | Creature book (searchable) |
| GET | `/admin/cards` | Action card book (searchable) |
| GET | `/admin/leaders` | Leader book (searchable) |

## Key Functions

| Function | Location | Description |
|----------|----------|-------------|
| `DecryptGameData(game)` | `app/utils.py` | Decode base64+gzip game save to dict |
| `EncryptGameData(game, username)` | `app/utils.py` | Encode dict to base64+gzip game save |
| `Backup()` | `app/utils.py` | Zip DB + persist folder to `backup/` |
| `Log(category, message)` | `app/utils.py` | Write to daily log file |
| `PlayerLog(ip, player, message)` | `app/utils.py` | Create Logs DB entry |
| `DiscordWebhookMessage(message)` | `app/utils.py` | Send Discord webhook + log to AdminActivity |
| `IsUserBanned(username, ip)` | `app/utils.py` | Check active (non-expired) ban list |
| `SystemBan(username)` | `app/utils.py` | Auto-ban (anti-cheat), permanent |
| `GetBanExpiry(duration, amount, unit)` | `app/utils.py` | Resolve a ban duration to a unix expiry (0 = permanent) |
| `FormatBanExpiry(expires)` | `app/utils.py` | Human-readable ban expiry (`"Permanent"` when 0/NULL) |
| `FindBrokenSaveIssues(game)` | `app/utils.py` | Return list of missing/invalid save fields & duplicate creature IDs |
| `RepairGameData(game, username, fallback_name)` | `app/utils.py` | Fill missing fields / fix duplicate IDs without deleting data |
| `BuildTransferredGame(source, target, username, name)` | `app/utils.py` | Copy progress to a target save keeping target name & currencies |
| `UpdateLastOnline(player_id)` | `app/utils.py` | Update last_online timestamp |
| `GetAllyInfo(player_id, isally)` | `app/utils.py` | Build ally info dict |
| `GetPlayerWins(player_id)` | `app/utils.py` | Count PVP wins this season |
| `GetXPForRank(rank)` | `app/utils.py` | Get required cumulative RankXP for a given player rank |
| `GetRankForXP(xp)` | `app/utils.py` | Calculate player rank from cumulative RankXP |
| `GetRankXPTable()` | `app/utils.py` | Return full level -> XP dictionary from blueprints |
| `GetPvpRankName(level)` | `app/utils.py` | PVP league name for a MultiplayerLevel (1 = Super Amadeus) |
| `GetTutorialOnlyCreatureIds()` | `app/utils.py` | Set of `TutorialOnly` creature IDs (non-collectible) |
| `IsTutorialOnlyCreature(id)` | `app/utils.py` | True if a creature is tutorial-only |
| `GetLeaderSkinBase(id)` | `app/utils.py` | Base hero ID if the ID is a skin, else `None` |
| `GetLeaderSkins(base_id)` | `app/utils.py` | Skin IDs belonging to a base hero |
| `NormalizeLeaders(leaders)` | `app/utils.py` | Fold skin entries into their base hero's `OwnedSkins` |
| `InvalidUsername(username)` | `app/utils.py` | Validate username |
| `IPFromRequest(request)` | `app/utils.py` | Extract client IP |

## Anti-Cheat / Security

1. **Leader level validation** — Auto-bans if fresh account sets level > 5 or level jumps by > 10
2. **ACTk detection** — Auto-bans on anti-cheat trigger from Upsight analytics
3. **Device binding** — First `X-Nick-Description` header is stored; subsequent saves must match
4. **Header validation** — PUT requires: `Player-Id`, `Age`, `User-Agent`, `Platform`, `Version`, `X-Nick-Description`
5. **Username validation** — Blocks special characters and reserved names ("ua", "guest")
6. **PVP ban** — `Zxcvbnm` flag in game data blocks save operations. It is set by the game client when it detects tampering — e.g. when non-collectible `TutorialOnly` creatures (`TUT_*`) are granted. Creature tools skip these IDs, and `remove_invalid_creatures` clears existing ones plus the flag
7. **Temporary bans** — Ban rows carry an optional `expires` unix timestamp (`0`/NULL = permanent). Expired bans are treated as inactive by `IsUserBanned` and purged from the banned-players list
8. **Save integrity** — The admin player page runs `FindBrokenSaveIssues` and offers a non-destructive `fix_save` repair (fills missing fields, reassigns duplicate creature IDs, folds independent skin entries into their base hero's `OwnedSkins`)

## Conventions

- **New routes**: Add to the appropriate blueprint file in `app/routes/`
- **New models**: Add to `app/models.py`
- **New admin pages**: Create template in `templates/`, add route in `app/routes/admin.py`, add nav link in `admin_base.html`
- **Game data changes**: Always use `EncryptGameData(game, player)` to save — it handles the `username=&data=` format
- **Logging**: Use `Log("category", "message")` for file logs, `DiscordWebhookMessage()` for alerts
- **Admin access**: All admin routes check `@login_required` + `isAdmin(current_user)`
- **Blueprints**: All routes use Flask Blueprints registered in `app/routes/__init__.py`
- **File paths**: Always use `ROOT_DIR` for file access (defined in each route file)

## Running

```bash
pip install -r requirements.txt
python app.py                    # Default port 5000
python app.py --port 8080        # Custom port
python app.py --debug            # Debug mode
```

The first admin account is auto-created on first login — check console output for the random password.
