import json, os, hashlib, hmac, time
from datetime import datetime, timezone
from urllib.parse import parse_qs
from flask import Blueprint, abort, jsonify, make_response, redirect, render_template, request, send_from_directory
from flask_login import current_user

from app import maintenance, app, db
from app.models import Player, UpsightLogs
from app.utils import (
    DecryptGameData, EncryptGameData, DiscordWebhookMessage, IPFromRequest,
    InvalidUsername, IsUserBanned, Log, PlayerLog, UpdateLastOnline,
    GetAllyInfo, GetPlayerWins, SystemBan, get_hash_string, safe_int, GetRankForXP,
    GetPvpBanlist, ReadPersistText, GetLiveStatus, StripLegacyAdminMails,
    PruneDeliveredNewsMail,
)
game_bp = Blueprint('game_bp', __name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@game_bp.route("/static/version.txt")
def PersistVersion():
    pc_version = ReadPersistText("version.txt", "0.0.0").strip()
    android_version = ReadPersistText("android_version.txt", "0.0.0").strip()

    data = {
        "maintenance_mode": "yes" if maintenance else "no",
        "message": "Card Wars Kingdom is currently undergoing maintenance.\n\nPlease try again later.",
        "icon": "",
        "clickable": "yes",
        "android_version": android_version,
        "version": pc_version,
        "android_url": "https://github.com/shishkabob27/CardWarsKingdom/releases",
        "pc_url": "https://github.com/shishkabob27/CardWarsKingdom/releases",
    }
    return json.dumps(data)


@game_bp.route("/")
def Index():
    return "200 App server running"


@game_bp.route("/persist/static/manifest.json")
def Manifest():
    with open(os.path.join(ROOT_DIR, "data/persist/manifest.json"), "r") as f:
        return f.read()


# only works in v1.18.0
@game_bp.route("/persist/static/blueprints", methods=["GET"])
def Blueprints():
    data = []
    blueprints_dir = os.path.join(ROOT_DIR, "data/persist/Blueprints")
    for root, dirs, files in os.walk(blueprints_dir):
        for file in files:
            data.append(
                {
                    "name": file.replace(".json", ""),
                    "data": open(os.path.join(root, file), "r").read(),
                }
            )
    return jsonify(data)


@game_bp.route("/persist/static/Blueprints/<filename>")
def BlueprintFile(filename):
    return send_from_directory(
        directory=os.path.join(ROOT_DIR, "data/persist/Blueprints"),
        path=filename,
    )


@game_bp.route("/persist/static/live", methods=["GET"])
@game_bp.route("/persist/static/live/", methods=["GET"])
def PersistLive():
    return jsonify(GetLiveStatus())


@game_bp.route("/persist/static/monthly_store", methods=["GET"])
def MonthlyStore():
    return jsonify({
        "StoreItems": [],
        "FeaturedItems": [],
        "ResetTime": 0,
    })


@game_bp.route("/persist/static/pvp_banlist", methods=["GET", "POST"])
@game_bp.route("/persist/static/pvp_banlist/", methods=["GET", "POST"])
def PvpBanlist():
    data = GetPvpBanlist()
    data["server_time"] = datetime.now(timezone.utc).isoformat()
    return jsonify(data)




@game_bp.route("/persist/messages_received_ids")
def PersistMessagesReceivedIDs():
    filepath = os.path.join(ROOT_DIR, "data/persist/messages_received_ids.json")
    if not os.path.exists(filepath):
        return make_response("[]", 200)
    return send_from_directory(
        directory=os.path.dirname(filepath),
        path=os.path.basename(filepath),
        as_attachment=True,
        download_name="messages_received_ids.json",
    )


@game_bp.route("/persist/messages_get/<string:message>")
def PersistMessagesGet(message):
    filepath = os.path.join(ROOT_DIR, f"data/persist/messages/{message}.json")
    if not os.path.exists(filepath):
        return make_response("Message not found!", 404)
    return send_from_directory(
        directory=os.path.dirname(filepath),
        path=os.path.basename(filepath),
        as_attachment=True,
        download_name=f"{message}.json",
    )


@game_bp.route("/time/")
def Time():
    data = {
        "data": {
            "server_time": f"{datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')}",
        }
    }
    return jsonify(data)


@game_bp.route("/account/preAuth/")
def AccountPreAuth():
    data = {"data": {"nonce": os.urandom(32).hex()}}
    return jsonify(data)


@game_bp.route("/account/gcAuth/", methods=["POST"])
def AccountGCAuth():
    clientData = parse_qs(request.get_data().decode("utf-8"))
    clientData = {k: v[0] if len(v) == 1 else v for k, v in clientData.items()}

    if InvalidUsername(clientData["player_id"]):
        return make_response("Invalid Username!", 400)

    if IsUserBanned(clientData["player_id"], IPFromRequest(request)):
        return make_response("User is banned!", 400)

    # Create user if it doesn't exist
    db_user = Player.query.filter_by(username=clientData["player_id"]).first()

    isplayernew = False

    if db_user is None:
        db_user = Player(username=clientData["player_id"])
        db.session.add(db_user)
        db.session.commit()
        isplayernew = True
        PlayerLog(
            ip=IPFromRequest(request),
            player=clientData["player_id"],
            message="Created new player",
        )

    data = {"data": {"user_id": clientData["player_id"], "is_new": isplayernew}}
    return data


@game_bp.route("/persist/getcc/")
def GetCountryCode():
    data = {
        "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
        "country_code": "US",
    }
    return jsonify(data)


@game_bp.route("/persist/user_action2/", methods=["POST"])
def UserAction2():
    clientData = parse_qs(request.get_data().decode("utf-8"))
    clientData = {k: v[0] if len(v) == 1 else v for k, v in clientData.items()}

    if IsUserBanned(clientData["player_id"], IPFromRequest(request)):
        return make_response("User is banned!", 400)

    UpdateLastOnline(clientData["player_id"])

    # Check if an event was sent
    if "evt" in clientData:
        db_user = Player.query.filter_by(username=clientData["player_id"]).first()
        if db_user is None:
            return make_response("No player found!", 404)

        FreeHardCurrency = int(clientData["fr"])
        df = int(clientData["df"])

        finalamount = FreeHardCurrency + df

        PlayerLog(
            IPFromRequest(request),
            clientData["player_id"],
            f"User Action: {clientData['evt']}\nFree Hard Currency: {FreeHardCurrency}\nDF: {df}\nFinal Amount: {finalamount}",
        )

        key = "5424498w34tiowhtgoae0tu4iksdf4_4" + clientData["player_id"] + "650"
        handle = get_hash_string(clientData["player_id"], key)

        data = {
            "success": True,
            "data": '{"fields": {"level2": '
            + str(finalamount)
            + ', "handle": "'
            + handle
            + '"}}',
        }
    else:
        data = {
            "success": True,
        }

    return jsonify(data)


@game_bp.route("/persist/game", methods=["GET", "PUT"])
@game_bp.route("/persist/<string:player_id>/game", methods=["GET", "PUT"])
def PersistGame(player_id=None):

    if request.headers.get("Player-Id") is None:
        DiscordWebhookMessage(
            "User attempted to access game without Player-Id header. IP: "
            + IPFromRequest(request)
        )
        abort(404)
    username = request.headers.get("Player-Id")

    # verify headers
    if request.headers.get("Age") is None:
        DiscordWebhookMessage(
            username
            + " attempted to access game without Age header. IP: "
            + IPFromRequest(request)
        )
        abort(404)
    if request.headers.get("User-Agent") != "Innertube Explorer v0.1":
        DiscordWebhookMessage(
            username
            + " attempted to access game without User-Agent header. IP: "
            + IPFromRequest(request)
        )
        abort(404)
    if request.headers.get("Platform") is None:
        DiscordWebhookMessage(
            username
            + " attempted to access game without Platform header. IP: "
            + IPFromRequest(request)
        )
        abort(404)
    if request.headers.get("Version") is None:
        DiscordWebhookMessage(
            username
            + " attempted to access game without Version header. IP: "
            + IPFromRequest(request)
        )
        abort(404)
    if request.method == "PUT":
        if request.headers.get("X-Nick-Description") is None:
            DiscordWebhookMessage(
                username
                + " attempted to access game without X-Nick-Description header. IP: "
                + IPFromRequest(request)
            )
            abort(404)

    if InvalidUsername(username):
        return make_response("Invalid Username!", 400)
    if IsUserBanned(username, IPFromRequest(request)):
        return make_response("No game found!", 404)

    # Device name check
    if request.method == "PUT":
        DeviceNameUser = Player.query.filter_by(username=username).first()
        devicename = request.headers["X-Nick-Description"]

        # check if player's devicename is empty, if so, set it to X-Nick-Description
        if DeviceNameUser.devicename is None or DeviceNameUser.devicename == b"" or DeviceNameUser.devicename == "":
            DeviceNameUser.devicename = devicename
            db.session.commit()
        elif DeviceNameUser.devicename != devicename:
            Log("persist", username + " device name mismatch: expected '" + str(DeviceNameUser.devicename) + "' got '" + devicename + "'")

    UpdateLastOnline(username)

    # check if user is PVP banned
    pvp_ban_db_user = Player.query.filter_by(username=username).first()
    if pvp_ban_db_user is not None:
        try:
            game = DecryptGameData(pvp_ban_db_user.game)
            if game is not None:
                if int(game.get("Zxcvbnm", 0)) == 1:
                    Log("persist", username + " is PVP banned")
        except Exception as e:
            Log("persist", "Error while checking if user is PVP banned: " + str(e))

    if request.method == "GET":
        db_user = Player.query.filter_by(username=username).first()
        if db_user is None:
            return make_response("No game found!", 404)
        if db_user.game is None:
            return make_response("No game found!", 404)
        if db_user.game == b"" or db_user.game == b" ":
            return make_response("No game found!", 404)
        return db_user.game

    if request.method == "PUT":
        data = request.data

        # check if data is encrypted
        if not data.startswith(b"username=") or data.startswith(b"{"):
            DiscordWebhookMessage(
                username
                + " attempted to put game data without encryption. IP: "
                + IPFromRequest(request)
                + ". Data: "
                + data.decode("utf-8")[:50]
            )

        db_user = Player.query.filter_by(username=username).first()
        if db_user is None:
            return make_response("No game found!", 404)

        try:
            client_game = DecryptGameData(data)
            server_game = DecryptGameData(db_user.game) if db_user.game else None

            if client_game:
                if server_game:
                    # 1. Preserve admin overrides
                    admin_leader = safe_int(server_game.get("AdminLeaderLevel", 0))
                    admin_player = safe_int(server_game.get("AdminPlayerLevel", 0))
                    if admin_leader > 0:
                        client_game["AdminLeaderLevel"] = admin_leader
                    if admin_player > 0:
                        client_game["AdminPlayerLevel"] = admin_player

                    # 2. Prevent downgrade of RankXP and PlayersLastSavedLevel
                    server_xp = safe_int(server_game.get("RankXP", 0))
                    client_xp = safe_int(client_game.get("RankXP", 0))
                    if server_xp > client_xp:
                        client_game["RankXP"] = server_xp

                    server_lvl = safe_int(server_game.get("PlayersLastSavedLevel", 0))
                    client_lvl = safe_int(client_game.get("PlayersLastSavedLevel", 0))
                    if server_lvl > client_lvl:
                        client_game["PlayersLastSavedLevel"] = server_lvl

                    # 3. Merge CardCollection, Inventory, Leaders
                    client_cards = {c.get("ID") for c in client_game.get("CardCollection", [])}
                    for card in server_game.get("CardCollection", []):
                        if card.get("ID") not in client_cards:
                            client_game.setdefault("CardCollection", []).append(card)

                    client_creatures = {i.get("UniqueID") for i in client_game.get("Inventory", []) if i.get("_T") == "CR"}
                    for item in server_game.get("Inventory", []):
                        if item.get("_T") == "CR" and item.get("UniqueID") not in client_creatures:
                            client_game.setdefault("Inventory", []).append(item)

                    client_ca_ids = {i.get("ID") for i in client_game.get("Inventory", []) if i.get("_T") == "CA"}
                    next_uid = max([i.get("UniqueID", 0) for i in client_game.get("Inventory", [])], default=0) + 1
                    for item in server_game.get("Inventory", []):
                        if item.get("_T") == "CA" and item.get("ID") not in client_ca_ids:
                            new_item = dict(item)
                            new_item["UniqueID"] = next_uid
                            next_uid += 1
                            client_game.setdefault("Inventory", []).append(new_item)

                    client_leaders = {l.get("ID") for l in client_game.get("Leaders", [])}
                    for leader in server_game.get("Leaders", []):
                        if leader.get("ID") not in client_leaders:
                            client_game.setdefault("Leaders", []).append(leader)

                    # 4. Clean up old direct-to-save gift mails and drop the
                    # db_NewsMail blueprint entries once they have been
                    # delivered to this save (stops re-claiming after restart).
                    StripLegacyAdminMails(client_game)
                    PruneDeliveredNewsMail(client_game)

                data = EncryptGameData(client_game, username)

                # Update db_user with effective rank and player level
                effective_rank = max(
                    db_user.leader_level or 0,
                    safe_int(client_game.get("AdminLeaderLevel", 0)),
                    safe_int(client_game.get("PlayersLastSavedLevel", 0)),
                    GetRankForXP(safe_int(client_game.get("RankXP", 0))),
                )
                if effective_rank > 0:
                    db_user.leader_level = effective_rank

                if "AdminPlayerLevel" in client_game:
                    db_user.level = max(db_user.level or 0, safe_int(client_game["AdminPlayerLevel"], 0))
        except Exception as e:
            Log("persist", f"Error merging PUT game data for {username}: {e}")

        db_user.game = data
        db.session.commit()
        return make_response("OK", 200)
