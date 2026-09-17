import json, time
from urllib.parse import parse_qs
from flask import Blueprint, jsonify, make_response, request
from flask_login import current_user

from app import db
from app.models import Player, RedeemCode
from app.utils import (
    DecryptGameData, EncryptGameData, IPFromRequest, InvalidUsername,
    IsUserBanned, Log, PlayerLog, SystemBan, DiscordWebhookMessage,
    safe_int, GetRankForXP,
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
        admin_lvl = safe_int(client_game.get("AdminLeaderLevel", 0)) if client_game else 0
        saved_lvl = safe_int(client_game.get("PlayersLastSavedLevel", 0)) if client_game else 0
        xp_lvl = GetRankForXP(safe_int(client_game.get("RankXP", 0))) if client_game else 0
        c_level = safe_int(clientData.get("leader_level", 0))
        db_user.leader_level = max(db_user.leader_level or 0, admin_lvl, saved_lvl, xp_lvl, c_level)
    except Exception:
        db_user.leader_level = safe_int(clientData.get("leader_level", 0), db_user.leader_level or 0)

    db_user.allyboxspace = safe_int(clientData.get("allyboxspace", db_user.allyboxspace or 0))
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
    saved_lvl = safe_int(client_game.get("PlayersLastSavedLevel", 0)) if client_game else 0
    xp_lvl = GetRankForXP(safe_int(client_game.get("RankXP", 0))) if client_game else 0
    authorized_rank = max(db_user.leader_level or 0, admin_lvl, saved_lvl, xp_lvl)
    client_leader_level = safe_int(clientData.get("leader_level", 0))

    # Anti-cheat check: only ban if client reports a level far exceeding any authorized level
    if (db_user.leader_level is None or db_user.leader_level == 0) and authorized_rank <= 1 and client_leader_level > 5:
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
    db_user.allyboxspace = safe_int(clientData.get("allyboxspace", db_user.allyboxspace or 0))
    db.session.commit()

    PlayerLog(
        IPFromRequest(request),
        clientData["player_id"],
        f"Set Deck Rank to {clientData['deck_rank']}\nSet Landscapes to {clientData['landscapes']}\nSet Helper Creature to {clientData['helper_creature']}\nSet Leader to {clientData['leader']}\nSet Leader Level to {clientData['leader_level']}\nSet Allyboxspace to {clientData['allyboxspace']}",
    )

    return jsonify({"success": True})


@multiplayer_bp.route("/multiplayer/redeemcodeDW/", methods=["POST"])
def RedeemCodeAPI():
    clientData = parse_qs(request.get_data().decode("utf-8"))
    clientData = {k: v[0] if len(v) == 1 else v for k, v in clientData.items()}

    code = clientData.get("code", "").strip()
    player_id = clientData.get("player_id", "")

    db_user = Player.query.filter_by(username=player_id).first()
    if db_user is None:
        return make_response("No player found!", 404)

    if IsUserBanned(player_id, IPFromRequest(request)):
        return make_response("User is banned!", 400)

    if not code:
        return jsonify({"success": False, "message": "No code provided"})

    game = DecryptGameData(db_user.game)
    if game is None:
        return jsonify({"success": False, "message": "No game data"})

    code_upper = code.upper()
    db_code = RedeemCode.query.filter_by(code=code_upper, enabled=True).first()
    if db_code is None:
        return jsonify({"success": False, "message": "Invalid code"})

    reward_type = db_code.reward_type
    reward_amount = db_code.reward_amount

    if reward_type in ("HardCurrency", "PaidHardCurrency"):
        game["HardCurrency"] = game.get("HardCurrency", 0) + reward_amount
        game["PaidHardCurrency"] = game.get("PaidHardCurrency", 0) + reward_amount
    elif reward_type == "FreeHardCurrency":
        game["FreeHardCurrency"] = game.get("FreeHardCurrency", 0) + reward_amount
        game["HardCurrency"] = game.get("HardCurrency", 0) + reward_amount
    elif reward_type == "SoftCurrency":
        game["SoftCurrency"] = game.get("SoftCurrency", 0) + reward_amount
    elif reward_type == "PvpCurrency":
        game["PvpCurrency"] = game.get("PvpCurrency", 0) + reward_amount
    elif reward_type == "EvolutionShards":
        game["EvolutionShards"] = game.get("EvolutionShards", 0) + reward_amount

    db_user.game = EncryptGameData(game, player_id)
    db.session.commit()

    PlayerLog(IPFromRequest(request), player_id, f"Redeemed code: {code_upper} - {reward_type} +{reward_amount}")

    return jsonify({
        "success": True,
        "message": f"Redeemed {code_upper} for {reward_amount} {reward_type}",
    })
