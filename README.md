# Card Wars Kingdom Server

A Flask-based backend server for the mobile game **Card Wars Kingdom**. Handles game persistence, multiplayer, PVP leaderboards, friend systems, and provides a full admin web panel.

## Features

- **Game Save Persistence** — Encrypted storage of player game data (base64 + gzip JSON)
- **Multiplayer** — Player profiles, deck management, PVP leaderboards
- **Friend System** — Friend requests, ally usage, anonymous helpers
- **Redeem Codes** — Create and manage reward codes (coins, gems, etc.)
- **Admin Panel** — Modern, responsive grid admin panel inspired by shadcn/ui
  - Player management (view, edit resources, ban/unban)
  - Creature, card, and leader management (add all, add single, max out)
  - Reference books for creature IDs, action card IDs, leader IDs
  - Game data viewer with structured sections
  - Server backups, version management, maintenance mode
  - Player logs and analytics
- **Anti-Cheat** — Device binding, leader level validation, auto-ban
- **Auto-Backup** — Database + data backed up every 4 hours

## Tech Stack

- Python 3.11+
- Flask + SQLAlchemy (SQLite)
- Flask-Login (authentication)
- Flask-Bcrypt (password hashing)
- Tailwind CSS + Lucide Icons
- shadcn/ui modern design system (responsive grid, light/dark mode)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
python app.py

# Custom port
python app.py --port 8080

# Debug mode
python app.py --debug
```

The first admin account is auto-created on first login. Check the console output for the random password.

## Project Structure

```
cwk-server/
├── app.py                  # Entry point
├── app/
│   ├── __init__.py         # Flask app factory, globals, scheduler
│   ├── models.py           # Database models (Player, Admin, Bans, etc.)
│   ├── utils.py            # Helpers (encrypt/decrypt, logging, etc.)
│   └── routes/
│       ├── game.py         # Client-facing game API
│       ├── admin.py        # Admin panel routes
│       ├── multiplayer.py  # Multiplayer routes
│       ├── friends.py      # Friend system routes
│       └── analytics.py    # Analytics + leaderboard
├── templates/              # 19 admin panel templates
├── data/persist/           # Game data, blueprints, logs
└── instance/               # SQLite database
```

## API Endpoints

### Game API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Health check |
| GET/PUT | `/persist/game` | Game save (by `Player-Id` header) |
| GET/PUT | `/persist/<uuid>/game` | Game save (by UUID) |
| GET | `/static/version.txt` | Version + maintenance status |
| GET | `/persist/static/Blueprints/<file>` | Blueprint data files |
| POST | `/account/gcAuth/` | Game Center authentication |

### Friend System

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/persist/friends/<uuid>` | Get friend list |
| POST | `/persist/friends_find_candidatesDW/` | Search for friends |
| POST | `/persist/friends_request_withmyinfoDW/` | Send friend request |
| POST | `/persist/friends_confirm_request_withmyinfoDW/` | Accept request |
| POST | `/persist/friends_use_friendDW/` | Use as ally |

### Multiplayer

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/multiplayer/new_player/` | Set multiplayer profile |
| POST | `/multiplayer/update_deck_name/` | Update deck/profile |
| POST | `/multiplayer/redeemcodeDW/` | Redeem a code |

### Admin Panel

| Endpoint | Description |
|----------|-------------|
| `/admin` | Login |
| `/admin/home` | Dashboard |
| `/admin/players` | Player list |
| `/admin/players/<uuid>` | Player detail/edit |
| `/admin/creatures` | Creature reference book |
| `/admin/cards` | Action card reference book |
| `/admin/leaders` | Leader reference book |
| `/admin/redeemcodes` | Redeem code management |
| `/admin/logs` | Player logs |
| `/admin/server` | Server/backups |

## Game Data Format

Player saves are stored as:
```
username=<uuid>&data=<base64(gzip(json))>
```

### Key Fields

| Field | Description |
|-------|-------------|
| `SoftCurrency` | Coins |
| `HardCurrency` | Gems |
| `PaidHardCurrency` | Purchased gems |
| `FreeHardCurrency` | Earned gems |
| `PvpCurrency` | Wishbones |
| `EvolutionShards` | Evolution shards |
| `InventorySpace` | Inventory capacity |
| `MultiplayerLevel` | MP rank |
| `RankXP` | Rank experience |
| `Zxcvbnm` | PVP ban flag (0/1) |
| `Inventory` | Items array (creatures, cards, materials) |
| `CardCollection` | Collected cards |
| `Leaders` | Owned leaders with skins |
| `BattleHistory` | PVP battle records |

### Inventory Types

| `_T` | Type | Fields |
|------|------|--------|
| `CR` | Creature | `ID`, `Xp`, `StarRating`, `UniqueID`, `Favorite`, `Passive` |
| `CA` | Action Card | `ID`, `CreatureUID`, `CreatureSlot` |
| `XP` | XP Material | `ID` |

## Database

SQLite database at `instance/cardwarskingdom.db` with tables:
- `player` — Player accounts and game data
- `admin` — Admin accounts
- `bans` — Player and IP bans
- `logs` — Player activity logs
- `upsight_logs` — Analytics events
- `admin_activity` — Admin action history
- `redeem_code` — Redeem codes

## Configuration

- **Flask secret key**: Auto-generated in `flaskkey`
- **Port**: Default 5000, override with `--port`
- **Database**: SQLite, auto-created on first run
- **Blueprints**: JSON files in `data/persist/Blueprints/`
- **Logs**: Daily files in `data/persist/logs/`
- **Backups**: Zip files in `backup/` (every 4 hours)
- **Discord webhook**: Optional, URL stored in `discordwebhookurl`
