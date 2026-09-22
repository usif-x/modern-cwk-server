import json, os, random, re, secrets, string, subprocess, time
from datetime import datetime, timezone
from flask import Blueprint, Response, abort, jsonify, make_response, redirect, render_template, request
from flask_login import current_user, login_required, login_user, logout_user

from app import db, bcrypt, maintenance, badcharaters, app as flask_app
from app.models import Admin, AdminActivity, Bans, Logs, Player, RedeemCode, UpsightLogs

from app.utils import (
    DecryptGameData, EncryptGameData, DiscordWebhookMessage, GetNameFromSave,
    GetPlayerWins, IPFromRequest, InvalidUsername, IsUserBanned, Log,
    PlayerLog, safe_int, time_ago_string, isAdmin, Backup, UpdateLastOnline,
    GetXPForRank, GetRankForXP, GetRankXPTable, GetPvpBanlist, SavePvpBanlist,
    FindBrokenSaveIssues, RepairGameData, GetBanExpiry, FormatBanExpiry,
    BuildTransferredGame, GetPvpRankName, GetTutorialOnlyCreatureIds,
    IsTutorialOnlyCreature, GetLeaderSkinBase, GetLeaderSkins,
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
        try:
            log.time = datetime.fromtimestamp(int(log.time), tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
        except (ValueError, TypeError, OSError):
            log.time = str(log.time)

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
@admin_bp.route("/admin/top_pvp")
def AdminTopPvp():
    if not isAdmin(current_user):
        return abort(404)

    entries = []
    for player in Player.query.all():
        if player.game is None or player.game in (b"", b" "):
            continue
        try:
            game = DecryptGameData(player.game)
        except Exception:
            continue
        if not isinstance(game, dict):
            continue

        name = player.multiplayer_name or game.get("MultiplayerPlayerName") or "Unnamed Player"
        last_online = player.last_online
        if last_online is not None:
            try:
                last_online = datetime.fromtimestamp(
                    last_online, tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S UTC")
            except (ValueError, TypeError, OSError):
                last_online = str(last_online)

        multiplayer_level = safe_int(game.get("MultiplayerLevel", 0))
        entries.append(
            {
                "username": player.username,
                "multiplayer_name": name,
                "multiplayer_level": multiplayer_level,
                "pvp_rank_name": GetPvpRankName(multiplayer_level),
                "leader_level": safe_int(player.leader_level, 0),
                "best_multiplayer_level": safe_int(game.get("BestMultiplayerLevel", 0)),
                "rank_xp": safe_int(game.get("RankXP", 0)),
                "is_banned": IsUserBanned(player.username),
                "last_online": last_online,
            }
        )

    # Lower MultiplayerLevel = better PVP rank (1 = Super Amadeus, 25 = Dweeb).
    entries.sort(key=lambda e: (e["multiplayer_level"] if e["multiplayer_level"] > 0 else 999))
    for index, entry in enumerate(entries):
        entry["ranking"] = index + 1

    return render_template(
        "admin_top_pvp.html",
        players=entries[:50],
        total_players=len(entries),
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
            player["multiplayer_name"] = game.get("MultiplayerPlayerName")
    except Exception:
        Log(
            "admin",
            "Failed to decrypt player game data for player: " + player["username"],
        )
        game = None

    if game is None:
        return render_template(
            "admin_player.html",
            player=player,
            is_banned=IsUserBanned(player["username"]),
            save_issues=["Game save could not be decrypted. Use Import JSON to restore it."],
            SoftCurrency=0,
            HardCurrency=0,
            PvpCurrency=0,
            EvolutionShards=0,
            InstalledDate="N/A",
            PVPBanned=False,
            MultiplayerLevel=0,
            InventorySpace=0,
            RankXP=0,
            BattleHistory=[],
            DeviceName=player["devicename"],
            Inventory=[],
            CardCollection=[],
            Leaders=[],
            HelperCreature=None,
            invalid_creature_count=0,
            rank_xp_json=json.dumps(GetRankXPTable()),
        )

    save_issues = FindBrokenSaveIssues(game)

    battle_history = game.get("BattleHistory", [])
    if not isinstance(battle_history, list):
        battle_history = []
    battle_history = [b for b in battle_history if isinstance(b, dict)]
    battle_history.sort(key=lambda x: x.get("recordTime", 0))

    for battle in battle_history:
        battle["recordTime"] = datetime.fromtimestamp(
            battle.get("recordTime", 0), tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")

    # fix device name
    if player["devicename"] is not None:
        player["devicename"] = re.sub(
            r"%[0-9A-Fa-f]{2}",
            lambda m: chr(int(m.group(0)[1:], 16)),
            player["devicename"],
        )

    Inventory = game.get("Inventory", [])

    # remove all items that are not creatures
    if not isinstance(Inventory, list):
        Inventory = []
    Inventory = [item for item in Inventory if isinstance(item, dict) and item.get("_T") == "CR"]

    tutorial_creature_ids = GetTutorialOnlyCreatureIds()
    invalid_creature_count = sum(
        1 for item in Inventory if item.get("ID") in tutorial_creature_ids
    )

    # parse helper creature JSON
    helper_creature = None
    if player.get("helper_creature"):
        try:
            helper_creature = json.loads(player["helper_creature"])
        except (json.JSONDecodeError, TypeError):
            helper_creature = None

    # compute effective rank across game save and DB
    game_saved_lvl = safe_int(game.get("PlayersLastSavedLevel", 0))
    game_xp_lvl = GetRankForXP(game.get("RankXP", 0))
    admin_lvl = safe_int(game.get("AdminLeaderLevel", 0))
    effective_rank = max(player.get("leader_level") or 0, game_saved_lvl, game_xp_lvl, admin_lvl)
    if effective_rank > (player.get("leader_level") or 0):
        player["leader_level"] = effective_rank

    card_collection = game.get("CardCollection", [])
    if not isinstance(card_collection, list):
        card_collection = []
    leaders = game.get("Leaders", [])
    if not isinstance(leaders, list):
        leaders = []

    return render_template(
        "admin_player.html",
        player=player,
        is_banned=IsUserBanned(player["username"]),
        save_issues=save_issues,
        SoftCurrency=game.get("SoftCurrency", 0),
        HardCurrency=int(game.get("PaidHardCurrency", 0)) + int(game.get("FreeHardCurrency", 0)),
        PvpCurrency=game.get("PvpCurrency", 0),
        EvolutionShards=game.get("EvolutionShards", 0),
        InstalledDate=datetime.fromtimestamp(
            game.get("InstalledDate", 0), tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC"),
        PVPBanned=bool(game.get("Zxcvbnm", 0)),
        MultiplayerLevel=game.get("MultiplayerLevel", 0),
        InventorySpace=game.get("InventorySpace", 0),
        RankXP=game.get("RankXP", 0),
        BattleHistory=battle_history,
        DeviceName=player["devicename"],
        Inventory=Inventory,
        CardCollection=card_collection,
        Leaders=leaders,
        HelperCreature=helper_creature,
        invalid_creature_count=invalid_creature_count,
        rank_xp_json=json.dumps(GetRankXPTable()),
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
    game_raw = request.form["player_game"]

    # try to parse as JSON and re-encrypt
    try:
        game_json = json.loads(game_raw)
        db_rank = max(
            safe_int(game_json.get("PlayersLastSavedLevel", 0)),
            GetRankForXP(safe_int(game_json.get("RankXP", 0))),
            safe_int(game_json.get("AdminLeaderLevel", 0))
        )
        if db_rank > 0:
            player.leader_level = db_rank
            player.level = max(player.level or 0, db_rank)
            game_json["AdminLeaderLevel"] = db_rank
            game_json["AdminPlayerLevel"] = player.level
            game_json["PlayersLastSavedLevel"] = db_rank
        player.game = EncryptGameData(game_json, player.username)
    except (json.JSONDecodeError, TypeError):
        # not JSON, save as-is (raw string)
        player.game = game_raw

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
    # PVP rank: MultiplayerLevel and BestMultiplayerLevel are always kept equal
    # (1 = Super Amadeus best, 25 = Dweeb worst).
    if "MultiplayerLevel" in request.form or "BestMultiplayerLevel" in request.form:
        source_value = request.form.get(
            "MultiplayerLevel", request.form.get("BestMultiplayerLevel")
        )
        new_pvp_rank = safe_int(source_value, game.get("MultiplayerLevel", 1))
        game["MultiplayerLevel"] = new_pvp_rank
        game["BestMultiplayerLevel"] = new_pvp_rank
    if "PointsInMultiplayerLevel" in request.form:
        game["PointsInMultiplayerLevel"] = safe_int(
            request.form["PointsInMultiplayerLevel"], game.get("PointsInMultiplayerLevel", 0)
        )
    if "MultiplayerName" in request.form:
        new_name = request.form["MultiplayerName"].strip()
        if new_name and new_name != db_player.multiplayer_name:
            db_player.multiplayer_name = new_name
            game["MultiplayerPlayerName"] = new_name

    # Synchronize Rank (leader_level), Player Level (level), RankXP, and PlayersLastSavedLevel
    old_leader_level = safe_int(db_player.leader_level, 0)
    old_level = safe_int(db_player.level, 0)
    old_rank_xp = safe_int(game.get("RankXP", 0))

    new_leader_level = safe_int(request.form.get("leader_level"), old_leader_level) if "leader_level" in request.form else old_leader_level
    new_level = safe_int(request.form.get("level"), old_level) if "level" in request.form else old_level
    submitted_rank_xp = safe_int(request.form.get("RankXP"), old_rank_xp) if "RankXP" in request.form else old_rank_xp

    # Determine desired target rank and XP
    if new_leader_level != old_leader_level:
        # Admin explicitly changed Rank (leader_level)
        target_rank = new_leader_level
        required_xp = GetXPForRank(target_rank)
        if target_rank < old_leader_level:
            # Demotion: reset XP to the required XP for the lower rank unless submitted XP is valid for it
            if submitted_rank_xp >= GetXPForRank(target_rank + 1) or submitted_rank_xp < required_xp:
                final_xp = required_xp
            else:
                final_xp = submitted_rank_xp
        else:
            # Promotion: boost XP to at least the required XP for that rank
            final_xp = max(submitted_rank_xp, required_xp)
    elif new_level != old_level and new_level > old_leader_level:
        # Admin specifically changed Player Level to a higher value
        target_rank = new_level
        final_xp = max(submitted_rank_xp, GetXPForRank(target_rank))
    elif submitted_rank_xp != old_rank_xp:
        # Admin specifically changed RankXP
        final_xp = submitted_rank_xp
        target_rank = max(old_leader_level, GetRankForXP(final_xp))
    else:
        # Neither rank nor XP was explicitly changed
        target_rank = max(old_leader_level, old_level, 1)
        final_xp = submitted_rank_xp

    effective_rank = max(target_rank, GetRankForXP(final_xp), 1)

    db_player.leader_level = effective_rank
    db_player.level = effective_rank
    game["AdminLeaderLevel"] = effective_rank
    game["AdminPlayerLevel"] = effective_rank
    game["PlayersLastSavedLevel"] = effective_rank
    game["RankXP"] = final_xp

    if "EvolutionShards" in request.form:
        game["EvolutionShards"] = safe_int(request.form["EvolutionShards"], game.get("EvolutionShards", 0))
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
    if IsTutorialOnlyCreature(creature_id):
        return make_response("This is a tutorial-only creature and cannot be added to a player.", 400)

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
@admin_bp.route("/admin/players/<player>/delete_all_creatures", methods=["POST"])
def AdminPlayerDeleteAllCreatures(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    inventory = game.get("Inventory", [])
    initial_count = len([i for i in inventory if i.get("_T") == "CR"])
    game["Inventory"] = [item for item in inventory if item.get("_T") != "CR"]

    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + f" deleted all ({initial_count}) creatures from player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/delete_creatures_bulk", methods=["POST"])
def AdminPlayerDeleteCreaturesBulk(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    to_delete = set()
    for idx in request.form.getlist("indexes"):
        try:
            to_delete.add(int(idx))
        except (ValueError, TypeError):
            pass

    if not to_delete:
        return redirect("/admin/players/" + player)

    inventory = game.get("Inventory", [])
    creatures = [item for item in inventory if item.get("_T") == "CR"]
    non_creatures = [item for item in inventory if item.get("_T") != "CR"]

    remaining_creatures = [c for i, c in enumerate(creatures) if i not in to_delete]
    game["Inventory"] = non_creatures + remaining_creatures

    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + f" bulk deleted {len(to_delete)} creatures from player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/max_creature/<int:index>", methods=["POST"])
def AdminPlayerMaxCreature(player, index):
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
        if IsTutorialOnlyCreature(creatures[index].get("ID")):
            return make_response("This is a tutorial-only creature and cannot be modified.", 400)
        creatures[index]["StarRating"] = 5
        creatures[index]["Xp"] = 70325
        db_player.game = EncryptGameData(game, player)
        db.session.commit()
        Log("admin", current_user.username + f" maxed creature index {index} for player: " + player)

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
@admin_bp.route("/admin/players/<player>/delete_all_cards", methods=["POST"])
def AdminPlayerDeleteAllCards(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    initial_count = len(game.get("CardCollection", []))
    game["CardCollection"] = []
    # Also remove action cards from inventory
    inventory = game.get("Inventory", [])
    game["Inventory"] = [item for item in inventory if item.get("_T") != "CA"]

    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + f" deleted all ({initial_count}) action cards from player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/delete_cards_bulk", methods=["POST"])
def AdminPlayerDeleteCardsBulk(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    to_delete = set()
    for idx in request.form.getlist("indexes"):
        try:
            to_delete.add(int(idx))
        except (ValueError, TypeError):
            pass

    if not to_delete:
        return redirect("/admin/players/" + player)

    cards = game.get("CardCollection", [])
    deleted_ids = {cards[i].get("ID") for i in to_delete if 0 <= i < len(cards)}
    game["CardCollection"] = [c for i, c in enumerate(cards) if i not in to_delete]

    # Clean inventory
    inventory = game.get("Inventory", [])
    game["Inventory"] = [item for item in inventory if not (item.get("_T") == "CA" and item.get("ID") in deleted_ids)]

    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + f" bulk deleted {len(to_delete)} cards from player: " + player)
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

    tutorial_ids = GetTutorialOnlyCreatureIds()

    existing_ids = set()
    inventory = game.get("Inventory", [])
    for item in inventory:
        if item.get("_T") == "CR":
            existing_ids.add(item.get("ID"))

    next_uid = max([item.get("UniqueID", 0) for item in inventory if item.get("_T") == "CR"], default=0) + 1
    added = 0
    for creature in all_creatures:
        cid = creature["ID"]
        # Tutorial-only creatures are not collectible; granting them makes the
        # game client flag the save as tampered (Zxcvbnm = 1).
        if cid in tutorial_ids:
            continue
        if cid not in existing_ids:
            new_creature = {
                "_T": "CR",
                "ID": cid,
                "UniqueID": next_uid,
                "Xp": 0,
                "Favorite": 0,
                "Passive": 1,
                "PassiveFeeds": 0,
                "StarRating": 1,
            }
            card_slots = int(creature.get("CardSlots", 1))
            default_cards = [
                creature.get(f"ActionCard{i}", "") for i in range(1, 6)
            ]
            default_cards = [c for c in default_cards if c][:card_slots]
            if default_cards:
                new_creature["Cards"] = default_cards

            inventory.append(new_creature)
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

    tutorial_ids = GetTutorialOnlyCreatureIds()

    inventory = game.get("Inventory", [])
    count = 0
    for item in inventory:
        if item.get("_T") == "CR":
            # Never max/modify non-collectible tutorial creatures.
            if item.get("ID") in tutorial_ids:
                continue
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
                default_cards = default_cards[:card_slots]
                if default_cards:
                    item["Cards"] = default_cards
            count += 1

    game["Inventory"] = inventory
    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + f" maxed {count} creatures for player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/remove_invalid_creatures", methods=["POST"])
def AdminPlayerRemoveInvalidCreatures(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None or not isinstance(game, dict):
        return make_response("No game data found!", 400)

    tutorial_ids = GetTutorialOnlyCreatureIds()
    inventory = game.get("Inventory", [])
    if not isinstance(inventory, list):
        inventory = []

    removed = [
        item
        for item in inventory
        if isinstance(item, dict)
        and item.get("_T") == "CR"
        and item.get("ID") in tutorial_ids
    ]
    game["Inventory"] = [
        item
        for item in inventory
        if not (
            isinstance(item, dict)
            and item.get("_T") == "CR"
            and item.get("ID") in tutorial_ids
        )
    ]
    # Clear the client tamper flag so the account can play PVP again.
    game["Zxcvbnm"] = 0

    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log(
        "admin",
        current_user.username
        + f" removed {len(removed)} invalid tutorial creature(s) and cleared the PVP ban flag for player: "
        + player,
    )
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
    if IsTutorialOnlyCreature(creature_id):
        return make_response("This is a tutorial-only creature and cannot be added to a player.", 400)

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

    leaders = game.get("Leaders", [])
    if not isinstance(leaders, list):
        leaders = []
    existing_ids = {l.get("ID") for l in leaders if isinstance(l, dict)}

    # Only base heroes are added here; skins belong in OwnedSkins and are
    # handled by the separate "Add All Skins" action.
    added = 0
    for leader in all_leaders:
        lid = leader["ID"]
        if leader.get("SkinOf"):
            continue
        if lid not in existing_ids:
            leaders.append({"ID": lid, "Skin": lid, "OwnedSkins": []})
            added += 1

    game["Leaders"] = leaders
    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + f" added {added} heroes to player: " + player)
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
    if not isinstance(leaders, list):
        leaders = []
    by_id = {l.get("ID"): l for l in leaders if isinstance(l, dict)}

    base_id = GetLeaderSkinBase(leader_id)
    if base_id:
        # This ID is a skin: store it inside its base hero's OwnedSkins.
        base_entry = by_id.get(base_id)
        if base_entry is None:
            base_entry = {"ID": base_id, "Skin": base_id, "OwnedSkins": []}
            leaders.append(base_entry)
        owned = base_entry.get("OwnedSkins")
        if not isinstance(owned, list):
            owned = []
            base_entry["OwnedSkins"] = owned
        if leader_id not in owned:
            owned.append(leader_id)
            game["Leaders"] = leaders
            db_player.game = EncryptGameData(game, player)
            db.session.commit()
            Log(
                "admin",
                current_user.username
                + f" added skin {leader_id} to hero {base_id} for player: "
                + player,
            )
    elif leader_id not in by_id:
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
    if not isinstance(leaders, list):
        leaders = []
    by_id = {l.get("ID"): l for l in leaders if isinstance(l, dict)}

    # Skins are attached to their base hero's OwnedSkins, never added as
    # independent leaders. Only heroes the player already owns get their skins.
    added = 0
    for blueprint in all_leaders:
        skin_of = blueprint.get("SkinOf")
        lid = blueprint["ID"]
        if not skin_of:
            continue
        base_entry = by_id.get(skin_of)
        if base_entry is None:
            continue
        owned = base_entry.get("OwnedSkins")
        if not isinstance(owned, list):
            owned = []
            base_entry["OwnedSkins"] = owned
        if lid not in owned:
            owned.append(lid)
            added += 1

    game["Leaders"] = leaders
    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + f" added {added} skins to player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/delete_leader/<int:index>", methods=["POST"])
def AdminPlayerDeleteLeader(player, index):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    leaders = game.get("Leaders", [])
    if 0 <= index < len(leaders):
        removed = leaders.pop(index)
        game["Leaders"] = leaders
        db_player.game = EncryptGameData(game, player)
        db.session.commit()
        Log("admin", current_user.username + f" deleted leader {removed.get('ID')} from player: " + player)

    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/delete_all_leaders", methods=["POST"])
def AdminPlayerDeleteAllLeaders(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    initial_count = len(game.get("Leaders", []))
    game["Leaders"] = []

    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + f" deleted all ({initial_count}) leaders from player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/delete_leaders_bulk", methods=["POST"])
def AdminPlayerDeleteLeadersBulk(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    to_delete = set()
    for idx in request.form.getlist("indexes"):
        try:
            to_delete.add(int(idx))
        except (ValueError, TypeError):
            pass

    if not to_delete:
        return redirect("/admin/players/" + player)

    leaders = game.get("Leaders", [])
    game["Leaders"] = [l for i, l in enumerate(leaders) if i not in to_delete]

    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + f" bulk deleted {len(to_delete)} leaders from player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/max_resources", methods=["POST"])
def AdminPlayerMaxResources(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    target_rank = 50
    target_xp = GetXPForRank(target_rank)
    game["SoftCurrency"] = 9999999
    game["PaidHardCurrency"] = 499999
    game["FreeHardCurrency"] = 500000
    game["PvpCurrency"] = 99999
    game["EvolutionShards"] = 9999
    game["InventorySpace"] = 300
    game["RankXP"] = target_xp
    game["PlayersLastSavedLevel"] = target_rank
    game["AdminLeaderLevel"] = target_rank
    game["AdminPlayerLevel"] = target_rank
    game["MultiplayerLevel"] = 10
    game["BestMultiplayerLevel"] = 10
    game["Zxcvbnm"] = 0

    db_player.leader_level = target_rank
    db_player.level = target_rank
    db_player.allyboxspace = 100
    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + " maxed all resources for player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/export_save", methods=["GET"])
def AdminPlayerExportSave(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    response = Response(
        json.dumps(game, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment;filename=player_{player}_save.json"}
    )
    return response


@login_required
@admin_bp.route("/admin/players/<player>/import_save", methods=["POST"])
def AdminPlayerImportSave(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    file = request.files.get("save_file")
    if not file:
        return make_response("No file uploaded!", 400)

    try:
        content = file.read().decode("utf-8")
        parsed = json.loads(content)
    except Exception as e:
        return make_response(f"Invalid JSON file: {e}", 400)

    imported_rank = max(
        safe_int(parsed.get("PlayersLastSavedLevel", 0)),
        GetRankForXP(safe_int(parsed.get("RankXP", 0))),
        safe_int(parsed.get("AdminLeaderLevel", 0))
    )
    if imported_rank > 0:
        db_player.leader_level = imported_rank
        db_player.level = max(db_player.level or 0, imported_rank)
        parsed["AdminLeaderLevel"] = imported_rank
        parsed["AdminPlayerLevel"] = db_player.level
        parsed["PlayersLastSavedLevel"] = imported_rank

    db_player.game = EncryptGameData(parsed, player)
    db.session.commit()

    Log("admin", current_user.username + " imported JSON save for player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/fix_save", methods=["POST"])
def AdminPlayerFixSave(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None or not isinstance(game, dict):
        return make_response(
            "Game save could not be decrypted. Use Import JSON with a valid save instead.",
            400,
        )

    issues_found = FindBrokenSaveIssues(game)
    repaired, repairs = RepairGameData(
        game,
        username=db_player.username,
        fallback_name=db_player.multiplayer_name or "",
    )

    db_player.game = EncryptGameData(repaired, player)

    effective_rank = max(
        safe_int(repaired.get("PlayersLastSavedLevel", 0)),
        GetRankForXP(safe_int(repaired.get("RankXP", 0))),
        safe_int(repaired.get("AdminLeaderLevel", 0)),
        1,
    )
    db_player.leader_level = max(safe_int(db_player.leader_level, 0), effective_rank)
    db_player.level = max(safe_int(db_player.level, 0), effective_rank)
    ally_space = safe_int(repaired.get("AllyBoxSpace", 0), 0)
    if ally_space > 0:
        db_player.allyboxspace = ally_space

    db.session.commit()

    Log(
        "admin",
        current_user.username
        + f" repaired save for player: {player} ({len(issues_found)} issue(s), {len(repairs)} repair(s))",
    )
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/transfer_progress", methods=["POST"])
def AdminPlayerTransferProgress(player):
    if not isAdmin(current_user):
        return abort(404)

    source = Player.query.filter_by(username=player).first()
    if source is None:
        return make_response("Source player not found!", 404)

    target_uuid = (request.form.get("target_uuid") or "").strip()
    if not target_uuid:
        return make_response("Target account UUID is required!", 400)
    if target_uuid == player:
        return make_response("Source and target accounts must be different!", 400)

    target = Player.query.filter_by(username=target_uuid).first()
    if target is None:
        return make_response("Target player not found!", 404)

    source_game = DecryptGameData(source.game)
    if source_game is None or not isinstance(source_game, dict):
        return make_response("Source account has no valid save data to transfer!", 400)

    target_game = DecryptGameData(target.game)

    # Start from the source's full progress, then restore the target's identity,
    # currencies and PVP flag so only progress/items are transferred.
    new_game = BuildTransferredGame(
        source_game,
        target_game,
        target.username,
        target_name=target.multiplayer_name or "",
    )

    target.game = EncryptGameData(new_game, target.username)

    # Transfer gameplay/profile fields, but never the display name.
    if source.leader_level is not None:
        target.leader_level = source.leader_level
    if source.level is not None:
        target.level = source.level
    if source.allyboxspace is not None:
        target.allyboxspace = source.allyboxspace
    target.deck = source.deck
    target.deck_rank = source.deck_rank
    target.landscapes = source.landscapes
    target.helper_creature = source.helper_creature
    target.leader = source.leader

    effective_rank = max(
        safe_int(target.leader_level, 0),
        GetRankForXP(safe_int(new_game.get("RankXP", 0))),
        safe_int(new_game.get("PlayersLastSavedLevel", 0)),
        1,
    )
    target.leader_level = effective_rank
    target.level = max(safe_int(target.level, 0), effective_rank)

    db.session.commit()

    Log(
        "admin",
        current_user.username + " transferred progress from " + player + " to " + target_uuid,
    )
    DiscordWebhookMessage(
        current_user.username + " transferred progress from " + player + " to " + target_uuid
    )
    return redirect("/admin/players/" + target.username)


@login_required
@admin_bp.route("/admin/players/<player>/reset_save", methods=["POST"])
def AdminPlayerResetSave(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    fresh_save = {
        "SoftCurrency": 5000,
        "PaidHardCurrency": 0,
        "FreeHardCurrency": 100,
        "PvpCurrency": 50,
        "EvolutionShards": 0,
        "InventorySpace": 50,
        "MultiplayerLevel": 25,
        "BestMultiplayerLevel": 25,
        "RankXP": 0,
        "PlayersLastSavedLevel": 1,
        "AdminLeaderLevel": 1,
        "AdminPlayerLevel": 1,
        "Zxcvbnm": 0,
        "InstalledDate": int(time.time()),
        "MultiplayerPlayerName": db_player.multiplayer_name or "Player",
        "Inventory": [
            {
                "_T": "CR",
                "ID": "CR_skeleton",
                "UniqueID": 1,
                "Xp": 0,
                "StarRating": 1,
                "Favorite": 0,
                "Passive": 1,
                "PassiveFeeds": 0,
            }
        ],
        "CardCollection": [],
        "Leaders": [{"ID": "Leader_Finn", "Skin": "Leader_Finn", "OwnedSkins": []}],
        "BattleHistory": [],
    }

    db_player.game = EncryptGameData(fresh_save, player)
    db_player.leader_level = 1
    db_player.level = 1
    db.session.commit()

    Log("admin", current_user.username + " wiped/reset save data for player: " + player)
    return redirect("/admin/players/" + player)


@login_required
@admin_bp.route("/admin/players/<player>/delete", methods=["POST"])
def AdminPlayerDelete(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player:
        db.session.delete(db_player)
        Bans.query.filter_by(username=player).delete()
        db.session.commit()
        Log("admin", current_user.username + " deleted player account: " + player)

    return redirect("/admin/players")


@login_required
@admin_bp.route("/admin/players/bulk_action", methods=["POST"])
def AdminPlayersBulkAction():
    if not isAdmin(current_user):
        return abort(404)

    action = request.form.get("action")
    player_ids = request.form.getlist("player_ids")

    if not player_ids:
        return redirect("/admin/players")

    if action == "ban":
        expires = GetBanExpiry(
            request.form.get("duration", "perm"),
            request.form.get("custom_amount", 1),
            request.form.get("custom_unit", "hours"),
        )
        for pid in player_ids:
            ban = Bans.query.filter_by(username=pid).first()
            if ban is not None:
                ban.bantype = "userid"
                ban.author = current_user.username
                ban.time = int(time.time())
                ban.expires = expires
            else:
                db.session.add(
                    Bans(
                        username=pid,
                        bantype="userid",
                        author=current_user.username,
                        time=int(time.time()),
                        expires=expires,
                    )
                )
        db.session.commit()
        Log(
            "admin",
            current_user.username
            + f" bulk banned {len(player_ids)} players (expires: {FormatBanExpiry(expires)})",
        )
    elif action == "unban":
        for pid in player_ids:
            Bans.query.filter_by(username=pid, bantype="userid").delete()
        db.session.commit()
        Log("admin", current_user.username + f" bulk unbanned {len(player_ids)} players")
    elif action == "delete":
        for pid in player_ids:
            Player.query.filter_by(username=pid).delete()
            Bans.query.filter_by(username=pid).delete()
        db.session.commit()
        Log("admin", current_user.username + f" bulk deleted {len(player_ids)} players")

    return redirect("/admin/players")


@login_required
@admin_bp.route("/admin/players/<player>/<action>", methods=["GET", "POST"])
def AdminPlayerAction(player, action):
    if not isAdmin(current_user):
        return abort(404)

    Log("admin", current_user.username + " performed " + action + " on " + player)

    if action == "ban":
        expires = GetBanExpiry(
            request.form.get("duration", request.args.get("duration", "perm")),
            request.form.get("custom_amount", request.args.get("custom_amount", 1)),
            request.form.get("custom_unit", request.args.get("custom_unit", "hours")),
        )
        ban = Bans.query.filter_by(username=player).first()
        if ban is not None:
            ban.bantype = "userid"
            ban.author = current_user.username
            ban.time = int(time.time())
            ban.expires = expires
        else:
            db.session.add(
                Bans(
                    username=player,
                    bantype="userid",
                    author=current_user.username,
                    time=int(time.time()),
                    expires=expires,
                )
            )
        db.session.commit()
    elif action == "unban":
        # remove the ban regardless of its current/expired state
        Bans.query.filter_by(username=player, bantype="userid").delete()
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

    # purge bans that have already expired
    now = int(time.time())
    Bans.query.filter(
        Bans.bantype == "userid", Bans.expires.isnot(None), Bans.expires != 0, Bans.expires <= now
    ).delete(synchronize_session=False)
    db.session.commit()

    bans = Bans.query.filter_by(bantype="userid").all()
    bans = [ban.as_dict() for ban in bans]

    # get player name
    for ban in bans:
        player = Player.query.filter_by(username=ban["username"]).first()
        ban["multiplayer_name"] = player.multiplayer_name if player else "Unnamed Player"
        if ban["multiplayer_name"] is None and player is not None:
            ban["multiplayer_name"] = GetNameFromSave(player.game)
        if ban["time"] is not None:
            ban["time"] = datetime.fromtimestamp(ban["time"], tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
        ban["expires_display"] = FormatBanExpiry(ban.get("expires"))
        ban["is_permanent"] = ban.get("expires") in (None, 0)

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

    codes = RedeemCode.query.order_by(RedeemCode.code).all()

    creatures = []
    cards = []
    leaders = []
    try:
        with open(os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Creatures.json"), "r") as f:
            c_data = json.load(f)
            creatures = sorted([{"id": c.get("ID", ""), "name": c.get("Name", c.get("ID", ""))} for c in c_data if c.get("ID")], key=lambda x: x["name"])
    except Exception:
        pass

    try:
        with open(os.path.join(ROOT_DIR, "data/persist/Blueprints/db_ActionCards.json"), "r") as f:
            ac_data = json.load(f)
            cards = sorted([{"id": c.get("ID", ""), "name": c.get("Name", c.get("ID", ""))} for c in ac_data if c.get("ID")], key=lambda x: x["name"])
    except Exception:
        pass

    try:
        with open(os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Leaders.json"), "r") as f:
            l_data = json.load(f)
            leaders = sorted([{"id": l.get("ID", ""), "name": l.get("Name", l.get("ID", ""))} for l in l_data if l.get("ID")], key=lambda x: x["name"])
    except Exception:
        pass

    return render_template(
        "admin_redeemcodes.html",
        codes=codes,
        creatures=creatures,
        cards=cards,
        leaders=leaders,
    )


@login_required
@admin_bp.route("/admin/redeemcodes/add", methods=["POST"])
def AdminRedeemCodeAdd():
    if not isAdmin(current_user):
        return abort(404)

    code = request.form.get("code", "").strip().upper()
    reward_type = request.form.get("reward_type", "").strip()
    reward_amount = safe_int(request.form.get("reward_amount", ""), 1)
    reward_item = request.form.get("reward_item", "").strip()

    if not code or not reward_type:
        return make_response("Code and reward type are required!", 400)

    # For item rewards, require reward_item
    if reward_type in ("Creature", "ActionCard", "Leader"):
        if not reward_item:
            return make_response(f"Item selection is required for {reward_type} reward!", 400)
        if reward_type == "Creature":
            # For creatures, reward_amount acts as star rating (1-5)
            reward_amount = min(max(reward_amount, 1), 5)
        elif reward_type == "Leader":
            reward_amount = 1
        elif reward_type == "ActionCard":
            reward_amount = max(reward_amount, 1)
    else:
        if reward_amount <= 0:
            return make_response("Reward amount must be greater than 0!", 400)
        reward_item = ""

    existing = RedeemCode.query.filter_by(code=code).first()
    if existing:
        existing.reward_type = reward_type
        existing.reward_amount = reward_amount
        existing.reward_item = reward_item if reward_item else None
        existing.enabled = True
    else:
        new_code = RedeemCode(
            code=code,
            reward_type=reward_type,
            reward_amount=reward_amount,
            reward_item=reward_item if reward_item else None,
            enabled=True,
            created_by=current_user.username,
        )
        db.session.add(new_code)

    db.session.commit()
    Log("admin", current_user.username + f" added/updated redeem code: {code} ({reward_type} {reward_item} x{reward_amount})")
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


@admin_bp.route("/admin/creatures")
def AdminCreatures():
    if not isAdmin(current_user):
        return abort(404)
    query = (request.args.get("q") or request.args.get("query") or "").strip().lower()
    with open(os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Creatures.json"), "r") as f:
        creatures = json.load(f)
    if query:
        creatures = [c for c in creatures if query in c.get("ID", "").lower() or query in c.get("Name", "").lower()]
    banned_set = set(GetPvpBanlist().get("banned_creatures", []))
    return render_template("admin_creatures.html", creatures=creatures, query=query, total=len(creatures), banned_set=banned_set)


@admin_bp.route("/admin/cards")
def AdminCards():
    if not isAdmin(current_user):
        return abort(404)
    query = (request.args.get("q") or request.args.get("query") or "").strip().lower()
    with open(os.path.join(ROOT_DIR, "data/persist/Blueprints/db_ActionCards.json"), "r") as f:
        cards = json.load(f)
    if query:
        cards = [c for c in cards if query in c.get("ID", "").lower() or query in c.get("Name", "").lower() or query in c.get("Description", "").lower()]
    return render_template("admin_cards.html", cards=cards, query=query, total=len(cards))


@admin_bp.route("/admin/leaders")
def AdminLeaders():
    if not isAdmin(current_user):
        return abort(404)
    query = (request.args.get("q") or request.args.get("query") or "").strip().lower()
    with open(os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Leaders.json"), "r") as f:
        leaders = json.load(f)
    if query:
        leaders = [l for l in leaders if query in l.get("ID", "").lower() or query in l.get("Name", "").lower()]
    banned_set = set(GetPvpBanlist().get("banned_leaders", []))
    return render_template("admin_leaders.html", leaders=leaders, query=query, total=len(leaders), banned_set=banned_set)


@login_required
@admin_bp.route("/admin/pvp_banlist")
def AdminPvpBanlist():
    if not isAdmin(current_user):
        return abort(404)

    banlist = GetPvpBanlist()

    creatures = []
    try:
        with open(os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Creatures.json"), "r") as f:
            creatures = json.load(f)
    except Exception:
        pass

    leaders = []
    try:
        with open(os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Leaders.json"), "r") as f:
            leaders = json.load(f)
    except Exception:
        pass

    creature_map = {c.get("ID"): c.get("Name", c.get("ID")) for c in creatures if "ID" in c}
    leader_map = {l.get("ID"): l.get("Name", l.get("ID")) for l in leaders if "ID" in l}

    banned_creatures_details = [
        {"ID": cid, "Name": creature_map.get(cid, cid)}
        for cid in banlist.get("banned_creatures", [])
    ]
    banned_leaders_details = [
        {"ID": lid, "Name": leader_map.get(lid, lid)}
        for lid in banlist.get("banned_leaders", [])
    ]

    return render_template(
        "admin_pvp_banlist.html",
        banlist=banlist,
        banned_creatures=banned_creatures_details,
        banned_leaders=banned_leaders_details,
        all_creatures=creatures,
        all_leaders=leaders,
        raw_json=json.dumps(banlist, indent=2),
    )


@login_required
@admin_bp.route("/admin/pvp_banlist/add_creature", methods=["POST"])
def AdminPvpBanlistAddCreature():
    if not isAdmin(current_user):
        return abort(404)

    creature_id = request.form.get("creature_id", "").strip()
    return_to = request.form.get("return_to") or "/admin/pvp_banlist"
    if creature_id:
        banlist = GetPvpBanlist()
        banned = banlist.setdefault("banned_creatures", [])
        if creature_id not in banned:
            banned.append(creature_id)
            SavePvpBanlist(banlist)
            Log("admin", f"{current_user.username} added creature '{creature_id}' to PVP banlist")

    return redirect(return_to)


@login_required
@admin_bp.route("/admin/pvp_banlist/remove_creature/<path:creature_id>", methods=["POST", "GET"])
def AdminPvpBanlistRemoveCreature(creature_id):
    if not isAdmin(current_user):
        return abort(404)

    return_to = request.args.get("return_to") or request.form.get("return_to") or "/admin/pvp_banlist"
    banlist = GetPvpBanlist()
    banned = banlist.get("banned_creatures", [])
    if creature_id in banned:
        banned.remove(creature_id)
        banlist["banned_creatures"] = banned
        SavePvpBanlist(banlist)
        Log("admin", f"{current_user.username} removed creature '{creature_id}' from PVP banlist")

    return redirect(return_to)


@login_required
@admin_bp.route("/admin/pvp_banlist/add_leader", methods=["POST"])
def AdminPvpBanlistAddLeader():
    if not isAdmin(current_user):
        return abort(404)

    leader_id = request.form.get("leader_id", "").strip()
    return_to = request.form.get("return_to") or "/admin/pvp_banlist"
    if leader_id:
        banlist = GetPvpBanlist()
        banned = banlist.setdefault("banned_leaders", [])
        if leader_id not in banned:
            banned.append(leader_id)
            SavePvpBanlist(banlist)
            Log("admin", f"{current_user.username} added leader '{leader_id}' to PVP banlist")

    return redirect(return_to)


@login_required
@admin_bp.route("/admin/pvp_banlist/remove_leader/<path:leader_id>", methods=["POST", "GET"])
def AdminPvpBanlistRemoveLeader(leader_id):
    if not isAdmin(current_user):
        return abort(404)

    return_to = request.args.get("return_to") or request.form.get("return_to") or "/admin/pvp_banlist"
    banlist = GetPvpBanlist()
    banned = banlist.get("banned_leaders", [])
    if leader_id in banned:
        banned.remove(leader_id)
        banlist["banned_leaders"] = banned
        SavePvpBanlist(banlist)
        Log("admin", f"{current_user.username} removed leader '{leader_id}' from PVP banlist")

    return redirect(return_to)


@login_required
@admin_bp.route("/admin/pvp_banlist/edit_raw", methods=["POST"])
def AdminPvpBanlistEditRaw():
    if not isAdmin(current_user):
        return abort(404)

    raw_json = request.form.get("raw_json", "").strip()
    try:
        parsed = json.loads(raw_json)
        SavePvpBanlist(parsed)
        Log("admin", f"{current_user.username} updated PVP banlist JSON directly")
    except Exception as e:
        Log("admin", f"Failed to parse PVP banlist JSON: {e}")

    return redirect("/admin/pvp_banlist")

