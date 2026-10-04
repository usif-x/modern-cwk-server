from ._common import *
from .game_data import *


def ReadMiscParam(name, default=None):
    """Return a Parameter value from db_MiscParams.json (raw string)."""
    try:
        with open(MISC_PARAMS_PATH, "r") as f:
            params = json.load(f)
    except (OSError, ValueError):
        return default

    if isinstance(params, list):
        for entry in params:
            if isinstance(entry, dict) and entry.get("Parameter") == name:
                return entry.get("Value", default)
    return default


def WriteMiscParam(name, value):
    """Set a Parameter value in db_MiscParams.json. Returns the previous value."""
    try:
        with open(MISC_PARAMS_PATH, "r") as f:
            params = json.load(f)
    except (OSError, ValueError):
        params = []
    if not isinstance(params, list):
        params = []

    old_value = None
    found = False
    for entry in params:
        if isinstance(entry, dict) and entry.get("Parameter") == name:
            old_value = entry.get("Value")
            entry["Value"] = str(value)
            found = True
            break
    if not found:
        params.append({"Parameter": name, "Value": str(value)})

    with open(MISC_PARAMS_PATH, "w") as f:
        json.dump(params, f, indent=4)

    return old_value


def IPFromRequest(request: Request):
    ip = request.remote_addr
    if request.headers.getlist("X-Forwarded-For"):
        ip = request.headers.getlist("X-Forwarded-For")[0]
    return ip


def PlayerLog(ip, player, message):
    from app.models import Logs

    db_log = Logs(
        date=datetime.now().strftime("%Y-%m-%d"),
        time=datetime.now().strftime("%H:%M:%S"),
        player=player,
        ip=ip,
        message=message,
    )
    db.session.add(db_log)
    db.session.commit()


def InvalidUsername(username):
    username = username.lower()
    for char in badcharaters:
        if char in username:
            return True
    if username == "ua" or username == "guest":
        return True
    return False


def _BanActive(ban):
    if ban is None:
        return False
    expires = getattr(ban, "expires", None)
    if expires is None or int(expires) == 0:
        return True
    return int(expires) > int(_time.time())


def IsUserBanned(username, ip=None):
    db_user = Bans.query.filter_by(username=username).first()
    if _BanActive(db_user):
        return True
    if ip is None:
        return False
    db_ip = Bans.query.filter_by(username=ip).first()
    if _BanActive(db_ip):
        return True
    return False


BAN_DURATION_PRESETS = {
    "1h": 3600,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
    "3d": 259200,
    "1w": 604800,
    "2w": 1209600,
    "1m": 2592000,
}

BAN_DURATION_UNITS = {
    "hours": 3600,
    "days": 86400,
    "weeks": 604800,
    "months": 2592000,
}


def GetBanExpiry(duration, amount=0, unit="hours"):
    """Return a unix expiry timestamp for a ban duration. 0 means permanent."""
    if not duration or duration == "perm":
        return 0
    now = int(_time.time())
    if duration in BAN_DURATION_PRESETS:
        return now + BAN_DURATION_PRESETS[duration]
    if duration == "custom":
        multiplier = BAN_DURATION_UNITS.get(unit, 3600)
        try:
            amount = int(amount)
        except (ValueError, TypeError):
            amount = 1
        if amount < 1:
            amount = 1
        return now + amount * multiplier
    return 0


def FormatBanExpiry(expires):
    if expires is None or int(expires) == 0:
        return "Permanent"
    try:
        return datetime.utcfromtimestamp(int(expires)).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, TypeError, OSError):
        return "Permanent"


def SystemBan(username):
    Log("admin", "SYSTEM BANNED " + username)
    if not IsUserBanned(username):
        newban = Bans(
            username=username,
            bantype="userid",
            author="SYSTEM",
            time=int(_time.time()),
            expires=0,
        )
        db.session.add(newban)
        db.session.commit()
        DiscordWebhookMessage("SYSTEM performed ban on ID: " + username)


def UpdateLastOnline(player_id):
    user = Player.query.filter_by(username=player_id).first()
    if user is None:
        return None
    user.last_online = int(_time.time())
    db.session.commit()


def AllyBoxSpaceNotExceeded(player_id):
    user = Player.query.filter_by(username=player_id).first()
    if user is None:
        return None
    friends = json.loads(user.friends)
    friends_count = 0
    for friend in friends:
        if IsUserBanned(friend):
            continue
        friend_user = Player.query.filter_by(username=friend).first()
        if friend_user is None:
            continue
        friends_count += 1
    return friends_count < user.allyboxspace


def GetAllyInfo(player_id, isally):
    db_user = Player.query.filter_by(username=player_id).first()
    if db_user is None:
        return None
    if db_user.multiplayer_name is None:
        return None
    data = {
        "fields": {
            "user_id": db_user.username,
            "name": db_user.multiplayer_name,
            "icon": db_user.icon,
            "rankxp": db_user.leader_level,
            "helpcount": db_user.helpcount if db_user.helpcount is not None else "0",
            "anonymoushelpcount": (
                db_user.anonymoushelpcount
                if db_user.anonymoushelpcount is not None
                else "0"
            ),
            "helpercreatureid": db_user.leader,
            "helpercreature": db_user.helper_creature,
            "landscapes": db_user.landscapes,
            "ally": "1" if isally else "0",
            "sincelastactivedate": str(int(_time.time()) - db_user.last_online),
        }
    }
    return data
