import json, os, hashlib, hmac, time
from datetime import datetime, timezone
from urllib.parse import parse_qs
from flask import Blueprint, abort, jsonify, make_response, redirect, render_template, request, send_from_directory
from flask_login import current_user

from app import maintenance, app, db
from app.models import Player, RouletteState, UpsightLogs, AdminGift
from app.services.trade_market import ApplyTradeDeltasToGame
from app.utils import (
    DecryptGameData, EncryptGameData, DiscordWebhookMessage, IPFromRequest,
    InvalidUsername, IsUserBanned, Log, PlayerLog, UpdateLastOnline,
    GetAllyInfo, GetPlayerWins, SystemBan, get_hash_string, safe_int, GetRankForXP,
    GetPvpBanlist, ReadPersistText, GetLiveStatus, StripLegacyAdminMails,
    PruneDeliveredNewsMail, RollRoulettePrize, ApplyRoulettePrize, PurchasePrice,
    BuildPvpBanlistResponse, ReadMiscParam, SaveReport, REPORT_MAX_BYTES,
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
    data = BuildPvpBanlistResponse()
    response = make_response(json.dumps(data))
    response.headers["Content-Type"] = "application/json"
    return response


@game_bp.route("/mail/gifts", methods=["POST"])
def MailGifts():
    """Post Office (6.1.2+): list this player's unclaimed admin gifts.

    Same proof as a save write: the Player-Id header. The app claims each gift
    once through user_action2 evt "admin gift".
    """
    username = request.headers.get("Player-Id")
    if not username or InvalidUsername(username):
        return jsonify({"ok": False, "error": "Invalid Username!"}), 400
    if IsUserBanned(username, IPFromRequest(request)):
        return jsonify({"ok": False, "error": "User is banned!"}), 403
    player = Player.query.filter_by(username=username).first()
    if player is None:
        return jsonify({"ok": False, "error": "Invalid Username!"}), 400

    rows = (
        AdminGift.query.filter_by(username=username, claimed_at=None)
        .order_by(AdminGift.id)
        .limit(50)
        .all()
    )
    return jsonify(
        {
            "ok": True,
            "gifts": [
                {
                    "id": g.id,
                    "title": g.title or "",
                    "message": g.message or "",
                    "gems": g.gems or 0,
                    "coins": g.coins or 0,
                    "pvp": g.pvp or 0,
                    "shards": g.shards or 0,
                    "items": g.items or "",
                }
                for g in rows
            ],
        }
    )


@game_bp.route("/persist/static/report", methods=["POST"])
def LiveReport():
    """Client crash / feedback reports. Saves the body and always answers 204."""
    length = request.content_length or 0
    if 0 < length <= REPORT_MAX_BYTES:
        SaveReport(request.get_data(cache=False, as_text=True), IPFromRequest(request))
    return ("", 204)




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

    pid = clientData.get("player_id", "")
    if IsUserBanned(pid, IPFromRequest(request)):
        return make_response("User is banned!", 400)

    UpdateLastOnline(pid)

    # Check if an event was sent
    if "evt" in clientData:
        db_user = Player.query.filter_by(username=pid).first()
        if db_user is None:
            return make_response("No player found!", 404)

        evt = (clientData.get("evt") or "").strip()
        key = "5424498w34tiowhtgoae0tu4iksdf4_4" + pid + "650"
        handle = get_hash_string(pid, key)

        # Daily Gift roulette: the SERVER rolls the winning slice and reports it
        # as fields.spin (production protocol), so the client wheel works.
        if evt.lower() == "roulette spin":
            return _RouletteSpin(db_user, pid, handle)

        # Spend wishbones to buy a spin token that bypasses the 24h cooldown.
        if evt.lower() == "roulette reset":
            return _RouletteReset(db_user, pid, handle)

        # Store purchase: the app names WHAT it buys; the server charges its own
        # price (claims.purchase protocol) and answers reason/cb/cc.
        if evt.lower() == "purchase":
            return _HandlePurchase(db_user, pid, clientData, handle)

        # Currency packs bought with gems: buy coins / evolution shards / craft
        # coins. The app sends df = -gems to spend; the server prices the packs.
        if evt.lower() in CURRENCY_PURCHASES:
            return _HandleCurrencyPurchase(db_user, pid, clientData, handle, evt.lower())

        # Post Office: claim one admin gift. The server grants the currencies
        # (save-based wallet); the app adds the gift's items and reports them.
        if evt.lower() == "admin gift":
            return _ClaimAdminGift(db_user, pid, clientData, handle)

        # The client sends its current balances (pd/fr/cu) plus the deltas it is
        # applying (dp/df/dc) and expects the authoritative results back in
        # level1/level2/level3. Return all three so the client never keeps a
        # stale balance after a mail claim.
        paid = safe_int(clientData.get("pd", 0))
        free = safe_int(clientData.get("fr", 0))
        custom = safe_int(clientData.get("cu", 0))
        dp = safe_int(clientData.get("dp", 0))
        df = safe_int(clientData.get("df", 0))
        dc = safe_int(clientData.get("dc", 0))

        final_paid = paid + dp
        final_free = free + df
        final_custom = custom + dc
        finalamount = final_free

        PlayerLog(
            IPFromRequest(request),
            pid,
            f"User Action: {evt}\nFree Hard Currency: {free}\nDF: {df}\nFinal Amount: {finalamount}",
        )

        data = {
            "success": True,
            "data": json.dumps(
                {
                    "fields": {
                        "level1": final_paid,
                        "level2": final_free,
                        "level3": final_custom,
                        "handle": handle,
                    }
                }
            ),
        }
    else:
        data = {
            "success": True,
        }

    return jsonify(data)


ROULETTE_COOLDOWN = 24 * 60 * 60   # one free spin per day
ROULETTE_RESET_COST = 1250         # wishbones to buy an extra spin (production)


def _RouletteState(pid, create=True):
    state = RouletteState.query.filter_by(username=pid).first()
    if state is None and create:
        state = RouletteState(username=pid, spin_at=0, spin_tokens=0, updated_at=int(time.time()))
        db.session.add(state)
    return state


def _RouletteSpin(db_user, pid, handle):
    """Roll the Daily Gift roulette, credit the prize and answer like production.

    Enforces the daily cooldown; a paid reset (`roulette reset`) adds a token that
    lets one extra spin through. The winning slice index is `fields.spin`; granted
    amounts are gs/gf/gv/ge/gc and the balances level1..level7.
    """
    now = int(time.time())
    state = _RouletteState(pid, create=True)

    if now - int(state.spin_at or 0) >= ROULETTE_COOLDOWN:
        state.spin_at = now
    elif int(state.spin_tokens or 0) > 0:
        state.spin_tokens = int(state.spin_tokens) - 1
    else:
        db.session.commit()
        game = DecryptGameData(db_user.game) if db_user.game else {}
        if not isinstance(game, dict):
            game = {}
        fields = {**_BalanceFields(game, handle), "reason": "ROULETTE_COOLDOWN", "spin": None, "seq": now}
        return jsonify({"success": True, "data": json.dumps({"fields": fields})})

    game = DecryptGameData(db_user.game) if db_user.game else {}
    if not isinstance(game, dict):
        game = {}

    prize = RollRoulettePrize()
    granted = ApplyRoulettePrize(game, prize)
    state.updated_at = now

    if db_user.game:
        db_user.game = EncryptGameData(game, pid)
    db.session.commit()

    fields = {
        **_BalanceFields(game, handle),
        "gs": granted["gs"],
        "gf": granted["gf"],
        "gv": granted["gv"],
        "ge": granted["ge"],
        "gc": granted["gc"],
        "reason": "OK" if prize else "NO_ROULETTE",
        "seq": now,
        "spin": prize["index"] if prize else None,
    }
    Log("admin", "Roulette spin by " + pid + ": " + json.dumps(prize))
    return jsonify({"success": True, "data": json.dumps({"fields": fields})})


def _RouletteReset(db_user, pid, handle):
    """Buy a spin token with wishbones so the next spin bypasses the cooldown.

    Charges ROULETTE_RESET_COST PvP currency (the client debits its own from the
    returned balance) and answers reason OK / NOT_ENOUGH_PVP like production.
    """
    now = int(time.time())
    game = DecryptGameData(db_user.game) if db_user.game else {}
    if not isinstance(game, dict):
        game = {}

    def reply(reason):
        fields = {**_BalanceFields(game, handle), "reason": reason, "seq": now}
        return jsonify({"success": True, "data": json.dumps({"fields": fields})})

    pvp = safe_int(game.get("PvpCurrency", 0))
    if pvp < ROULETTE_RESET_COST:
        return reply("NOT_ENOUGH_PVP")

    game["PvpCurrency"] = pvp - ROULETTE_RESET_COST
    state = _RouletteState(pid, create=True)
    state.spin_tokens = int(state.spin_tokens or 0) + 1
    state.updated_at = now
    db_user.game = EncryptGameData(game, pid)
    db.session.commit()
    PlayerLog(IPFromRequest(request), pid, f"Roulette reset: charged {ROULETTE_RESET_COST} wishbones (token {state.spin_tokens})")
    return reply("OK")


def _BalanceFields(game, handle):
    """The level1..level7 balance block the client assigns onto its own save."""
    return {
        "level1": safe_int(game.get("PaidHardCurrency", 0)),
        "level2": safe_int(game.get("FreeHardCurrency", 0)),
        "level4": safe_int(game.get("SoftCurrency", 0)),
        "level5": safe_int(game.get("PvpCurrency", 0)),
        "level6": safe_int(game.get("EvolutionShards", 0)),
        "level7": safe_int(game.get("CraftCurrency", 0)),
        "handle": handle,
    }


def _ClaimAdminGift(db_user, pid, clientData, handle):
    """Claim one Post Office admin gift (production 6.1.2+ "admin gift").

    Currencies are granted here (the save is the wallet); the gift's ``items``
    string is handed to the app, which adds those items to its save. A gift is
    claimed at most once.
    """
    ctx = str(clientData.get("ctx", "") or "").strip()
    gift = None
    if ctx.isdigit():
        gift = AdminGift.query.filter_by(
            id=int(ctx), username=pid, claimed_at=None
        ).first()

    game = DecryptGameData(db_user.game) if db_user.game else None
    if not isinstance(game, dict):
        game = {}

    if gift is None:
        fields = {
            **_BalanceFields(game, handle),
            "reason": "UNKNOWN_GIFT",
            "gs": 0,
            "gf": 0,
            "gv": 0,
            "ge": 0,
            "gc": 0,
        }
        return jsonify({"success": True, "data": json.dumps({"fields": fields})})

    gems = max(0, safe_int(gift.gems, 0))
    coins = max(0, safe_int(gift.coins, 0))
    pvp = max(0, safe_int(gift.pvp, 0))
    shards = max(0, safe_int(gift.shards, 0))

    if gems:
        game["FreeHardCurrency"] = safe_int(game.get("FreeHardCurrency", 0)) + gems
        game["HardCurrency"] = safe_int(game.get("HardCurrency", 0)) + gems
    if coins:
        game["SoftCurrency"] = safe_int(game.get("SoftCurrency", 0)) + coins
    if pvp:
        game["PvpCurrency"] = safe_int(game.get("PvpCurrency", 0)) + pvp
    if shards:
        game["EvolutionShards"] = safe_int(game.get("EvolutionShards", 0)) + shards

    db_user.game = EncryptGameData(game, pid)
    gift.claimed_at = int(time.time())
    db.session.commit()

    PlayerLog(
        IPFromRequest(request),
        pid,
        f"[post] gift {gift.id} claimed: {gems} gems, {coins} coins, "
        f"{pvp} wishbones, {shards} shards, items={gift.items}",
    )

    fields = {
        **_BalanceFields(game, handle),
        "reason": "OK",
        "gs": coins,
        "gf": gems,
        "gv": pvp,
        "ge": shards,
        "gc": 0,
        "seq": int(time.time()),
    }
    return jsonify({"success": True, "data": json.dumps({"fields": fields})})


def _OwnsLeader(game, key, is_skin):
    for leader in game.get("Leaders") or []:
        if not isinstance(leader, dict):
            continue
        owned = leader.get("OwnedSkins")
        if isinstance(owned, list) and key in owned:
            return True
        if leader.get("Skin") == key:
            return True
        if not is_skin and leader.get("ID") == key:
            return True
    return False


def _HandlePurchase(db_user, pid, clientData, handle):
    """Server-authoritative store purchase (production claims.purchase protocol).

    The app names WHAT it buys (`ctx = kind:id[:count]`); the server charges its
    own price and answers `reason`/`cb` (bucket) / `cc` (charged) plus balances.
    """
    ctx = str(clientData.get("ctx", ""))
    kind, _, rest = ctx.partition(":")
    key, _, count = rest.partition(":")
    count = max(1, min(1000, safe_int(count, 1) or 1)) if kind == "gacha" else 1

    game = DecryptGameData(db_user.game) if db_user.game else {}
    if not isinstance(game, dict):
        game = {}

    def reply(fields):
        return jsonify({"success": True, "data": json.dumps({"fields": fields})})

    price = PurchasePrice(kind, key)
    if price is None:
        return reply({**_BalanceFields(game, handle), "reason": "UNKNOWN_ITEM", "cb": "", "cc": 0})

    if kind in ("leader", "skin") and _OwnsLeader(game, key, kind == "skin"):
        return reply({**_BalanceFields(game, handle), "reason": "OK", "cb": price["bucket"], "cc": 0})

    bucket = price["bucket"]
    total = int(price["amount"]) * count

    free = safe_int(game.get("FreeHardCurrency", 0))
    paid = safe_int(game.get("PaidHardCurrency", 0))
    coins = safe_int(game.get("SoftCurrency", 0))
    pvp = safe_int(game.get("PvpCurrency", 0))
    have = {"gems": free + paid, "coins": coins, "pvp": pvp}.get(bucket, 0)
    if have < total:
        return reply({**_BalanceFields(game, handle), "reason": "NOT_ENOUGH", "cb": bucket, "cc": 0})

    if bucket == "gems":
        take_free = min(free, total)
        take_paid = total - take_free
        game["FreeHardCurrency"] = free - take_free
        game["PaidHardCurrency"] = paid - take_paid
        game["HardCurrency"] = game["FreeHardCurrency"] + game["PaidHardCurrency"]
    elif bucket == "coins":
        game["SoftCurrency"] = coins - total
    elif bucket == "pvp":
        game["PvpCurrency"] = pvp - total

    # Store creatures are granted server-side (the client cannot add them itself).
    creature_id = price.get("creature")
    if kind == "creature" and creature_id:
        inv = game.get("Inventory")
        if not isinstance(inv, list):
            inv = []
            game["Inventory"] = inv
        nxt = (
            max(
                [safe_int(i.get("UniqueID"), 0) for i in inv if isinstance(i, dict)],
                default=0,
            )
            + 1
        )
        inv.append(
            {
                "_T": "CR",
                "ID": creature_id,
                "UniqueID": nxt,
                "Xp": 0,
                "StarRating": 1,
                "Favorite": 0,
                "Passive": 1,
                "PassiveFeeds": 0,
            }
        )

    db_user.game = EncryptGameData(game, pid)
    db.session.commit()
    PlayerLog(IPFromRequest(request), pid, f"Purchase {ctx or kind} charged {total} {bucket}")

    return reply(
        {
            **_BalanceFields(game, handle),
            "reason": "OK",
            "cb": bucket,
            "cc": total,
            "seq": int(time.time()),
        }
    )


# Currency packs bought with gems. event -> (cost param, amount param, product,
# granted key, default cost, default amount). Production: claims.process.
CURRENCY_PURCHASES = {
    "buy coins": ("BuySoftCurrencyCost", "BuySoftCurrencyAmount", "SoftCurrency", "gs", 100, 10000),
    "evolution shards purchase": ("BuyEvolutionShardsCost", "BuyEvolutionShardsAmount", "EvolutionShards", "ge", 6000, 1),
    "craft coin purchase": ("BuyCraftCurrencyCost", "BuyCraftCurrencyAmount", "CraftCurrency", "gc", 6500, 1),
}


def _HandleCurrencyPurchase(db_user, pid, clientData, handle, evt):
    """Gem-priced currency packs (buy coins / evolution shards / craft coins).

    The app sends df = -<gems to spend>; the server prices the packs from
    MiscParams and grants the product, answering reason OK / NOT_ENOUGH_GEMS the
    same way the production claims.process does.
    """
    cost_param, amount_param, product, gkey, cost_default, amount_default = CURRENCY_PURCHASES[evt]
    cost_each = safe_int(ReadMiscParam(cost_param, cost_default), cost_default) or cost_default
    amount_each = safe_int(ReadMiscParam(amount_param, amount_default), amount_default) or amount_default

    df = safe_int(clientData.get("df", 0))
    gems_asked = max(0, -df)
    packs = gems_asked // cost_each if cost_each > 0 else 0

    game = DecryptGameData(db_user.game) if db_user.game else {}
    if not isinstance(game, dict):
        game = {}

    def reply(reason, granted=0):
        fields = {**_BalanceFields(game, handle), "reason": reason, "seq": int(time.time())}
        fields[gkey] = granted
        return jsonify({"success": True, "data": json.dumps({"fields": fields})})

    free = safe_int(game.get("FreeHardCurrency", 0))
    paid = safe_int(game.get("PaidHardCurrency", 0))
    if packs <= 0 or (free + paid) < packs * cost_each:
        return reply("NOT_ENOUGH_GEMS")

    total = packs * cost_each
    take_free = min(free, total)
    take_paid = total - take_free
    game["FreeHardCurrency"] = free - take_free
    game["PaidHardCurrency"] = paid - take_paid
    game["HardCurrency"] = game["FreeHardCurrency"] + game["PaidHardCurrency"]

    gained = packs * amount_each
    game[product] = safe_int(game.get(product, 0)) + gained

    db_user.game = EncryptGameData(game, pid)
    db.session.commit()
    PlayerLog(
        IPFromRequest(request),
        pid,
        f"{evt}: {packs} pack(s), spent {total} gems, granted {gained} {product}",
    )
    return reply("OK", gained)




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

                # Apply any pending trade changes so a stale upload cannot
                # resurrect sold creatures or drop bought ones.
                ApplyTradeDeltasToGame(username, client_game)

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
