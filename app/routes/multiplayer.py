import json
import time
from urllib.parse import parse_qs

from flask import Blueprint, jsonify, make_response, request
from flask_login import current_user

from app import db
from app.models import Player, RedeemCode
from app.utils import (
    ApplyRedeemReward,
    DecryptGameData,
    DiscordWebhookMessage,
    EncryptGameData,
    GetRankForXP,
    InvalidUsername,
    IPFromRequest,
    IsUserBanned,
    Log,
    ParseRedeemRewards,
    PlayerLog,
    SystemBan,
    safe_int,
)

multiplayer_bp = Blueprint("multiplayer_bp", __name__)


@multiplayer_bp.route("/multiplayer/new_player/", methods=["POST"])
def MultiplayerNewPlayer():
    clientData = parse_qs(request.get_data().decode("utf-8"))
    clientData = {k: v[0] if len(v) == 1 else v for k, v in clientData.items()}

    # Make sure username is valid
    if InvalidUsername(clientData["name"]):
        return make_response("Invalid username!", 400)

    db_user = Player.query.filter_by(username=clientData["player_id"]).first()
    if db_user is None:
        return make_response("No player found!", 404)

    db_user.multiplayer_name = clientData["name"]
    db_user.icon = clientData["icon"]
    db_user.deck_rank = clientData["deck_rank"]
    db_user.landscapes = clientData["landscapes"]
    db_user.helper_creature = clientData["helper_creature"]
    db_user.leader = clientData["leader"]

    try:
        client_game = DecryptGameData(db_user.game)
        admin_lvl = (
            safe_int(client_game.get("AdminLeaderLevel", 0)) if client_game else 0
        )
        saved_lvl = (
            safe_int(client_game.get("PlayersLastSavedLevel", 0)) if client_game else 0
        )
        xp_lvl = (
            GetRankForXP(safe_int(client_game.get("RankXP", 0))) if client_game else 0
        )
        c_level = safe_int(clientData.get("leader_level", 0))
        db_user.leader_level = max(
            db_user.leader_level or 0, admin_lvl, saved_lvl, xp_lvl, c_level
        )
    except Exception:
        db_user.leader_level = safe_int(
            clientData.get("leader_level", 0), db_user.leader_level or 0
        )

    db_user.allyboxspace = safe_int(
        clientData.get("allyboxspace", db_user.allyboxspace or 0)
    )
    db_user.level = max(safe_int(clientData.get("level", 0)), db_user.level or 0)
    db.session.commit()

    PlayerLog(
        IPFromRequest(request),
        clientData["player_id"],
        f"Set Multiplayer name to {clientData['name']}\nSet Deck Rank to {clientData['deck_rank']}\nSet Landscapes to {clientData['landscapes']}\nSet Helper Creature to {clientData['helper_creature']}\nSet Leader to {clientData['leader']}\nSet Leader Level to {clientData['leader_level']}\nSet Allyboxspace to {clientData['allyboxspace']}\nSet Level to {clientData['level']}",
    )

    return jsonify(
        {
            "success": True,
            "data": {
                "name": clientData["name"],
                "icon": clientData["icon"],
                "leader": clientData["leader"],
                "level": str(db_user.leader_level),
                "trophies": "0",  # Unused
            },
        }
    )


@multiplayer_bp.route("/multiplayer/update_deck_name/", methods=["POST"])
def MultiplayerUpdateDeckName():
    clientData = parse_qs(request.get_data().decode("utf-8"))
    clientData = {k: v[0] if len(v) == 1 else v for k, v in clientData.items()}

    if InvalidUsername(clientData["name"]):
        return make_response("Invalid username!", 400)

    db_user = Player.query.filter_by(username=clientData["player_id"]).first()
    if db_user is None:
        return make_response("No player found!", 404)

    db_user.deck_rank = clientData["deck_rank"]
    db_user.landscapes = clientData["landscapes"]
    db_user.helper_creature = clientData["helper_creature"]
    db_user.leader = clientData["leader"]

    client_game = None
    try:
        client_game = DecryptGameData(db_user.game)
    except Exception:
        pass

    admin_lvl = safe_int(client_game.get("AdminLeaderLevel", 0)) if client_game else 0
    saved_lvl = (
        safe_int(client_game.get("PlayersLastSavedLevel", 0)) if client_game else 0
    )
    xp_lvl = GetRankForXP(safe_int(client_game.get("RankXP", 0))) if client_game else 0
    authorized_rank = max(db_user.leader_level or 0, admin_lvl, saved_lvl, xp_lvl)
    client_leader_level = safe_int(clientData.get("leader_level", 0))

    # Anti-cheat check: only ban if client reports a level far exceeding any authorized level
    if (
        (db_user.leader_level is None or db_user.leader_level == 0)
        and authorized_rank <= 1
        and client_leader_level > 5
    ):
        DiscordWebhookMessage(
            f"{clientData['player_id']} attempted to set leader level to a {clientData['leader_level']} on a fresh account! IP: "
            + IPFromRequest(request)
        )
        SystemBan(clientData["player_id"])
    elif authorized_rank > 0 and client_leader_level > authorized_rank + 10:
        DiscordWebhookMessage(
            f"{clientData['player_id']} attempted to set leader level to {clientData['leader_level']} when authorized level was {authorized_rank}! IP: "
            + IPFromRequest(request)
        )
        SystemBan(clientData["player_id"])

    # Safely update leader level: never downgrade below authorized rank
    db_user.leader_level = max(authorized_rank, client_leader_level)
    db_user.allyboxspace = safe_int(
        clientData.get("allyboxspace", db_user.allyboxspace or 0)
    )
    db.session.commit()

    PlayerLog(
        IPFromRequest(request),
        clientData["player_id"],
        f"Set Deck Rank to {clientData['deck_rank']}\nSet Landscapes to {clientData['landscapes']}\nSet Helper Creature to {clientData['helper_creature']}\nSet Leader to {clientData['leader']}\nSet Leader Level to {clientData['leader_level']}\nSet Allyboxspace to {clientData['allyboxspace']}",
    )

    return jsonify({"success": True})


REDEEM_OK = "OK"
REDEEM_EMPTY = "EMPTY"
REDEEM_INVALID = "INVALID"
REDEEM_NOT_STARTED = "NOT_STARTED"
REDEEM_EXPIRED = "EXPIRED"
REDEEM_USED = "USED"
REDEEM_LIMIT = "LIMIT"
REDEEM_BUSY = "BUSY"

# Legacy error text the game client shows for a refused code (matches the
# production server's _REDEEM_LEGACY map).
_REDEEM_LEGACY = {
    REDEEM_INVALID: "invalid redeemcode",
    REDEEM_NOT_STARTED: "invalid redeemcode",
    REDEEM_EXPIRED: "invalid redeemcode",
    REDEEM_USED: "maximum reword count reached",
    REDEEM_LIMIT: "maximum reword count reached",
}

REDEEM_ITEMS_IN_APP = (6, 0, 49)  # from this version the app adds redeemed items itself

# Failed-attempt throttling (per player id and per IP), mirroring the
# production redeem.Attempts() guard.
_REDEEM_TRIES = {}
_REDEEM_WINDOW = 300
_REDEEM_MAX = 10


def _redeem_now():
    return int(time.time())


def _redeem_blocked(key, now):
    hits = [t for t in _REDEEM_TRIES.get(key, []) if now - t < _REDEEM_WINDOW]
    _REDEEM_TRIES[key] = hits
    return len(hits) >= _REDEEM_MAX


def _redeem_miss(key, now):
    hits = [t for t in _REDEEM_TRIES.get(key, []) if now - t < _REDEEM_WINDOW]
    hits.append(now)
    _REDEEM_TRIES[key] = hits


def _client_ver(value):
    try:
        return tuple(int(x) for x in str(value).split(".")[:3])
    except Exception:
        return (0,)


@multiplayer_bp.route("/multiplayer/redeemcodeDW/", methods=["POST"])
def RedeemCodeAPI():
    """Admin-made redeem codes. Response matches the production server exactly so
    the game client parses it: {"success", "reason", "data", "error", ...}."""
    form = parse_qs(request.get_data().decode("utf-8", "replace"))

    def _first(key):
        values = form.get(key)
        return values[0] if values else ""

    pid = str(request.headers.get("Player-Id") or "") or _first("player_id")
    code = (_first("redeemcode") or _first("code")).strip().upper()

    def answer(reason, **extra):
        body = {
            "success": reason == REDEEM_OK,
            "reason": reason,
            "data": "",
            "error": "" if reason == REDEEM_OK else _REDEEM_LEGACY.get(reason, "error"),
        }
        body.update(extra)
        return jsonify(body)

    if not code:
        return answer(REDEEM_EMPTY)

    db_user = Player.query.filter_by(username=pid).first() if pid else None
    if db_user is None:
        return answer("ERROR")

    if IsUserBanned(pid, IPFromRequest(request)):
        return make_response("User is banned!", 403)

    now = _redeem_now()
    ip_key = "ip:" + str(IPFromRequest(request))
    if _redeem_blocked(pid, now) or _redeem_blocked(ip_key, now):
        return answer(REDEEM_BUSY)

    db_code = RedeemCode.query.filter_by(code=code, enabled=True).first()
    if db_code is None:
        _redeem_miss(pid, now)
        _redeem_miss(ip_key, now)
        PlayerLog(IPFromRequest(request), pid, f"[redeem] {code} refused: {REDEEM_INVALID}")
        return answer(REDEEM_INVALID)

    game = DecryptGameData(db_user.game)
    if game is None:
        return answer("ERROR")

    used_codes = game.get("UsedRedeemCodes")
    if not isinstance(used_codes, list):
        used_codes = []
    if code in used_codes:
        return answer(REDEEM_USED)

    rewards = ParseRedeemRewards(db_code)

    # Validate every reward before touching the save so a partial redeem cannot
    # hand out only part of a code's contents.
    for reward in rewards:
        if reward["type"] in ("Creature", "ActionCard", "Card", "Leader", "Hero"):
            if not reward["item"]:
                return answer("ERROR")

    granted = {"gems": 0, "coins": 0, "creatures": [], "cards": [], "leaders": []}
    reward_descs = []
    for reward in rewards:
        rtype, amount, item = reward["type"], reward["amount"], reward["item"]
        if rtype in ("HardCurrency", "PaidHardCurrency", "FreeHardCurrency"):
            granted["gems"] += amount
        elif rtype == "SoftCurrency":
            granted["coins"] += amount
        elif rtype == "Creature":
            granted["creatures"].append(item)
        elif rtype in ("ActionCard", "Card"):
            granted["cards"].append(item)
        elif rtype in ("Leader", "Hero"):
            granted["leaders"].append(item)

        ok, info = ApplyRedeemReward(game, rtype, amount, item)
        if not ok:
            return answer("ERROR")
        reward_descs.append(info)

    used_codes.append(code)
    game["UsedRedeemCodes"] = used_codes
    db_user.game = EncryptGameData(game, pid)
    db.session.commit()

    PlayerLog(
        IPFromRequest(request),
        pid,
        f"Redeemed code: {code} - " + ", ".join(reward_descs),
    )
    Log("admin", "Redeem %s by %s: %s" % (code, pid, json.dumps(granted)))

    in_app = _client_ver(request.headers.get("version")) >= REDEEM_ITEMS_IN_APP
    fields = {
        "level1": safe_int(game.get("PaidHardCurrency", 0)),
        "level2": safe_int(game.get("FreeHardCurrency", 0)),
        "gs": granted["coins"],
        "gf": granted["gems"],
        "seq": now,
        "reason": "OK",
    }
    return answer(
        REDEEM_OK,
        rewards=granted,
        deliver="now" if in_app else "login",
        fields=fields,
    )

