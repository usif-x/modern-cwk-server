# AGENTS.md — Card Wars Kingdom Server

Reference for AI coding agents working on this codebase.

## Project Overview

A Flask-based backend server for the mobile game **Card Wars Kingdom**. Handles game persistence, multiplayer, PVP leaderboards, friend systems, and provides a full admin web panel. Modular package architecture under `app/`.

## Tech Stack

- **Python 3.11+**, Flask, SQLAlchemy (PostgreSQL), Flask-Login, Flask-Bcrypt
- **Database**: PostgreSQL `cardwarskingdom` at `postgresql+psycopg2://localhost:5432/cardwarskingdom` (override with `DATABASE_URL` / `POSTGRES_URL`; `postgres://` (Heroku), `postgresql://` and `postgres+psycopg2://` are normalised to `postgresql+psycopg2://`, query strings kept; `DATABASE_URL=sqlite:///...` falls back to SQLite)
- **Frontend**: Tailwind CSS (CDN) + Lucide Icons + shadcn/ui design system (modern, responsive grid, light/dark mode)
- **Dependencies**: `flask`, `flask_sqlalchemy`, `flask_login`, `flask_bcrypt`, `psycopg2-binary`, `schedule`, `discord-webhook`, `python-dotenv`, `requests`
- **Config**: `.env` (gitignored, copy from `.env.example`) — optional `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_ID`, optional `BACKUP_INTERVAL_HOURS`

## File Structure

```
cwk-server/
├── app.py                          # Thin entry point (18 lines)
├── app/
│   ├── __init__.py                 # Flask app factory, db, globals, scheduler
│   ├── config.py                   # .env loader (Telegram token/id, backup interval)
│   ├── models.py                   # All DB models
│   ├── utils.py                    # All helpers (encrypt/decrypt, backups, Telegram, logging, etc.)
│   └── routes/
│       ├── __init__.py             # Blueprint registration
│       ├── game.py                 # Game API routes (client-facing)
│       ├── admin.py                # Admin panel routes
│       ├── multiplayer.py          # Multiplayer routes
│       ├── friends.py              # Friend system routes
│       └── analytics.py            # Analytics + leaderboard routes
├── flaskkey                        # Flask secret key (fallback; set SECRET_KEY on Heroku)
├── requirements.txt                # Python dependencies
├── migrate_sqlite_to_postgres.py   # One-off SQLite -> PostgreSQL data migration
├── instance/
│   └── cardwarskingdom.db          # Legacy SQLite database (pre-migration)
├── data/persist/
│   ├── version.txt                 # PC version string
│   ├── android_version.txt         # Android version string
│   ├── manifest.json               # Client manifest
│   ├── Blueprints/                 # Game data JSON files (creatures, cards, etc.)
│   └── logs/                       # Daily log files (YYYY-MM-DD.txt)
├── static/admin/                   # Bootstrap CSS/JS assets (legacy)
├── templates/                      # 22 Jinja2 admin templates
│   ├── admin_base.html             # Base layout (Tailwind + shadcn/ui sidebar & theme toggle)
│   ├── admin_login.html            # Login page (username/password + passkey)
│   ├── admin_profile.html          # Secret profile (email, password, passkey)
│   ├── admin_home.html             # Dashboard
│   ├── admin_player.html           # Player detail/edit
│   ├── admin_player_game.html      # Game data viewer
│   ├── admin_players.html          # Player list
│   ├── admin_creatures.html        # Creature book (searchable reference)
│   ├── admin_cards.html            # Auguments book (searchable reference)
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

| Field                | Type                       | Description                            |
| -------------------- | -------------------------- | -------------------------------------- |
| `username`           | String(80), PK             | Player UUID                            |
| `game`               | Text                       | Encrypted game save (base64+gzip JSON) |
| `multiplayer_name`   | String(128)                | Display name                           |
| `icon`               | String(128)                | Player icon                            |
| `deck`               | String(1024)               | Deck data                              |
| `deck_rank`          | String(16)                 | Deck rank                              |
| `landscapes`         | String(1024)               | Landscape data                         |
| `helper_creature`    | String(1024)               | Helper creature (JSON)                 |
| `leader`             | String(128)                | Leader character                       |
| `leader_level`       | Integer                    | Rank/level                             |
| `allyboxspace`       | Integer                    | Ally box capacity                      |
| `level`              | Integer                    | Player level                           |
| `friends`            | Text, default="[]"         | JSON array of friend UUIDs             |
| `friend_requests`    | String(8192), default="[]" | JSON array of pending request UUIDs    |
| `last_online`        | Integer                    | Unix timestamp                         |
| `helpcount`          | Integer                    | Help count                             |
| `anonymoushelpcount` | Integer                    | Anonymous help count                   |
| `devicename`         | String(128)                | Bound device name                      |

### Admin

| Field             | Type           | Description                                   |
| ----------------- | -------------- | --------------------------------------------- |
| `username`        | String(80), PK | Admin username                                |
| `password`        | String(80)     | Bcrypt password hash                          |
| `rank`            | Integer        | 0 = superadmin                                |
| `email`           | String(255)    | Optional recovery email                       |
| `passkey`         | String(80)     | Bcrypt hash of the 6-digit passkey (optional) |
| `passkey_enabled` | Boolean        | Allow passwordless passkey login              |

### Bans

| Field      | Type           | Description                                 |
| ---------- | -------------- | ------------------------------------------- |
| `username` | String(80), PK | Player UUID or IP address                   |
| `bantype`  | String(80)     | `"userid"` or `"ip"`                        |
| `author`   | String(80)     | Admin username or `"SYSTEM"`                |
| `time`     | Integer        | Unix timestamp                              |
| `expires`  | Integer        | Unix expiry timestamp; `0`/NULL = permanent |

### Logs

| Field     | Type         | Description    |
| --------- | ------------ | -------------- |
| `id`      | Integer, PK  | Auto-increment |
| `date`    | String(80)   | `"YYYY-MM-DD"` |
| `time`    | String(80)   | `"HH:MM:SS"`   |
| `player`  | String(80)   | Player UUID    |
| `ip`      | String(80)   | Client IP      |
| `message` | String(8192) | Log message    |

### UpsightLogs

| Field       | Type         | Description    |
| ----------- | ------------ | -------------- |
| `id`        | Integer, PK  | Auto-increment |
| `player_id` | String(80)   | Player UUID    |
| `time`      | Integer      | Unix timestamp |
| `event`     | String(80)   | Event type     |
| `action`    | String(80)   | Event action   |
| `message`   | String(1024) | Event data     |

### AdminActivity

| Field     | Type         | Description          |
| --------- | ------------ | -------------------- |
| `id`      | Integer, PK  | Auto-increment       |
| `time`    | Integer      | Unix timestamp       |
| `message` | String(8192) | Activity description |

### RedeemCode

| Field           | Type            | Description                                                                                                                                      |
| --------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `code`          | String(128), PK | Redeem code (uppercase)                                                                                                                          |
| `reward_type`   | String(128)     | Currency or item type (`SoftCurrency`, `HardCurrency`, `FreeHardCurrency`, `PvpCurrency`, `EvolutionShards`, `Creature`, `ActionCard`, `Leader`) |
| `reward_amount` | Integer         | Amount (or Star Rating for Creature, Copies for Auguments)                                                                                       |
| `reward_item`   | String(128)     | Creature ID, Auguments ID, or Leader ID (for item rewards)                                                                                       |
| `enabled`       | Boolean         | Active status                                                                                                                                    |
| `created_by`    | String(128)     | Admin who created                                                                                                                                |

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
- `"CA"` — Auguments (has `ID`, `CreatureUID`, `CreatureSlot`)
- `"XP"` — XP Material (has `ID`)

### CardCollection Items

Each card has: `{"ID": "<card_id>", "Stat": <level>}`

### Leader Items

Each base hero has: `{"ID": "Leader_Finn", "Skin": "Leader_Finn", "OwnedSkins": ["Leader_FinnPajama", ...]}`

Skins are stored inside their base hero's `OwnedSkins` — they must never be added as independent entries in `Leaders` (the client flags this). `db_Leaders.json` contains 32 base heroes and 51 skins; a skin entry has a `SkinOf` field pointing at its base hero. The admin **Leader Book** (`/admin/leaders`) shows base heroes only.

### Battle History

Each `BattleHistory` entry records only the **opponent's** side of a PVP match:

```json
{"opponentName": "...", "opponentId": "<uuid>", "opponentLeader": "Leader_FlameKing",
 "creatures": ["...", "..."], "season": "Season19SmellySewer", "youWon": true,
 "recordTime": 1790108761, "currentLeague": 14, "bestLeague": 1,
 "bestLeagueSeasonID": 0, "flag": "US", "battleVideo": "<uuid>"}
```

- `creatures` + `opponentLeader` are the loadout the match was fought against — this player's own deck is never stored, so it cannot be reconstructed
- An empty or missing `season` means a friendly match: PVP ban rules do not apply, so `DescribeBattleRecord` never flags those records
- The admin player page expands each row to show that opponent loadout, highlights anything listed in `pvp_banlist.json`, and screens the player's current Teams the same way

### Post Office (Mails)

The in-game post office is the save's `Mails` array. An entry looks like:

```json
{"ID": "DAILY_05", "UniqueID": 1, "MailTitle": "Fried-Day!",
 "MailBody": "...", "HardQuantity": 0, "SoftQuantity": 0, "PVPQuantity": 25,
 "Repeatable": "Friday", "ShowDate": "01/01/0001 00:00:00",
 "EndDate": "01/01/0001 00:00:00", "MailType": "Scheduled",
 "Opened": 1, "Rewarded": 1}
```

- The save's `Mails` array is **client-owned**. The client rebuilds it from `data/persist/Blueprints/db_NewsMail.json` (`MailController.RetrieveMailsAndAllyInvites`): for every blueprint entry whose `PlayerID` matches the player (or is empty) and whose `showDate`/`endDate`/`Repeats` window is active, and that isn't already in `Mails` or `DeletedMail`, it creates a `MailItem`.
- The client's `MailItem` only understands these rewards: `SoftCurrency`, `HardCurrency`, `PvPCurrency` (currency quantities), `XPMaterials` (GiftID + quantity) and `Creature` (GiftID). **Heroes, Auguments and Evolution Shards cannot travel by mail.**
- The admin **Gift / Reward** composer (`POST /admin/players/<uuid>/gift`) appends a per-player entry to `db_NewsMail.json` (`AddNewsMailGift`: unique `ADMIN_*` ID, `GiftType`, optional `GiftID`, `Quantity`, `showDate` = today, `PlayerID` = UUID). Heroes/Auguments/Shards are instead granted directly (`ApplyRedeemReward`, skin-aware for heroes) plus a reward-less notice mail (`AddNewsMailNotice`). The player must restart the game to pick up a new blueprint mail.
- Never write gift rewards into the save's `Mails` directly — the client ignores unknown fields and rebuilds the array. `StripLegacyAdminMails` removes any leftover `ADMIN_*` entries from saves.
- `PruneDeliveredNewsMail` deletes a per-player `db_NewsMail` entry once the save references its ID (in `Mails` or `DeletedMail`), so a claimed gift is not re-created on the next login. Blueprint IDs are timestamp-based so they are never reused.

## Route Reference

### Game API Routes (`app/routes/game.py`)

| Method   | Route                               | Description                         |
| -------- | ----------------------------------- | ----------------------------------- |
| GET      | `/`                                 | Health check                        |
| GET      | `/time/`                            | Server time                         |
| GET      | `/static/version.txt`               | Version info + maintenance status   |
| GET      | `/persist/static/manifest.json`     | Client manifest                     |
| GET      | `/persist/static/blueprints`        | All blueprints (v1.18.0+)           |
| GET      | `/persist/static/Blueprints/<file>` | Individual blueprint                |
| GET      | `/persist/static/monthly_store`     | Monthly store configuration         |
| GET      | `/persist/static/live`              | Live status (maintenance/notices, admin-editable `live.json`) |
| GET/POST | `/persist/static/pvp_banlist`       | PVP ban list & active bans          |
| GET/PUT  | `/persist/game`                     | Game save (uses `Player-Id` header) |
| GET/PUT  | `/persist/<uuid>/game`              | Game save by UUID                   |
| GET      | `/persist/messages_received_ids`    | Message IDs                         |
| GET      | `/persist/messages_get/<message>`   | Get message                         |
| GET      | `/persist/getcc/`                   | Country code                        |
| POST     | `/account/preAuth/`                 | Pre-auth nonce                      |
| POST     | `/account/gcAuth/`                  | Game Center auth                    |
| POST     | `/persist/user_action2/`            | User action tracking                |

### Friend Routes (`app/routes/friends.py`)

| Method | Route                                              | Description               |
| ------ | -------------------------------------------------- | ------------------------- |
| GET    | `/persist/friends/<uuid>`                          | Friend list               |
| POST   | `/persist/friends_informationDW/`                  | Friend info               |
| POST   | `/persist/friends_find_candidatesDW/`              | Find friend candidates    |
| POST   | `/persist/friends_request_withmyinfoDW/`           | Send friend request       |
| POST   | `/persist/friends_confirm_request_withmyinfoDW/`   | Accept friend request     |
| GET    | `/persist/friends_deny_request/<uuid>/<invite_id>` | Deny friend request       |
| GET    | `/persist/friends_remove/<uuid>/<invite_id>`       | Remove friend             |
| GET    | `/persist/friends_all_requests_received/<uuid>`    | Pending requests          |
| POST   | `/persist/friends_use_friendDW/`                   | Use ally (increment help) |
| POST   | `/persist/friends_use_playerDW/`                   | Use anonymous helper      |

### Multiplayer Routes (`app/routes/multiplayer.py`)

| Method | Route                            | Description             |
| ------ | -------------------------------- | ----------------------- |
| POST   | `/multiplayer/new_player/`       | Set multiplayer profile |
| POST   | `/multiplayer/update_deck_name/` | Update deck/profile     |
| POST   | `/multiplayer/redeemcodeDW/`     | Redeem code API         |

### Analytics Routes (`app/routes/analytics.py`)

| Method | Route                           | Description        |
| ------ | ------------------------------- | ------------------ |
| POST   | `/analytics/upsight`            | Analytics receiver |
| POST   | `/analytics/pvpmatch`           | PVP match data     |
| POST   | `/dw_leaderboard/fetchentries/` | PVP leaderboard    |

### Admin Routes (`app/routes/admin.py`)

| Method   | Route                                            | Description                                                                      |
| -------- | ------------------------------------------------ | -------------------------------------------------------------------------------- |
| GET/POST | `/admin`                                         | Login (auto-creates first admin)                                                 |
| POST     | `/admin/passkey`                                 | Passwordless login with a 6-digit passkey only                                   |
| GET      | `/admin/home`                                    | Dashboard                                                                        |
| GET      | `/admin/profile`                                 | Secret profile (email, password, passkey)                                        |
| POST     | `/admin/profile/email`                           | Update admin email                                                               |
| POST     | `/admin/profile/password`                        | Change admin password                                                            |
| POST     | `/admin/profile/passkey`                         | Set/replace 6-digit passkey                                                      |
| POST     | `/admin/profile/passkey/disable`                 | Disable passkey login                                                            |
| GET      | `/admin/logout`                                  | Logout                                                                           |
| GET/POST | `/admin/versions`                                | Version management                                                               |
| GET      | `/admin/server`                                  | Server/backups + interval & Telegram settings                                    |
| GET      | `/admin/server/backup`                           | Trigger backup (and send to Telegram)                                            |
| POST     | `/admin/server/settings`                         | Save backup interval / Telegram toggle                                           |
| POST     | `/admin/server/telegram_test`                    | Send a test Telegram message                                                     |
| POST     | `/admin/server/upload_backup`                    | Upload & restore a backup `.zip`                                                 |
| GET      | `/admin/server/pull`                             | Git pull                                                                         |
| GET/POST | `/admin/createadmin`                             | Create admin                                                                     |
| GET      | `/admin/players`                                 | Player list (sortable)                                                           |
| GET      | `/admin/top_pvp`                                 | Top PVP players ranked by Multiplayer Level (1 = Super Amadeus best, 25 = Dweeb) |
| GET      | `/admin/players/<uuid>`                          | Player detail                                                                    |
| GET      | `/admin/players/<uuid>/game`                     | Game data viewer                                                                 |
| POST     | `/admin/players/<uuid>/game/edit`                | Overwrite raw data                                                               |
| POST     | `/admin/players/<uuid>/edit`                     | Edit resources (incl. `MultiplayerName` to rename player)                        |
| POST     | `/admin/players/<uuid>/add_creature`             | Add creatures (1–10 at once)                                                     |
| POST     | `/admin/players/<uuid>/delete_creature/<idx>`    | Delete creature                                                                  |
| POST     | `/admin/players/<uuid>/delete_all_creatures`     | Delete all creatures                                                             |
| POST     | `/admin/players/<uuid>/delete_creatures_bulk`    | Multi-delete selected creatures                                                  |
| POST     | `/admin/players/<uuid>/max_creature/<idx>`       | Max single creature to 5★                                                        |
| POST     | `/admin/players/<uuid>/downgrade_creature/<idx>` | Reset a maxed creature to 1★                                                     |
| POST     | `/admin/players/<uuid>/add_card`                 | Add Auguments copies (1–10)                                                      |
| POST     | `/admin/players/<uuid>/add_card_copy/<idx>`      | Duplicate a single Auguments copy                                                |
| POST     | `/admin/players/<uuid>/delete_card/<idx>`        | Delete Auguments                                                                 |
| POST     | `/admin/players/<uuid>/delete_all_cards`         | Delete all Auguments                                                             |
| POST     | `/admin/players/<uuid>/delete_cards_bulk`        | Multi-delete selected Auguments                                                  |
| POST     | `/admin/players/<uuid>/add_all_creatures`        | Add all 625 collectible creatures (skips `TutorialOnly`)                         |
| POST     | `/admin/players/<uuid>/remove_invalid_creatures` | Remove tutorial-only creatures & clear `Zxcvbnm` PVP ban flag                    |
| POST     | `/admin/players/<uuid>/max_all_creatures`        | Max all creatures to 5★                                                          |
| POST     | `/admin/players/<uuid>/add_max_creature`         | Add single max creature                                                          |
| POST     | `/admin/players/<uuid>/add_all_cards`            | Add all 695 Auguments                                                            |
| POST     | `/admin/players/<uuid>/add_all_leaders`          | Add all 32 base heroes (skips skins)                                             |
| POST     | `/admin/players/<uuid>/add_leader`               | Add single hero; a skin ID is attached to its base hero's `OwnedSkins`           |
| POST     | `/admin/players/<uuid>/delete_leader/<idx>`      | Delete single leader                                                             |
| POST     | `/admin/players/<uuid>/delete_all_leaders`       | Delete all leaders                                                               |
| POST     | `/admin/players/<uuid>/delete_leaders_bulk`      | Multi-delete selected leaders                                                    |
| POST     | `/admin/players/<uuid>/add_all_skins`            | Attach all skins to the player's owned heroes via `OwnedSkins`                   |
| POST     | `/admin/players/<uuid>/max_resources`            | Max all currencies preset                                                        |
| POST     | `/admin/players/<uuid>/gift`                     | Send a Gift/Reward to the player's post office (`db_NewsMail.json`, per `PlayerID`) |
| POST     | `/admin/players/<uuid>/loadouts/set`             | Set team (loadout) count 1-50; grows with blank team lines                       |
| POST     | `/admin/players/<uuid>/loadouts/creatures`       | Set creatures per team 1-10; shrinking drops the extra slots                     |
| GET      | `/admin/players/<uuid>/export_save`              | Download save as JSON                                                            |
| POST     | `/admin/players/<uuid>/import_save`              | Upload & replace save JSON                                                       |
| POST     | `/admin/players/<uuid>/fix_save`                 | Detect & repair broken save fields / duplicate creature IDs (deletes nothing)    |
| POST     | `/admin/players/<uuid>/transfer_progress`        | Copy progress to target UUID (keeps target name & currencies; source untouched)  |
| POST     | `/admin/players/<uuid>/reset_save`               | Reset save to starter values                                                     |
| POST     | `/admin/players/<uuid>/delete`                   | Delete player account                                                            |
| POST     | `/admin/players/bulk_action`                     | Bulk ban, unban, or delete players                                               |
| GET      | `/admin/players/<uuid>/ban`                      | Ban player                                                                       |
| GET      | `/admin/players/<uuid>/unban`                    | Unban player                                                                     |
| GET      | `/admin/bannedplayers`                           | Banned players list                                                              |
| GET      | `/admin/bannedips`                               | Banned IPs list                                                                  |
| POST     | `/admin/ipban`                                   | Ban IP                                                                           |
| GET      | `/admin/ipban/<ip>/unban`                        | Unban IP                                                                         |
| GET      | `/admin/pvp_banlist`                             | PVP creature & leader ban list manager                                           |
| POST     | `/admin/pvp_banlist/add_creature`                | Add creature to PVP ban list                                                     |
| POST     | `/admin/pvp_banlist/remove_creature/<id>`        | Remove creature from PVP ban list                                                |
| POST     | `/admin/pvp_banlist/add_leader`                  | Add leader to PVP ban list                                                       |
| POST     | `/admin/pvp_banlist/remove_leader/<id>`          | Remove leader from PVP ban list                                                  |
| POST     | `/admin/pvp_banlist/edit_raw`                    | Save raw JSON for PVP ban list                                                   |
| GET      | `/admin/maintenance`                             | Maintenance toggle                                                               |
| POST     | `/admin/maintenance/live`                        | Save the live status JSON (`data/persist/live.json`)                             |
| GET      | `/admin/logs`                                    | Player logs (paginated)                                                          |
| GET      | `/admin/upsight`                                 | Analytics logs (paginated)                                                       |
| GET      | `/admin/misc`                                    | Misc tools                                                                       |
| POST     | `/admin/misc/loadout_count`                      | Set global `StartingLoadoutCount` blueprint value (default team lines)           |
| POST     | `/admin/misc/creatures_on_team`                  | Set global `CreaturesOnTeam` blueprint value (slots per team)                    |
| GET      | `/admin/redeemcodes`                             | Redeem codes list                                                                |
| POST     | `/admin/redeemcodes/add`                         | Add/update redeem code                                                           |
| POST     | `/admin/redeemcodes/delete/<code>`               | Delete redeem code                                                               |
| POST     | `/admin/redeemcodes/toggle/<code>`               | Toggle redeem code                                                               |
| GET      | `/admin/creatures`                               | Creature book (searchable)                                                       |
| GET      | `/admin/cards`                                   | Auguments book (searchable)                                                      |
| GET      | `/admin/leaders`                                 | Leader book (searchable)                                                         |

## Key Functions

| Function                                               | Location       | Description                                                                |
| ------------------------------------------------------ | -------------- | -------------------------------------------------------------------------- |
| `DecryptGameData(game)`                                | `app/utils.py` | Decode base64+gzip game save to dict                                       |
| `EncryptGameData(game, username)`                      | `app/utils.py` | Encode dict to base64+gzip game save (`str`, never `bytes`)                |
| `DatabaseBackend()` / `IsPostgres()`                   | `app/utils.py` | `"postgres"` / `"sqlite"` for the active SQLAlchemy URI                     |
| `DumpDatabase()`                                       | `app/utils.py` | `pg_dump` (or sqlite file copy) of the active DB                           |
| `RestoreDatabaseSql(path)`                             | `app/utils.py` | `psql` restore; disposes pooled connections first (locks)                  |
| `MigrateSqliteDatabase(path, replace)`                 | `app/utils.py` | Copy every SQLite table into the active DB (coercing types)                |
| `SyncPostgresSequences()`                              | `app/utils.py` | Advance `SERIAL` sequences to `MAX(id) + 1` after a row copy               |
| `FormatTimestamp(value, utc)`                          | `app/utils.py` | Render a unix timestamp for display (`fmt_ts` Jinja filter)                |
| `Backup()`                                             | `app/utils.py` | Zip `pg_dump` + persist folder to `backup/`                                |
| `Log(category, message)`                               | `app/utils.py` | Write to daily log file                                                    |
| `PlayerLog(ip, player, message)`                       | `app/utils.py` | Create Logs DB entry                                                       |
| `DiscordWebhookMessage(message)`                       | `app/utils.py` | Send Discord webhook + log to AdminActivity                                |
| `IsUserBanned(username, ip)`                           | `app/utils.py` | Check active (non-expired) ban list                                        |
| `SystemBan(username)`                                  | `app/utils.py` | Auto-ban (anti-cheat), permanent                                           |
| `GetBanExpiry(duration, amount, unit)`                 | `app/utils.py` | Resolve a ban duration to a unix expiry (0 = permanent)                    |
| `FormatBanExpiry(expires)`                             | `app/utils.py` | Human-readable ban expiry (`"Permanent"` when 0/NULL)                      |
| `FindBrokenSaveIssues(game)`                           | `app/utils.py` | Return list of missing/invalid save fields & duplicate creature IDs        |
| `RepairGameData(game, username, fallback_name)`        | `app/utils.py` | Fill missing fields / fix duplicate IDs without deleting data              |
| `BuildTransferredGame(source, target, username, name)` | `app/utils.py` | Copy progress to a target save keeping target name & currencies            |
| `AddNewsMailGift(player, type, id, amount, title, body)` | `app/utils.py` | Append a per-player gift to `db_NewsMail.json` (claimable mail)          |
| `AddNewsMailNotice(player, title, body)`               | `app/utils.py` | Append a reward-less notice mail (for direct-granted items)                |
| `StripLegacyAdminMails(game)`                          | `app/utils.py` | Remove leftover `ADMIN_*` mails from a save (old broken format)            |
| `GetGiftCatalog()`                                     | `app/utils.py` | Item choices (creatures, Auguments, heroes, XP materials) for the composer |
| `SetLoadoutCount(game, count)`                         | `app/utils.py` | Resize `game["Loadouts"]` team lines (1-50); pads new teams to match        |
| `SetTeamCreatureCount(game, count)`                    | `app/utils.py` | Resize `CreatureID0..n` slots on every team (1-10, truncates on shrink)     |
| `LoadoutCreatureCount(loadout)`                        | `app/utils.py` | How many creature slots a team dict currently exposes                        |
| `DescribeBattleRecord(record, banned_c, banned_l)`     | `app/utils.py` | Battle row + opponent loadout & PVP ban flags (no-season = friendly)        |
| `UpdateLastOnline(player_id)`                          | `app/utils.py` | Update last_online timestamp                                               |
| `GetAllyInfo(player_id, isally)`                       | `app/utils.py` | Build ally info dict                                                       |
| `GetPlayerWins(player_id)`                             | `app/utils.py` | Count PVP wins this season                                                 |
| `GetXPForRank(rank)`                                   | `app/utils.py` | Get required cumulative RankXP for a given player rank                     |
| `GetRankForXP(xp)`                                     | `app/utils.py` | Calculate player rank from cumulative RankXP                               |
| `GetRankXPTable()`                                     | `app/utils.py` | Return full level -> XP dictionary from blueprints                         |
| `GetPvpRankName(level)`                                | `app/utils.py` | PVP league name for a MultiplayerLevel (1 = Super Amadeus)                 |
| `GetTutorialOnlyCreatureIds()`                         | `app/utils.py` | Set of `TutorialOnly` creature IDs (non-collectible)                       |
| `IsTutorialOnlyCreature(id)`                           | `app/utils.py` | True if a creature is tutorial-only                                        |
| `GetLeaderSkinBase(id)`                                | `app/utils.py` | Base hero ID if the ID is a skin, else `None`                              |
| `GetLeaderSkins(base_id)`                              | `app/utils.py` | Skin IDs belonging to a base hero                                          |
| `NormalizeLeaders(leaders)`                            | `app/utils.py` | Fold skin entries into their base hero's `OwnedSkins`                      |
| `InvalidUsername(username)`                            | `app/utils.py` | Validate username                                                          |
| `IPFromRequest(request)`                               | `app/utils.py` | Extract client IP                                                          |
| `SafeLoginNext(target, default)`                       | `app/utils.py` | Same-site post-login redirect target (rejects `//host`, `://`)             |
| `LoadSettings()` / `SaveSettings(d)`                   | `app/utils.py` | Read/write `data/persist/settings.json` (backup interval, Telegram toggle) |
| `GetBackupIntervalHours()`                             | `app/utils.py` | Effective backup interval (setting → `BACKUP_INTERVAL_HOURS` → 4)          |
| `ReadMiscParam(name)` / `WriteMiscParam(name, value)` | `app/utils.py` | Read/write a `db_MiscParams.json` blueprint parameter                       |
| `SendTelegramDocument(path, caption)`                  | `app/utils.py` | Send a file to the admin Telegram chat via bot                             |
| `SendBackupToTelegram(zip_path)`                       | `app/utils.py` | Send a (latest) backup archive to Telegram                                 |
| `RunScheduledBackup()`                                 | `app/utils.py` | Run a backup when the configured interval elapsed                          |
| `GetLiveStatus()`                                      | `app/utils.py` | Live status payload with a fresh `now` timestamp                           |
| `LoadLiveStatus()` / `SaveLiveStatus(d)`               | `app/utils.py` | Read/write `data/persist/live.json` (maintenance, notices, flags, texts)   |

## Configuration & Assets

- **`.env`** (gitignored, copy `.env.example`): optional `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_ID`, optional `BACKUP_INTERVAL_HOURS`
- **Database**: PostgreSQL `cardwarskingdom` by default (`app/__init__.py::ResolveDatabaseUri` normalises `postgres://` / `postgresql://` / `postgres+psycopg2://` onto `postgresql+psycopg2://` and keeps query strings); `DATABASE_URL=sqlite:///instance/cardwarskingdom.db` opts into SQLite
- **Migration**: `python migrate_sqlite_to_postgres.py [--sqlite PATH] [--keep] [--dry-run] [--yes]` copies an existing SQLite file into the active DB and resyncs sequences
- **Runtime settings**: `data/persist/settings.json` — `backup_interval_hours`, `backup_to_telegram`, `last_backup`
- **Live status**: `data/persist/live.json` — admin-editable payload served at `GET /persist/static/live` (`maintenance`, `maint_ended`, `notices`, `poll`, `flags`, `texts`, `content`, `ui`, `restart`); `now` is injected per request, the file is optional and falls back to defaults in `app/services/live.py`
- **Auto-backup**: scheduler thread checks every minute in `app/__init__.py::run_scheduler` → `RunScheduledBackup()`; backups go to `backup/*.zip` and optionally Telegram
- **Restore**: `POST /admin/server/upload_backup` accepts a zip with `cardwarskingdom.sql` (pg_dump) or a legacy `cardwarskingdom.db` (routed through `MigrateSqliteDatabase`), plus `persist/`, after taking a safety snapshot

## Trade Market

Player-to-player trading, ported from the production server into `app/`. A
`trade_*` request is form-encoded POST and answers `{"success": bool, ...}`.

**Models** (`app/models/__init__.py`): `TradeCoinBalance` (`trade_coin_balance`),
`TradeEscrow` (`trade_escrow`), `TradeListing` (`trade_listing`),
`TradeOffer` (`trade_offer`), `TradeDelta` (`trade_pending`), `TradeLog` (`trade_log`).

**Endpoints** (`app/routes/trade.py`, blueprint `trade_bp`):

| Method | Route | Function |
| ------ | ----- | -------- |
| POST | `/persist/trade_balanceDW/` | Coin balance |
| POST | `/persist/trade_syncDW/` | Pending add/remove deltas for the app |
| POST | `/persist/trade_listDW/` | List a creature (moves it to escrow) |
| POST | `/persist/trade_browseDW/` | Market list (`v=2` paged/filtered) |
| POST | `/persist/trade_buyDW/` | Buy a listing |
| POST | `/persist/trade_cancelDW/` | Cancel own listing (returns creature) |
| POST | `/persist/trade_buycoinsDW/` | Buy trade coins with gems/coins |
| POST | `/persist/trade_offerDW/` | Create a trade offer |
| POST | `/persist/trade_offers_receivedDW/` | Offers addressed to a player |
| POST | `/persist/trade_inventoryDW/` | Another player's tradeable creatures |
| POST | `/persist/trade_acceptDW/` | Accept an offer |
| POST | `/persist/trade_declineDW/` | Decline/cancel an offer |

**Key functions** (`app/services/trade_market.py`): `_tload_save` / `_twrite_save`
(read/write a player's save; the latter records `TradeDelta` rows and stores via
`EncryptGameData`), `ApplyTradeDeltasToGame` (called from the save PUT handler in
`app/routes/game.py` to correct a stale upload), `_market_page`, `_market_expire`,
`PublicId`/`RealId` (hide real ids in the market), `_ttrade_refused` (device check).

**Admin control panel** (`app/routes/admin/market.py`, template `admin_market.html`,
nav link in `admin_base.html`): `GET /admin/market` lists listings (filter by
`?status=`), escrow, open offers, trade-coin balances and the trade log, with
`POST /admin/market/listing/<id>/{remove,delete}`, `/admin/market/offer/<id>/cancel`,
`/admin/market/escrow/<id>/delete`, `/admin/market/balance/set`, `/admin/market/expire`
(forced expiry sweep) and `/admin/market/purge` (drop closed listings + orphan escrow).

### Redeem codes

`POST /multiplayer/redeemcodeDW/` (`app/routes/multiplayer.py`) mirrors the
production server exactly: it reads the `redeemcode` form field (falls back to
`code`) and the `Player-Id` header, and answers the production JSON shape
`{"success", "reason", "data", "error"}` plus, on success, `rewards`, `deliver`
and `fields` (`level1`/`level2`/`gs`/`gf`/`seq`/`reason`). `reason` is one of
`OK`/`EMPTY`/`INVALID`/`USED`/`BUSY`; refusals carry the legacy `error` text
("invalid redeemcode" / "maximum reword count reached"). Rewards are still
applied to the player's save directly.

### Daily Gift roulette

`POST /persist/user_action2/` (`app/routes/game.py::UserAction2`) now handles the
`evt="roulette spin"` event the same way production does: the **server** rolls the
winning slice and returns it as `fields.spin` in the envelope
`{"success": true, "data": "{\"fields\": {...}}"}` (with `gs`/`gf`/`gv`/`ge`/`gc`,
resulting balances `level1`..`level7`, `reason`, `seq` and `handle`). The wheel is
`data/persist/Blueprints/db_DailyGift.json`; the **odds** come from
`db_DailyGiftRouletteWeights.json` (its explicit `Weight` per index — a balanced
wheel), falling back to `db_DailyGift`'s `max(1, round(10000 / Rarity))`. Helpers:
`GetRoulettePrizes`, `RollRoulettePrize`, `ApplyRoulettePrize`
(`app/services/game_data.py`). Currency prizes are credited to the save; creature
prizes are granted by the client from its own pool.

A spin is once per 24h, tracked in the `roulette_state` table (`spin_at`,
`spin_tokens`). `evt="roulette reset"` spends `ROULETTE_RESET_COST` (1250)
wishbones from the save's `PvpCurrency` and adds a token so one more spin passes
the cooldown; it answers `reason` `OK`/`NOT_ENOUGH_PVP`.

### Store purchases

`POST /persist/user_action2/` with `evt="purchase"` mirrors production's
`claims.purchase`: the app names what it buys (`ctx = "<kind>:<id>[:<count>]"`,
e.g. `creature:ElderBruteWoad_Store`, `leader:Leader_Finn`, `gacha:Premium:10`,
`inventory:`, `stamina:`), and the **server** charges its own price from the
blueprints (`PurchasePrice`, `app/services/game_data.py`) and replies with
`fields.reason` (`OK`/`NOT_ENOUGH`/`UNKNOWN_ITEM`), `fields.cb` (bucket) and
`fields.cc` (charged) plus the resulting balances. Currencies live in the save:
`gems` debit `FreeHardCurrency` then `PaidHardCurrency`, `coins` debit
`SoftCurrency`, `pvp` debits `PvpCurrency`; store creatures are granted into
`Inventory`. Already-owned heroes/skins are never charged twice.

### PVP banlist response

`GET /persist/static/pvp_banlist` answers the production shape:
`banned_creatures`, `banned_leaders`, `banned_cards`, `banned_floops`,
`banned_augments`, `server_time`, `active_bans`. Values come from the
admin-managed `data/persist/pvp_banlist.json`, merged with any time-active seasons
in `data/persist/Blueprints/db_PVPBanlist.json` (`BuildPvpBanlistResponse`,
`app/services/admin.py`). A banned floop is also emitted as a banned_card.

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
- **Game data changes**: Always use `EncryptGameData(game, player)` to save — it handles the `username=&data=` format and returns `str` (PostgreSQL text columns reject `bytes`)
- **Typed columns**: Never write display values back onto ORM rows (e.g. converting a timestamp to a formatted string for a template) — the strict-typed column fails on flush. Format in Jinja with the `fmt_ts` filter (`FormatTimestamp`) or build a plain dict for the template
- **Logging**: Use `Log("category", "message")` for file logs, `DiscordWebhookMessage()` for alerts
- **Admin access**: All admin routes check `@login_required` + `isAdmin(current_user)`.
  - Decorator order must stay `@admin_bp.route(...)` **first (top)**, `@login_required` **second**: Flask registers the view at decoration time, so putting `@login_required` above the route wraps only the module name and the guard never runs — every anonymous request then falls into `isAdmin` and returns a bare `404` page
  - `/admin` and `/admin/passkey` are intentionally unguarded (login endpoints)
  - Anonymous requests are redirected to `/admin?next=…` (`login_manager.login_view = "/admin"`); `SafeLoginNext` validates the return path after login
- **Blueprints**: All routes use Flask Blueprints registered in `app/routes/__init__.py`
- **File paths**: Always use `ROOT_DIR` for file access (defined in each route file)
- **Confirm dialogs**: Use SweetAlert2 via `cwkConfirm(message)` / `cwkAlert(message)` (defined in `admin_base.html`); never native `confirm()`/`alert()`. Inline `onclick="return confirm('...')"` is auto-upgraded to a `data-confirm` attribute at load
- **Leader skins**: Add skins via `/admin/players/<uuid>/add_leader` (a skin ID attaches to its base hero's `OwnedSkins`); the player page has a per-hero "Add Skin" picker

## Running

```bash
pip install -r requirements.txt
createdb cardwarskingdom             # once; or set DATABASE_URL
python migrate_sqlite_to_postgres.py # only when importing an old SQLite file
python app.py                    # Default port 5000
python app.py --port 8080        # Custom port
python app.py --debug            # Debug mode
```

The first admin account is auto-created on first login — check console output for the random password.
