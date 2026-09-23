# Card Wars Kingdom Server

A Flask-based backend server for the mobile game **Card Wars Kingdom**. Handles game persistence, multiplayer, PVP leaderboards, friend systems, and provides a full admin web panel.

## Features

- **Game Save Persistence** — Encrypted storage of player game data (base64 + gzip JSON)
- **Multiplayer & PVP** — Player profiles, deck configurations, seasonal PVP leaderboards
- **PVP Ban List Management** — Global & seasonal bans for specific creatures and leaders via `/persist/static/pvp_banlist` with admin control panel and one-click ban toggle in reference books
- **Friend System** — Friend discovery, friend requests, ally sharing, and anonymous helpers
- **Multi-Reward Redeem Codes** — Promotional gift codes supporting:
  - Currencies: Soft Currency (Coins), Hard Currency (Gems), Free Gems, PVP Wishbones, and Evolution Shards
  - Game Items: Creatures (with custom star ratings 1–5★), Auguments (with custom quantities), and Heroes/Leaders
  - Automated duplicate redemption tracking via `UsedRedeemCodes`
- **Interactive Player Event Logs** — Audit trail with smart classification badges, compact single-line previews, and a full-featured modal dialog with structured parameter cards, syntax-highlighted JSON viewer, and instant clipboard copy
- **Admin Panel** — Modern, responsive grid admin panel inspired by shadcn/ui (light/dark mode, Tailwind CSS, Lucide icons):
  - Player management (view, edit resources, rank sync, ban/unban, JSON save export/import)
  - Creature, action card, and leader tools (bulk multi-select deletion, delete all, max to 5★, add all 625 collectible creatures, 695 cards, and 32 base heroes)
  - Heroes and skins are handled separately: "Add All Heroes" adds only base leaders, and "Add All Skins" attaches skins to owned heroes via `OwnedSkins` (never as independent heroes)
  - Tutorial-only creatures are automatically skipped so granting them can't trigger the client's `Zxcvbnm` PVP-ban flag; a cleanup button removes any already present and clears the flag
  - Interactive reference books for all creatures, Auguments, and leaders
  - **Top PVP Players** leaderboard ranked by Multiplayer Level (`1` = Super Amadeus best → `25` = Dweeb), with league names and a champion spotlight
  - Modern, theme-aware confirmation dialogs (SweetAlert2); per-hero "Add Skin" picker in the heroes section
  - PVP ban list manager with raw JSON editor
  - **Secret Profile** — per-admin email, password change, and a passwordless 6-digit login passkey
  - Server backups (configurable interval, Telegram delivery, upload & restore), version management, maintenance mode, and logs
- **Progress Transfer** — Copy all account progress (creatures, Auguments, leaders, unlocks, rank, quests) from one account to another. The target keeps its own name and currencies (gems, coins, wishbones, etc.); the source account is left untouched
- **Broken Save Detection & Repair** — The admin panel automatically detects missing/invalid save fields and duplicate creature IDs. A one-click **Fix Save** repairs the structure without deleting any items
- **Temporary Bans** — Bans support an optional expiry. Admins pick a preset duration (hour, day, week, month) or a custom amount/unit; expired bans are treated as inactive and purged automatically
- **Automatic Telegram Backups** — Backups run on a configurable interval (default 4h, can be set to 1h or any custom value) and are delivered to an admin Telegram chat via bot (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_ADMIN_ID` in `.env`). Backups can also be uploaded/restored from the admin panel
- **Creature & Card Tooling** — Add 1–10 copies at once, max/downgrade a creature from the same button, and duplicate Auguments with one click
- **Anti-Cheat & Rank Sync** — Device binding, automated Rank & RankXP synchronization based on game blueprint curves (`db_PlayerRanks.json`), leader level jump validation, and ACTk detection
- **Auto-Backup** — Automatic full database + persist directory backups every 4 hours

## Tech Stack

- **Python 3.11+**
- **Flask** + **SQLAlchemy** (SQLite)
- **Flask-Login** (session authentication)
- **Flask-Bcrypt** (password hashing)
- **Tailwind CSS** + **Lucide Icons**
- **shadcn/ui** design system (responsive grid, accessible components, light/dark mode)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server (default port 5000)
python app.py

# Custom port
python app.py --port 8080

# Debug mode
python app.py --debug
```

> **Note**: The first admin account is auto-created on first login if no admin exists. Check the terminal output for the generated password.

## Deploy to Heroku

Install the [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli), log in, and run these commands from the project root:

```bash
heroku login
heroku create your-app-name
heroku config:set SECRET_KEY="$(openssl rand -hex 32)"
heroku config:set TELEGRAM_BOT_TOKEN="your-token" TELEGRAM_ADMIN_ID="your-chat-id"
git push heroku main
heroku open
```

The `Procfile` starts the app with Gunicorn and binds it to Heroku's `$PORT`. Telegram variables are optional. Heroku's filesystem is ephemeral, so this app's SQLite database, logs, backups, and runtime settings can be lost when the dyno restarts. Use an external persistent database and storage service before relying on the deployment for production data.

## Project Structure

```
cwk-server/
├── app.py                  # Thin entry point
├── app/
│   ├── __init__.py         # Flask app factory, globals, scheduler, DB migration
│   ├── config.py           # .env loader (Telegram bot token / admin id, backup interval)
│   ├── models.py           # Database models (Player, Admin, Bans, RedeemCode, etc.)
│   ├── utils.py            # Helpers (encryption/decryption, backups, Telegram, anti-cheat, XP tables)
│   └── routes/
│       ├── __init__.py     # Blueprint registration
│       ├── game.py         # Client-facing game API & PVP ban list
│       ├── admin.py        # Admin panel routes & moderation
│       ├── multiplayer.py  # Multiplayer routes & redeem code API
│       ├── friends.py      # Friend system routes
│       └── analytics.py    # Analytics & PVP leaderboard
├── templates/              # 22 Jinja2 admin templates (shadcn/ui style)
├── data/persist/           # Game data, blueprints, ban lists, logs
├── instance/               # SQLite database (cardwarskingdom.db)
└── backup/                 # Automatic zip backups (every 4 hours)
```

## API Endpoints

### Game API

| Method   | Endpoint                            | Description                                  |
| -------- | ----------------------------------- | -------------------------------------------- |
| GET      | `/`                                 | Health check                                 |
| GET/PUT  | `/persist/game`                     | Game save (by `Player-Id` header)            |
| GET/PUT  | `/persist/<uuid>/game`              | Game save (by UUID)                          |
| GET      | `/static/version.txt`               | Version string + maintenance status          |
| GET      | `/persist/static/manifest.json`     | Client asset manifest                        |
| GET      | `/persist/static/blueprints`        | All blueprints bundle (v1.18.0+)             |
| GET      | `/persist/static/Blueprints/<file>` | Blueprint data file                          |
| GET/POST | `/persist/static/pvp_banlist`       | Active PVP season & banned creatures/leaders |
| POST     | `/account/gcAuth/`                  | Game Center authentication                   |
| POST     | `/persist/user_action2/`            | User tracking action                         |

### Friend System

| Method | Endpoint                                           | Description                      |
| ------ | -------------------------------------------------- | -------------------------------- |
| GET    | `/persist/friends/<uuid>`                          | Get friend list                  |
| POST   | `/persist/friends_find_candidatesDW/`              | Search for friends               |
| POST   | `/persist/friends_request_withmyinfoDW/`           | Send friend request              |
| POST   | `/persist/friends_confirm_request_withmyinfoDW/`   | Accept request                   |
| GET    | `/persist/friends_deny_request/<uuid>/<invite_id>` | Deny request                     |
| GET    | `/persist/friends_remove/<uuid>/<invite_id>`       | Remove friend                    |
| POST   | `/persist/friends_use_friendDW/`                   | Use ally helper (increment help) |
| POST   | `/persist/friends_use_playerDW/`                   | Use anonymous helper             |

### Multiplayer & Redeem Codes

| Method | Endpoint                         | Description                                             |
| ------ | -------------------------------- | ------------------------------------------------------- |
| POST   | `/multiplayer/new_player/`       | Set multiplayer profile                                 |
| POST   | `/multiplayer/update_deck_name/` | Update deck/profile & anti-cheat check                  |
| POST   | `/multiplayer/redeemcodeDW/`     | Redeem code for currencies, creatures, cards, or heroes |
| POST   | `/dw_leaderboard/fetchentries/`  | PVP leaderboard entries                                 |

### Admin Panel

| Endpoint                                         | Description                                                                         |
| ------------------------------------------------ | ----------------------------------------------------------------------------------- |
| `/admin`                                         | Login & first-time setup                                                            |
| `/admin/home`                                    | System dashboard with stats & recent activity                                       |
| `/admin/players`                                 | Sortable player list with bulk ban/unban/delete                                     |
| `/admin/top_pvp`                                 | Top PVP Players ranked by Multiplayer Level (1 = best)                              |
| `/admin/players/<uuid>`                          | Player details, resource editor, multi-item actions (incl. change multiplayer name) |
| `/admin/players/<uuid>/game`                     | Structured game save viewer and raw editor                                          |
| `/admin/players/<uuid>/fix_save`                 | Detect & repair broken save fields (no data deleted)                                |
| `/admin/players/<uuid>/transfer_progress`        | Copy progress to another account (keeps target name/currencies)                     |
| `/admin/players/<uuid>/add_card_copy/<idx>`      | Duplicate an action card                                                            |
| `/admin/players/<uuid>/downgrade_creature/<idx>` | Reset a maxed creature to 1★                                                        |
| `/admin/creatures`                               | Searchable Creature Book with PVP ban toggles                                       |
| `/admin/cards`                                   | Searchable Action Card Book                                                         |
| `/admin/leaders`                                 | Searchable Leader / Hero Book                                                       |
| `/admin/redeemcodes`                             | Redeem codes CRUD with autocomplete item picker                                     |
| `/admin/pvp_banlist`                             | Manage PVP banned creatures, leaders & raw JSON                                     |
| `/admin/logs`                                    | Audit log with interactive structured detail modal                                  |
| `/admin/bannedplayers`                           | Banned players list                                                                 |
| `/admin/bannedips`                               | Banned IP addresses list                                                            |
| `/admin/profile`                                 | Secret Profile: email, password, 6-digit passkey                                    |
| `/admin/passkey`                                 | Passwordless login using only a 6-digit passkey                                     |
| `/admin/server`                                  | Manual backups, interval/Telegram settings, upload & restore, git pull              |
| `/admin/versions`                                | Client version and maintenance toggles                                              |

## Game Data Format

Player saves are stored in `Player.game` as:

```
username=<uuid>&data=<base64(gzip(json))>
```

### Key JSON Fields

| Field                  | Description                                                |
| ---------------------- | ---------------------------------------------------------- |
| `SoftCurrency`         | Coins                                                      |
| `HardCurrency`         | Gems (total)                                               |
| `PaidHardCurrency`     | Purchased gems                                             |
| `FreeHardCurrency`     | Earned gems                                                |
| `PvpCurrency`          | PVP Wishbones                                              |
| `EvolutionShards`      | Evolution shards                                           |
| `InventorySpace`       | Inventory capacity                                         |
| `MultiplayerLevel`     | PVP league level (1 = Super Amadeus best, 25 = Dweeb)      |
| `BestMultiplayerLevel` | Best PVP league reached (kept equal to `MultiplayerLevel`) |
| `RankXP`               | Cumulative rank experience                                 |
| `Zxcvbnm`              | PVP ban flag (0 = active, 1 = banned)                      |
| `UsedRedeemCodes`      | Array of previously redeemed promotional code strings      |
| `Inventory`            | Inventory items array (`CR`, `CA`, `XP`)                   |
| `CardCollection`       | Action card collection dictionary                          |
| `Leaders`              | Owned leaders and unlocked skins                           |
| `BattleHistory`        | PVP battle logs                                            |

### Inventory Types

| `_T` | Type        | Fields                                                                      |
| ---- | ----------- | --------------------------------------------------------------------------- |
| `CR` | Creature    | `ID`, `Xp`, `StarRating`, `UniqueID`, `Favorite`, `Passive`, `PassiveFeeds` |
| `CA` | Action Card | `ID`, `UniqueID`, `CreatureUID`, `CreatureSlot`, `Favorite`                 |
| `XP` | XP Material | `ID`                                                                        |

## Database

SQLite database located at `instance/cardwarskingdom.db` with models:

- `player` — Player accounts, profiles, and encrypted saves
- `admin` — Admin credentials, rank, `email`, and optional `passkey` / `passkey_enabled`
- `bans` — UUID and IP ban entries (`expires` = unix timestamp, `0`/NULL = permanent)
- `logs` — Player activity audit logs
- `upsight_logs` — Analytics events
- `admin_activity` — Admin audit trail
- `redeem_code` — Promotional codes (`code`, `reward_type`, `reward_amount`, `reward_item`, `enabled`, `created_by`)

## Configuration & Assets

- **Flask secret key**: Automatically generated in `flaskkey`
- **Database URI**: SQLite at `instance/cardwarskingdom.db` (auto-migrated)
- **Blueprints**: Game data in `data/persist/Blueprints/` (`db_Creatures.json`, `db_ActionCards.json`, `db_Leaders.json`, `db_PlayerRanks.json`)
- **PVP Ban List**: JSON file at `data/persist/pvp_banlist.json`
- **Backups**: Compressed zip archives in `backup/`; interval configurable in the admin Server page (default 4h). Upload & restore supported
- **Runtime settings**: `data/persist/settings.json` (backup interval, Telegram toggle, last backup time)
- **.env** (gitignored, copy from `.env.example`):
  - `TELEGRAM_BOT_TOKEN` — Telegram bot token from @BotFather
  - `TELEGRAM_ADMIN_ID` — chat id that receives backups
  - `BACKUP_INTERVAL_HOURS` — optional default interval override
- **Discord Webhook**: Optional alerts URL stored in `discordwebhookurl`
