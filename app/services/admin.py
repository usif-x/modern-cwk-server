import time as _time

from ._common import *
from .backup import *
from .database import *
from .game_data import *
from .player import *


def time_ago_string(date_time):
    now = datetime.now()
    time_difference = now - date_time
    hours = time_difference.seconds // 3600
    minutes = (time_difference.seconds // 60) % 60
    if time_difference.days > 0:
        return f"{time_difference.days} days ago"
    elif hours > 0:
        return f"{hours} {'hour' if hours == 1 else 'hours'} ago"
    elif minutes > 0:
        return f"{minutes} {'minute' if minutes == 1 else 'minutes'} ago"
    else:
        return f"{time_difference.seconds} seconds ago"


def isAdmin(user):
    if not user.is_authenticated:
        return False
    db_user = Admin.query.filter_by(username=user.username).first()
    return db_user is not None


def SafeLoginNext(target, default="/admin/home"):
    """Where to send an admin after signing in.

    Only same-site relative paths are accepted so a crafted `?next=`
    cannot bounce the session off-site.
    """
    if not isinstance(target, str):
        return default
    target = target.strip()
    if not target.startswith("/") or target.startswith("//"):
        return default
    if "\\" in target or "://" in target or "\n" in target or "\r" in target:
        return default
    return target


def GetPlayerWins(player_id):
    db_user = Player.query.filter_by(username=player_id).first()
    if db_user is None:
        return None
    if db_user.game is None or db_user.game == b"" or db_user.game == b" ":
        return None
    if IsUserBanned(player_id):
        return None
    try:
        game = DecryptGameData(db_user.game)
    except Exception:
        return None
    if game["Zxcvbnm"]:
        return None
    currentSeason = ""
    with open(
        os.path.join(ROOT_DIR, "data/persist/Blueprints/db_PVPSeasons.json")
    ) as f:
        seasons = json.load(f)
        seasons = list(filter(lambda x: "EndDate" in x, seasons))
        for season in seasons:
            if (
                int(_time.time())
                < datetime.strptime(season["EndDate"], "%m/%d/%Y").timestamp()
            ):
                currentSeason = season["Season"]
                break
        if currentSeason == "":
            currentSeason = seasons[-1]["Season"]
    if game["ActivePvpSeason"] != currentSeason:
        return None
    if int(game["PvpPlayed"]) == 0:
        return None
    wins = 0
    for battle in game["BattleHistory"]:
        if battle["youWon"] == True and battle["season"] == currentSeason:
            wins += 1
    return wins


def DescribeBattleRecord(record, banned_creatures, banned_leaders):
    """Enrich one BattleHistory row with the opponent loadout + ban flags.

    The save only records the *opponent's* side of a match
    (opponentLeader + creatures), so that is what gets screened.
    Records without a season are friendly matches — ban rules do not
    apply to them, so they are never flagged.
    """
    if not isinstance(record, dict):
        return None

    banned_creatures = banned_creatures or set()
    banned_leaders = banned_leaders or set()

    leader_id = record.get("opponentLeader") or ""
    raw_creatures = record.get("creatures") or []
    if not isinstance(raw_creatures, list):
        raw_creatures = []

    friendly = not str(record.get("season") or "").strip()

    creature_details = []
    banned_count = 0
    for creature_id in raw_creatures:
        if not isinstance(creature_id, str):
            continue
        banned = not friendly and creature_id in banned_creatures
        banned_count += 1 if banned else 0
        creature_details.append({"id": creature_id, "banned": banned})

    leader_banned = not friendly and bool(leader_id) and leader_id in banned_leaders
    banned_count += 1 if leader_banned else 0

    enriched = dict(record)
    enriched["friendly"] = friendly
    enriched["creature_details"] = creature_details
    enriched["leader_banned"] = leader_banned
    enriched["banned_count"] = banned_count
    enriched["has_ban"] = banned_count > 0
    return enriched


def GetPvpBanlist():
    filepath = os.path.join(ROOT_DIR, "data/persist/pvp_banlist.json")
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            Log("persist", f"Error reading pvp_banlist.json: {e}")
    return {
        "active_bans": [
            {
                "expires": "2099-12-31T23:59:59Z",
                "id": "global_permanent_bans",
                "name": "Permanent Bans (All Seasons)",
                "starts": "2020-01-01T00:00:00Z",
            }
        ],
        "banned_creatures": [],
        "banned_leaders": [],
    }


def BuildPvpBanlistResponse():
    """The /persist/static/pvp_banlist payload in the production shape.

    The game client reads banned_creatures / banned_leaders / banned_cards /
    banned_floops / banned_augments / server_time / active_bans. Values come from
    the admin-managed pvp_banlist.json plus (when the file exists) the seasonal
    db_PVPBanlist.json, filtered by server time like production.
    """
    src = GetPvpBanlist()

    creatures = [c for c in (src.get("banned_creatures") or []) if c]
    leaders = [l for l in (src.get("banned_leaders") or []) if l]
    cards = [c for c in (src.get("banned_cards") or []) if c]
    floops = [f for f in (src.get("banned_floops") or []) if f]
    augments = [a for a in (src.get("banned_augments") or []) if a]

    # Seasonal blueprint (same source production reads), active by server time.
    for season in _ReadPvpSeasons():
        if not _season_active(season):
            continue
        for cid in season.get("banned_creatures", []) or []:
            if cid and cid not in creatures:
                creatures.append(cid)
        for lid in season.get("banned_leaders", []) or []:
            if lid and lid not in leaders:
                leaders.append(lid)
        for cid in season.get("banned_cards", []) or []:
            if cid and cid not in cards:
                cards.append(cid)
        for aid in season.get("banned_augments", []) or []:
            if aid and aid not in augments:
                augments.append(aid)

    # A banned floop is also a PvP-banned card (production rule for older apps).
    for cid in floops:
        if cid not in cards:
            cards.append(cid)

    active = []
    for ban in src.get("active_bans") or []:
        if not isinstance(ban, dict):
            continue
        active.append(
            {
                "id": ban.get("id", "unknown"),
                "name": ban.get("name", "Unnamed Ban Period"),
                "starts": ban.get("starts") or ban.get("start_date") or "",
                "expires": ban.get("expires") or ban.get("end_date") or "",
            }
        )

    return {
        "banned_creatures": creatures,
        "banned_leaders": leaders,
        "banned_cards": cards,
        "banned_floops": floops,
        "banned_augments": augments,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "active_bans": active,
    }


def _ReadPvpSeasons():
    try:
        with open(
            os.path.join(ROOT_DIR, "data/persist/Blueprints/db_PVPBanlist.json"),
            "r",
            encoding="utf-8",
        ) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    seasons = data.get("seasons") if isinstance(data, dict) else None
    return seasons if isinstance(seasons, list) else []


def _season_active(season):
    if not isinstance(season, dict):
        return False
    try:
        start = datetime.fromisoformat(str(season.get("start_date", "")).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(season.get("end_date", "")).replace("Z", "+00:00"))
    except ValueError:
        return False
    now = datetime.now(timezone.utc)
    return start <= now <= end


def SavePvpBanlist(data):
    filepath = os.path.join(ROOT_DIR, "data/persist/pvp_banlist.json")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return True
