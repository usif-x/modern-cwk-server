import base64
import gzip
import hashlib
import hmac
import json
import os
import shutil
import time as _time
from datetime import datetime
from io import BytesIO

import discord_webhook
from flask import Request

from app import db, badcharaters
from app.models import Admin, AdminActivity, Bans, Player

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_hash_string(source_value, key):
    hmac_sha256 = hmac.new(
        key.encode("utf-8"), source_value.encode("utf-8"), hashlib.sha256
    )
    return hmac_sha256.hexdigest()


def Log(category, message):
    os.makedirs(os.path.join(ROOT_DIR, "data/persist/logs"), exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    t = datetime.now().strftime("%H:%M:%S")
    with open(os.path.join(ROOT_DIR, "data/persist/logs/" + date + ".txt"), "a") as f:
        log = f"{t} - [{category.upper()}] - {message} \n"
        f.write(log)


def DiscordWebhookMessage(message):
    newActivity = AdminActivity(time=int(_time.time()), message=message)
    db.session.add(newActivity)
    db.session.commit()

    if not os.path.exists("discordwebhookurl"):
        return
    else:
        with open("discordwebhookurl", "r") as f:
            url = f.read()
    try:
        webhook = discord_webhook.DiscordWebhook(url=url, content=message)
        webhook.execute()
    except Exception:
        Log("admin", "Failed to send webhook message: " + message)


def DecryptGameData(game):
    if game is None or game == b"" or game == b" " or game == "":
        return None
    if isinstance(game, str):
        input_str = game
    else:
        input_str = game.decode("utf-8")
    index = input_str.find("&data=")
    if index == -1:
        try:
            return json.loads(input_str)
        except Exception:
            return None
    encoded_data = input_str[index + 6:]
    array = base64.b64decode(encoded_data)
    try:
        with gzip.GzipFile(fileobj=BytesIO(array), mode="rb") as gz:
            decoded_data = gz.read().decode("utf-8")
    except Exception:
        Log("admin", "Failed to decrypt game data")
        return None

    decoded_data = (
        decoded_data.replace(",}", "}")
        .replace(",],", "],")
        .replace(",]", "]")
        .replace(",,", ",")
    )

    json_start = decoded_data.find("{")
    if json_start > 0:
        decoded_data = decoded_data[json_start:]

    json_end = decoded_data.rfind("}")
    if json_end >= 0 and json_end < len(decoded_data) - 1:
        decoded_data = decoded_data[:json_end + 1]

    try:
        return json.loads(decoded_data)
    except Exception as e:
        Log("admin", "Failed to parse game data JSON: " + str(e))
        return None


def EncryptGameData(game, username=""):
    json_str = json.dumps(game, separators=(",", ":"))
    compressed = gzip.compress(json_str.encode("utf-8"))
    encoded = base64.b64encode(compressed).decode("utf-8")
    if username:
        prefix = "username=" + username + "&data="
    else:
        prefix = "&data="
    return (prefix + encoded).encode("utf-8")


def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def GetNameFromSave(save):
    try:
        game = DecryptGameData(save)
    except Exception:
        return None
    if game is None:
        return None
    return game["MultiplayerPlayerName"]


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


def IsUserBanned(username, ip=None):
    db_user = Bans.query.filter_by(username=username).first()
    if db_user is not None:
        return True
    if ip is None:
        return False
    db_ip = Bans.query.filter_by(username=ip).first()
    if db_ip is not None:
        return True
    return False


def SystemBan(username):
    Log("admin", "SYSTEM BANNED " + username)
    if not IsUserBanned(username):
        newban = Bans(
            username=username, bantype="userid", author="SYSTEM", time=int(_time.time())
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


def Backup():
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    os.makedirs(os.path.join(ROOT_DIR, "backup/" + now), exist_ok=True)
    shutil.copy(os.path.join(ROOT_DIR, "instance/cardwarskingdom.db"), os.path.join(ROOT_DIR, f"backup/{now}/cardwarskingdom.db"))
    shutil.copytree(os.path.join(ROOT_DIR, "data/persist"), os.path.join(ROOT_DIR, f"backup/{now}/persist"))
    shutil.make_archive(os.path.join(ROOT_DIR, "backup/" + now), "zip", os.path.join(ROOT_DIR, "backup/" + now))
    shutil.rmtree(os.path.join(ROOT_DIR, "backup/" + now))
    Log("admin", "Backed up")
    return True


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
    with open(os.path.join(ROOT_DIR, "data/persist/Blueprints/db_PVPSeasons.json")) as f:
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
