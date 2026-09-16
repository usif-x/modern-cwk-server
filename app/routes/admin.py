import json, os, random, re, secrets, string, subprocess, time
from datetime import datetime, timezone
from flask import Blueprint, abort, jsonify, make_response, redirect, render_template, request
from flask_login import current_user, login_required, login_user, logout_user

from app import db, bcrypt, maintenance, badcharaters, app as flask_app
from app.models import Admin, AdminActivity, Bans, Logs, Player, RedeemCode, UpsightLogs
from app.utils import (
    DecryptGameData, EncryptGameData, DiscordWebhookMessage, GetNameFromSave,
    GetPlayerWins, IPFromRequest, InvalidUsername, IsUserBanned, Log,
    PlayerLog, safe_int, time_ago_string, isAdmin, Backup, UpdateLastOnline,
)

admin_bp = Blueprint('admin_bp', __name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@admin_bp.route("/admin", methods=["GET", "POST"])
def AdminPage():

    # create an admin account if one doesn't exist
    if not Admin.query.first():
        randompassword = "".join(
            random.choices(string.ascii_letters + string.digits, k=24)
        )
        newAdmin = Admin(
            username="admin",
            password=bcrypt.generate_password_hash(randompassword).decode("utf-8"),
            rank=0,
        )
        db.session.add(newAdmin)
        db.session.commit()
        Log("server", "Created admin account")
        print(f"Admin account created! Username: admin, Password: {randompassword}")

    if request.method == "GET":
        if current_user.is_authenticated:
            if not isAdmin(current_user):
                return abort(404)
            return redirect("/admin/home")
        else:
            return render_template("admin_login.html")
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        username = re.sub(r"[^a-zA-Z0-9]", "", username)
        db_user = Admin.query.filter_by(username=username).first()
        if db_user is None:
            return make_response("Invalid Username or Password!", 400)
        if not bcrypt.check_password_hash(db_user.password, password):
            return make_response("Invalid Password or Username!", 400)
        login_user(db_user, remember=True)
        return redirect("/admin")


@login_required
@admin_bp.route("/admin/home")
def AdminHome():
    if not isAdmin(current_user):
        return abort(404)

    adminActivity = AdminActivity.query.order_by(AdminActivity.time).all()
    # convert time
    for log in adminActivity:
        log.time = datetime.fromtimestamp(log.time, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

    # reverse list
    adminActivity.reverse()

    total_players = Player.query.filter(Player.game.isnot(None), Player.leader_level.isnot(None)).count()
    total_banned = Bans.query.filter_by(bantype="userid").count()
    total_banned_ips = Bans.query.filter_by(bantype="ip").count()
    cutoff = int(time.time()) - 86400
    active_24h = Player.query.filter(Player.last_online >= cutoff, Player.game.isnot(None), Player.leader_level.isnot(None)).count()

    return render_template(
        "admin_home.html",
        Activity=adminActivity,
        total_players=total_players,
        total_banned=total_banned,
        total_banned_ips=total_banned_ips,
        active_24h=active_24h,
    )


@login_required
@admin_bp.route("/admin/versions", methods=["GET", "POST"])
def AdminVersions():
    if not isAdmin(current_user):
        return abort(404)

    if request.method == "GET":

        return render_template(
            "admin_versions.html",
            pc_version=open(os.path.join(ROOT_DIR, "data/persist/version.txt"), "r").read(),
            android_version=open(os.path.join(ROOT_DIR, "data/persist/android_version.txt"), "r").read(),
        )
    elif request.method == "POST":
        form = request.form
        form = {k: v[0] if len(v) == 1 else v for k, v in form.items()}

        if "pc_version" not in form or form["pc_version"] == "":
            return make_response("Invalid PC version!", 400)
        if "android_version" not in form or form["android_version"] == "":
            return make_response("Invalid Android version!", 400)

        # update version.txt
        with open(os.path.join(ROOT_DIR, "data/persist/version.txt"), "w") as f:
            f.write(form["pc_version"])
        with open(os.path.join(ROOT_DIR, "data/persist/android_version.txt"), "w") as f:
            f.write(form["android_version"])

        return redirect("/admin/versions")


@login_required
@admin_bp.route("/admin/server")
def AdminServer():
    if not isAdmin(current_user):
        return abort(404)

    # create backup folder if it doesn't exist
    if not os.path.exists(os.path.join(ROOT_DIR, "backup")):
        os.makedirs(os.path.join(ROOT_DIR, "backup"))

    # get last backup in folder
    last_backup_time = 0
    last_backup_file = ""
    for file in os.listdir(os.path.join(ROOT_DIR, "backup")):
        if file.endswith(".zip"):
            file_time = int(file.replace(".zip", "").replace("-", "").replace("_", ""))
            if file_time > last_backup_time:
                last_backup_time = file_time
                last_backup_file = file.replace(".zip", "")

    if last_backup_file == "":
        last_backup = "Never"
    else:
        last_backup = time_ago_string(
            datetime.strptime(last_backup_file, "%Y-%m-%d_%H-%M-%S")
        )

    return render_template("admin_server.html", last_backup=last_backup)


@login_required
@admin_bp.route("/admin/server/backup")
def AdminBackup():
    if not isAdmin(current_user):
        return abort(404)

    backup = Backup()
    if not backup:
        return make_response("Failed to backup", 400)
    return redirect("/admin/server")


@login_required
@admin_bp.route("/admin/server/pull")
def AdminGitPull():
    if not isAdmin(current_user):
        return abort(404)

    Log("admin", current_user.username + " pulled from git.")

    # Git pull and return response
    output = subprocess.check_output(["git", "pull"])

    Log("admin", "Pulled from git. Output: " + output.decode("utf-8"))

    # TODO: restart server

    return make_response(output.decode("utf-8"), 200)


@login_required
@admin_bp.route("/admin/createadmin", methods=["GET", "POST"])
def AdminCreateAdmin():
    if not isAdmin(current_user):
        return abort(404)

    if request.method == "GET":
        return render_template("admin_createadmin.html")
    if request.method == "POST":
        username = request.form["username"]
        rank = request.form["rank"]

        # create random password
        password = secrets.token_urlsafe(24)
        new_admin = Admin(
            username=username,
            password=bcrypt.generate_password_hash(password).decode("utf-8"),
            rank=int(rank),
        )
        db.session.add(new_admin)
        db.session.commit()

        Log(
            "admin",
            current_user.username
            + " created admin: "
            + username
            + " with rank: "
            + rank,
        )
        return "Admin created! Username: " + username + " Password: " + password


@login_required
@admin_bp.route("/admin/players")
def AdminPlayers():
    if not isAdmin(current_user):
        return abort(404)

    players = Player.query.all()

    # convert player to dict
    players = [player.as_dict() for player in players]

    # remove any players that do not have a multiplayer name
    players = [
        player
        for player in players
        if player["game"] != None and player["leader_level"] != None
    ]

    # remove any player that is banned
    players = [player for player in players if not IsUserBanned(player["username"])]

    for player in players:
        player["last_online"] = datetime.fromtimestamp(
            player["last_online"], tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")

        # if player's multiplayer name is empty, attempt to get it from their game
        if player["multiplayer_name"] == None:
            player["multiplayer_name"] = GetNameFromSave(player["game"])

    sortQuery = request.args.get("sort")

    if sortQuery is not None:
        players = sorted(players, key=lambda player: player[sortQuery], reverse=True)
    else:
        players = players[::-1]

    return render_template(
        "admin_players.html", players=players, player_count=len(players)
    )


@login_required
@admin_bp.route("/admin/players/<player>")
def AdminPlayer(player):
    if not isAdmin(current_user):
        return abort(404)

    player = Player.query.filter_by(username=player).first()

    if player is None:
        return make_response("No player found!", 404)

    player = player.as_dict()

    player["last_online"] = datetime.fromtimestamp(
        player["last_online"], tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")

    game = None
    try:
        game = DecryptGameData(player["game"])
        if player["multiplayer_name"] == None:
            player["multiplayer_name"] = game["MultiplayerPlayerName"]
    except Exception:
        Log(
            "admin",
            "Failed to decrypt player game data for player: " + player["username"],
        )
        game = None

    if game is None:
        return render_template("admin_player.html", player=player)

    battle_history = game["BattleHistory"]
    battle_history.sort(key=lambda x: x["recordTime"])

    for battle in battle_history:
        battle["recordTime"] = datetime.fromtimestamp(
            battle["recordTime"], tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")

    # fix device name
    if player["devicename"] is not None:
        player["devicename"] = re.sub(
            r"%[0-9A-Fa-f]{2}",
            lambda m: chr(int(m.group(0)[1:], 16)),
            player["devicename"],
        )

    Inventory = game["Inventory"]

    # remove all items that are not creatures
    if Inventory is not None:
        Inventory = [item for item in Inventory if item["_T"] == "CR"]

    return render_template(
        "admin_player.html",
        player=player,
        is_banned=IsUserBanned(player["username"]),
        SoftCurrency=game["SoftCurrency"],
        HardCurrency=int(game["PaidHardCurrency"]) + int(game["FreeHardCurrency"]),
        PvpCurrency=game["PvpCurrency"],
        EvolutionShards=game.get("EvolutionShards", 0),
        InstalledDate=datetime.fromtimestamp(
            game["InstalledDate"], tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC"),
        PVPBanned=bool(game["Zxcvbnm"]),
        MultiplayerLevel=game["MultiplayerLevel"],
        InventorySpace=game["InventorySpace"],
        RankXP=game.get("RankXP", 0),
        BattleHistory=battle_history,
        DeviceName=player["devicename"],
        Inventory=Inventory,
        CardCollection=game.get("CardCollection", []),
        Leaders=game.get("Leaders", []),
    )


@login_required
@admin_bp.route("/admin/players/<player>/game")
def AdminPlayerGame(player):
    if not isAdmin(current_user):
        return abort(404)

    player = Player.query.filter_by(username=player).first()

    if player is None:
        return make_response("No player found!", 404)

    player = player.as_dict()

    try:
        game = DecryptGameData(player["game"])
    except Exception:  # save is most likely not encrypted
        game = player["game"]

    if game is None:
        return make_response("No game found!", 404)

    return render_template(
        "admin_player_game.html", game=game, player_id=player["username"]
    )


@login_required
@admin_bp.route("/admin/players/<player>/game/edit", methods=["POST"])
def AdminPlayerGameEdit(player):
    if not isAdmin(current_user):
        return abort(404)

    player = Player.query.filter_by(username=player).first()

    if player is None:
        return make_response("No player found!", 404)

    # get game from post
    game = request.form["player_game"]
    print(game)
    # update game
    player.game = game
    db.session.commit()

    Log(
        "admin",
        current_user.username + " edited game data for player: " + player.username,
    )

    return redirect("/admin/players/" + player.username)


@login_required
@admin_bp.route("/admin/players/<player>/edit", methods=["POST"])
def AdminPlayerEdit(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    if "SoftCurrency" in request.form:
        game["SoftCurrency"] = safe_int(request.form["SoftCurrency"], game.get("SoftCurrency", 0))
    if "HardCurrency" in request.form:
        val = safe_int(request.form["HardCurrency"], 0)
        paid = int(game.get("PaidHardCurrency", 0))
        free = val - paid
        if free < 0:
            game["PaidHardCurrency"] = val
            game["FreeHardCurrency"] = 0
        else:
            game["FreeHardCurrency"] = free
    if "PvpCurrency" in request.form:
        game["PvpCurrency"] = safe_int(request.form["PvpCurrency"], game.get("PvpCurrency", 0))
    if "InventorySpace" in request.form:
        game["InventorySpace"] = safe_int(request.form["InventorySpace"], game.get("InventorySpace", 0))
    if "MultiplayerLevel" in request.form:
        new_rank = safe_int(request.form["MultiplayerLevel"], game.get("MultiplayerLevel", 0))
        game["MultiplayerLevel"] = new_rank
    if "leader_level" in request.form:
        db_player.leader_level = safe_int(request.form["leader_level"], db_player.leader_level or 0)
        game["AdminLeaderLevel"] = db_player.leader_level
    if "level" in request.form:
        db_player.level = safe_int(request.form["level"], db_player.level or 0)
        game["AdminPlayerLevel"] = db_player.level
    if "EvolutionShards" in request.form:
        game["EvolutionShards"] = safe_int(request.form["EvolutionShards"], game.get("EvolutionShards", 0))
    if "RankXP" in request.form:
        game["RankXP"] = safe_int(request.form["RankXP"], game.get("RankXP", 0))
    if "Zxcvbnm" in request.form:
        game["Zxcvbnm"] = 1
    else:
        game["Zxcvbnm"] = 0

    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + " edited resources for player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/add_creature", methods=["POST"])
def AdminPlayerAddCreature(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    creature_id = request.form.get("creature_id", "").strip()
    creature_xp = int(request.form.get("creature_xp", 0))
    creature_stars = int(request.form.get("creature_stars", 1))

    if not creature_id:
        return make_response("Creature ID is required!", 400)

    new_creature = {
        "_T": "CR",
        "ID": creature_id,
        "Xp": creature_xp,
        "StarRating": creature_stars,
    }

    if game.get("Inventory") is None:
        game["Inventory"] = []
    game["Inventory"].append(new_creature)

    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + " added creature " + creature_id + " to player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/delete_creature/<int:index>", methods=["POST"])
def AdminPlayerDeleteCreature(player, index):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    inventory = game.get("Inventory", [])
    creatures = [item for item in inventory if item.get("_T") == "CR"]

    if 0 <= index < len(creatures):
        creature_to_delete = creatures[index]
        inventory.remove(creature_to_delete)
        game["Inventory"] = inventory

        db_player.game = EncryptGameData(game, player)
        db.session.commit()

        Log("admin", current_user.username + " deleted creature from player: " + player)

    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/add_card", methods=["POST"])
def AdminPlayerAddCard(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    card_id = request.form.get("card_id", "").strip()
    if not card_id:
        return make_response("Card ID is required!", 400)

    new_card = {"ID": card_id, "Stat": 1}
    if game.get("CardCollection") is None:
        game["CardCollection"] = []
    game["CardCollection"].append(new_card)

    inventory = game.get("Inventory", [])
    next_uid = max([item.get("UniqueID", 0) for item in inventory], default=0) + 1
    inventory.append({
        "_T": "CA",
        "ID": card_id,
        "UniqueID": next_uid,
        "Favorite": 0,
        "CreatureUID": -1,
        "CreatureSlot": 0,
    })
    game["Inventory"] = inventory

    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + " added card " + card_id + " to player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/delete_card/<int:index>", methods=["POST"])
def AdminPlayerDeleteCard(player, index):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    cards = game.get("CardCollection", [])
    if 0 <= index < len(cards):
        cards.pop(index)
        game["CardCollection"] = cards

        db_player.game = EncryptGameData(game, player)
        db.session.commit()

        Log("admin", current_user.username + " deleted card from player: " + player)

    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/add_all_creatures", methods=["POST"])
def AdminPlayerAddAllCreatures(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    with open(os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Creatures.json"), "r") as f:
        all_creatures = json.load(f)

    existing_ids = set()
    inventory = game.get("Inventory", [])
    for item in inventory:
        if item.get("_T") == "CR":
            existing_ids.add(item.get("ID"))

    next_uid = max([item.get("UniqueID", 0) for item in inventory if item.get("_T") == "CR"], default=0) + 1
    added = 0
    for creature in all_creatures:
        cid = creature["ID"]
        if cid not in existing_ids:
            card_slots = int(creature.get("CardSlots", 1))
            default_cards = []
            for i in range(1, 6):
                ac = creature.get(f"ActionCard{i}", "")
                if ac:
                    default_cards.append(ac)
            default_cards = default_cards[:card_slots]

            inventory.append({
                "_T": "CR",
                "ID": cid,
                "UniqueID": next_uid,
                "Xp": 0,
                "Favorite": 0,
                "Passive": 1,
                "PassiveFeeds": 0,
                "StarRating": 1,
                "Cards": default_cards,
            })
            next_uid += 1
            added += 1

    game["Inventory"] = inventory
    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + f" added {added} creatures to player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/max_all_creatures", methods=["POST"])
def AdminPlayerMaxAllCreatures(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    with open(os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Creatures.json"), "r") as f:
        all_creatures = json.load(f)
    creature_blueprint_map = {c["ID"]: c for c in all_creatures}

    inventory = game.get("Inventory", [])
    count = 0
    for item in inventory:
        if item.get("_T") == "CR":
            item["StarRating"] = 5
            item["Xp"] = 70325
            if "Cards" not in item:
                bp = creature_blueprint_map.get(item.get("ID"), {})
                card_slots = int(bp.get("CardSlots", 1))
                default_cards = []
                for i in range(1, 6):
                    ac = bp.get(f"ActionCard{i}", "")
                    if ac:
                        default_cards.append(ac)
                item["Cards"] = default_cards[:card_slots]
            count += 1

    game["Inventory"] = inventory
    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + f" maxed {count} creatures for player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/add_max_creature", methods=["POST"])
def AdminPlayerAddMaxCreature(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    creature_id = request.form.get("creature_id", "").strip()
    if not creature_id:
        return make_response("Creature ID is required!", 400)

    inventory = game.get("Inventory", [])
    next_uid = max([item.get("UniqueID", 0) for item in inventory if item.get("_T") == "CR"], default=0) + 1

    inventory.append({
        "_T": "CR",
        "ID": creature_id,
        "UniqueID": next_uid,
        "Xp": 70325,
        "Favorite": 0,
        "Passive": 1,
        "PassiveFeeds": 0,
        "StarRating": 5,
    })

    game["Inventory"] = inventory
    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + f" added max creature {creature_id} to player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/add_all_cards", methods=["POST"])
def AdminPlayerAddAllCards(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    with open(os.path.join(ROOT_DIR, "data/persist/Blueprints/db_ActionCards.json"), "r") as f:
        all_cards = json.load(f)

    existing_ids = set()
    cards = game.get("CardCollection", [])
    for card in cards:
        existing_ids.add(card.get("ID"))

    inventory = game.get("Inventory", [])
    existing_inv_ids = set()
    for item in inventory:
        if item.get("_T") == "CA":
            existing_inv_ids.add(item.get("ID"))

    next_uid = max([item.get("UniqueID", 0) for item in inventory], default=0) + 1
    added = 0
    for card in all_cards:
        cid = card["ID"]
        if cid not in existing_ids:
            cards.append({"ID": cid, "Stat": 1})
        if cid not in existing_inv_ids:
            inventory.append({
                "_T": "CA",
                "ID": cid,
                "UniqueID": next_uid,
                "Favorite": 0,
                "CreatureUID": -1,
                "CreatureSlot": 0,
            })
            next_uid += 1
            added += 1

    game["CardCollection"] = cards
    game["Inventory"] = inventory
    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + f" added {added} action cards to player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/add_all_leaders", methods=["POST"])
def AdminPlayerAddAllLeaders(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    with open(os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Leaders.json"), "r") as f:
        all_leaders = json.load(f)

    existing_ids = set()
    leaders = game.get("Leaders", [])
    for leader in leaders:
        existing_ids.add(leader.get("ID"))

    added = 0
    for leader in all_leaders:
        lid = leader["ID"]
        if lid not in existing_ids:
            leaders.append({"ID": lid, "Skin": lid, "OwnedSkins": []})
            added += 1

    game["Leaders"] = leaders
    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + f" added {added} leaders to player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/add_leader", methods=["POST"])
def AdminPlayerAddLeader(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    leader_id = request.form.get("leader_id", "").strip()
    if not leader_id:
        return make_response("Leader ID is required!", 400)

    leaders = game.get("Leaders", [])
    existing_ids = {l.get("ID") for l in leaders}

    if leader_id not in existing_ids:
        leaders.append({"ID": leader_id, "Skin": leader_id, "OwnedSkins": []})
        game["Leaders"] = leaders
        db_player.game = EncryptGameData(game, player)
        db.session.commit()
        Log("admin", current_user.username + f" added leader {leader_id} to player: " + player)

    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/add_all_skins", methods=["POST"])
def AdminPlayerAddAllSkins(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    with open(os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Leaders.json"), "r") as f:
        all_leaders = json.load(f)

    leaders = game.get("Leaders", [])
    owned_ids = {l.get("ID") for l in leaders}

    added = 0
    for blueprint in all_leaders:
        skin_of = blueprint.get("SkinOf")
        lid = blueprint["ID"]
        if skin_of and skin_of in owned_ids and lid not in owned_ids:
            leaders.append({"ID": lid, "Skin": lid, "OwnedSkins": []})
            added += 1

    game["Leaders"] = leaders
    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + f" added {added} skins to player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/<action>")
def AdminPlayerAction(player, action):
    if not isAdmin(current_user):
        return abort(404)

    Log("admin", current_user.username + " performed " + action + " on " + player)

    if action == "ban":
        # check if player id is in banlist, if not, add it
        if not IsUserBanned(player):
            newban = Bans(
                username=player,
                bantype="userid",
                author=current_user.username,
                time=int(time.time()),
            )
            db.session.add(newban)
            db.session.commit()
    elif action == "unban":
        # check if player id is in banlist, if yes, remove it
        if IsUserBanned(player):
            player_check = Bans.query.filter_by(username=player).first()
            db.session.delete(player_check)
            db.session.commit()
    else:
        return make_response("Invalid action!", 400)

    DiscordWebhookMessage(
        current_user.username + " performed " + action + " on ID: " + player
    )
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/ipban/<ip>/unban")
def AdminIPBan(ip):
    if not isAdmin(current_user):
        return abort(404)

    Log("admin", current_user.username + " performed unban on " + ip)

    player_check = Bans.query.filter_by(username=ip).first()
    db.session.delete(player_check)
    db.session.commit()

    DiscordWebhookMessage(current_user.username + " performed unban on IP: " + ip)
    return redirect("/admin/bannedips")


@login_required
@admin_bp.route("/admin/ipban", methods=["POST"])
def AdminIPBanAction():
    if not isAdmin(current_user):
        return abort(404)

    Log("admin", current_user.username + " performed ban on " + request.form["ip"])

    newban = Bans(
        username=request.form["ip"],
        bantype="ip",
        author=current_user.username,
        time=int(time.time()),
    )
    db.session.add(newban)
    db.session.commit()

    DiscordWebhookMessage(
        current_user.username + " performed ban on IP: " + request.form["ip"]
    )
    return redirect("/admin/bannedips")


@login_required
@admin_bp.route("/admin/bannedplayers")
def AdminBannedPlayers():
    if not isAdmin(current_user):
        return abort(404)

    bans = Bans.query.filter_by(bantype="userid").all()
    bans = [ban.as_dict() for ban in bans]

    # get player name
    for ban in bans:
        ban["multiplayer_name"] = (
            Player.query.filter_by(username=ban["username"]).first().multiplayer_name
        )
        if ban["multiplayer_name"] is None:
            ban["multiplayer_name"] = GetNameFromSave(
                Player.query.filter_by(username=ban["username"]).first().game
            )
        if ban["time"] is not None:
            ban["time"] = datetime.fromtimestamp(ban["time"], tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )

    return render_template("admin_bannedplayers.html", bans=bans)


@login_required
@admin_bp.route("/admin/bannedips")
def AdminBannedIPs():
    if not isAdmin(current_user):
        return abort(404)

    bans = Bans.query.filter_by(bantype="ip").all()
    bans = [ban.as_dict() for ban in bans]

    for ban in bans:
        ban["time"] = datetime.fromtimestamp(ban["time"], tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    return render_template("admin_bannedips.html", bans=bans)


@login_required
@admin_bp.route("/admin/maintenance")
def AdminMaintenance():
    if not isAdmin(current_user):
        return abort(404)

    return render_template("admin_maintenance.html", maintenance=maintenance)


@login_required
@admin_bp.route("/admin/maintenance/<action>")
def AdminMaintenanceAction(action):
    if not isAdmin(current_user):
        return abort(404)

    global maintenance
    if action == "enable":
        maintenance = True
    elif action == "disable":
        maintenance = False
    Log(
        "admin",
        current_user.username
        + " updated maintenance mode to "
        + ("on" if maintenance else "off"),
    )
    return redirect("/admin/maintenance")


@admin_bp.route("/admin/logout")
def AdminLogout():
    logout_user()
    return redirect("/admin")


@login_required
@admin_bp.route("/admin/misc")
def AdminMisc():
    if not isAdmin(current_user):
        return abort(404)

    return render_template("admin_misc.html")


@login_required
@admin_bp.route("/admin/redeemcodes")
def AdminRedeemCodes():
    if not isAdmin(current_user):
        return abort(404)

    codes = RedeemCode.query.all()
    return render_template("admin_redeemcodes.html", codes=codes)


@login_required
@admin_bp.route("/admin/redeemcodes/add", methods=["POST"])
def AdminRedeemCodeAdd():
    if not isAdmin(current_user):
        return abort(404)

    code = request.form.get("code", "").strip().upper()
    reward_type = request.form.get("reward_type", "").strip()
    reward_amount = safe_int(request.form.get("reward_amount", ""), 0)

    if not code or not reward_type or reward_amount <= 0:
        return make_response("Invalid input!", 400)

    existing = RedeemCode.query.filter_by(code=code).first()
    if existing:
        existing.reward_type = reward_type
        existing.reward_amount = reward_amount
        existing.enabled = True
    else:
        new_code = RedeemCode(
            code=code,
            reward_type=reward_type,
            reward_amount=reward_amount,
            enabled=True,
            created_by=current_user.username,
        )
        db.session.add(new_code)

    db.session.commit()
    Log("admin", current_user.username + f" added/updated redeem code: {code}")
    return redirect("/admin/redeemcodes")


@login_required
@admin_bp.route("/admin/redeemcodes/delete/<code>", methods=["POST"])
def AdminRedeemCodeDelete(code):
    if not isAdmin(current_user):
        return abort(404)

    RedeemCode.query.filter_by(code=code).delete()
    db.session.commit()
    Log("admin", current_user.username + f" deleted redeem code: {code}")
    return redirect("/admin/redeemcodes")


@login_required
@admin_bp.route("/admin/redeemcodes/toggle/<code>", methods=["POST"])
def AdminRedeemCodeToggle(code):
    if not isAdmin(current_user):
        return abort(404)

    db_code = RedeemCode.query.filter_by(code=code).first()
    if db_code:
        db_code.enabled = not db_code.enabled
        db.session.commit()
    Log("admin", current_user.username + f" toggled redeem code: {code}")
    return redirect("/admin/redeemcodes")


@login_required
@admin_bp.route("/admin/logs/delete/olderthan/<days>")
def AdminLogsDeleteOlderThan(days):
    if not isAdmin(current_user):
        return abort(404)

    # convert days to seconds
    days = int(days)
    seconds = days * 86400

    # delete logs older than x days
    db.session.query(Logs).filter(Logs.time < int(time.time()) - seconds).delete()
    db.session.commit()

    Log(
        "admin",
        current_user.username + " deleted logs older than " + str(days) + " days",
    )

    return redirect("/admin/logs")


@login_required
@admin_bp.route("/admin/upsight/delete/olderthan/<days>")
def AdminUpsightDeleteOlderThan(days):
    if not isAdmin(current_user):
        return abort(404)

    # convert days to seconds
    days = int(days)
    seconds = days * 86400

    # delete logs older than x days
    db.session.query(UpsightLogs).filter(
        UpsightLogs.time < int(time.time()) - seconds
    ).delete()
    db.session.commit()

    Log(
        "admin",
        current_user.username
        + " deleted upsight logs older than "
        + str(days)
        + " days",
    )

    return redirect("/admin/upsight")


@login_required
@admin_bp.route("/admin/logs", methods=["GET"])
def AdminLogs():
    if not isAdmin(current_user):
        return abort(404)

    perpage = 20
    pagerequest = request.args.get("page", 1, type=int)
    query = request.args.get("query", "", type=str)
    logs = db.paginate(
        db.select(Logs).order_by(Logs.id.desc()), page=pagerequest, per_page=perpage
    )

    if query != "":
        logs = db.paginate(
            db.select(Logs).filter(Logs.player == query).order_by(Logs.id.desc()),
            page=pagerequest,
            per_page=perpage,
        )

    return render_template("admin_logs.html", logs=logs, query=query)


@login_required
@admin_bp.route("/admin/upsight", methods=["GET"])
def AdminUpsight():
    if not isAdmin(current_user):
        return abort(404)

    perpage = 20
    pagerequest = request.args.get("page", 1, type=int)
    query = request.args.get("query", "", type=str)
    logs = db.paginate(
        db.select(UpsightLogs).order_by(UpsightLogs.id.desc()),
        page=pagerequest,
        per_page=perpage,
    )

    if query != "":
        logs = db.paginate(
            db.select(UpsightLogs)
            .filter(UpsightLogs.player_id == query)
            .order_by(UpsightLogs.id.desc()),
            page=pagerequest,
            per_page=perpage,
        )

    # convert time
    for log in logs.items:
        log.time = datetime.fromtimestamp(log.time)

    return render_template("admin_upsight.html", logs=logs, query=query)
