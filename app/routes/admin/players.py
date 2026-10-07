import threading

from ._common import *
from app.models import AccountLink, TradeCoinBalance


def _ParseIdList(raw):
    if not raw:
        return []
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if item]


def BuildFriendsView(player):
    """Resolve a player's friends and incoming requests into display rows."""
    friend_ids = _ParseIdList(player.get("friends"))
    request_ids = _ParseIdList(player.get("friend_requests"))

    lookup = list(dict.fromkeys(friend_ids + request_ids))

    info = {}
    if lookup:
        for row in Player.query.filter(Player.username.in_(lookup)).all():
            name = row.multiplayer_name
            if not name and row.game:
                try:
                    name = GetNameFromSave(row.game)
                except Exception:
                    name = None

            last_online = row.last_online
            if last_online:
                try:
                    last_online = datetime.fromtimestamp(
                        int(last_online), tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S UTC")
                except (ValueError, TypeError, OSError):
                    last_online = str(last_online)

            info[row.username] = {
                "username": row.username,
                "multiplayer_name": name or "Unnamed",
                "last_online": last_online,
                "banned": IsUserBanned(row.username),
            }

    def build(ids, is_request):
        rows = []
        for uid in ids:
            entry = info.get(uid) or {
                "username": uid,
                "multiplayer_name": "Unknown",
                "last_online": None,
                "banned": IsUserBanned(uid),
            }
            item = dict(entry)
            item["is_request"] = is_request
            rows.append(item)
        return rows

    return build(friend_ids, False), build(request_ids, True)


@admin_bp.route("/admin/players")
@login_required
def AdminPlayers():
    if not isAdmin(current_user):
        return abort(404)

    query = (request.args.get("q") or "").strip()
    sort_query = request.args.get("sort") or ""
    active = request.args.get("active") or ""

    per_page = request.args.get("per_page", 10, type=int)
    if per_page not in (10, 20, 30, 40, 50):
        per_page = 10

    page = request.args.get("page", 1, type=int)

    data = _PlayerListPage(query, sort_query, page, per_page, active)

    return render_template(
        "admin_players.html",
        query=query,
        sort=sort_query,
        active=active,
        **data,
    )


@admin_bp.route("/admin/players/list")
@login_required
def AdminPlayersList():
    """Lightweight JSON feed used for refresh-free search / sort / paging."""
    if not isAdmin(current_user):
        return abort(404)

    query = (request.args.get("q") or "").strip()
    sort_query = request.args.get("sort") or ""
    active = request.args.get("active") or ""

    per_page = request.args.get("per_page", 10, type=int)
    if per_page not in (10, 20, 30, 40, 50):
        per_page = 10

    page = request.args.get("page", 1, type=int)

    return jsonify(_PlayerListPage(query, sort_query, page, per_page, active))


# --- Player list query ------------------------------------------------------
PLAYER_LIST_SORTS = {
    "multiplayer_name": Player.multiplayer_name,
    "last_online": Player.last_online,
    "leader_level": Player.leader_level,
}

# Activity window -> seconds (relative to now).
PLAYER_ACTIVE_WINDOWS = {
    "now": 120,
    "5m": 300,
    "1h": 3600,
    "24h": 86400,
    "7d": 604800,
}


def _ActiveBannedUsernames():
    """Set of usernames with an active (non-expired) user ban."""
    now = int(time.time())
    banned = set()
    for ban in Bans.query.filter_by(bantype="userid").all():
        expires = ban.expires or 0
        if expires == 0 or expires > now:
            banned.add(ban.username)
    return banned


def _PlayerListPage(query, sort_query, page, per_page, active=""):
    """Return one page of the player list using only the needed columns.

    The ``game`` save column (up to tens of MB in total) is never loaded for
    the whole table; it is only read for the handful of rows on the current
    page that are still missing a ``multiplayer_name``.
    """
    base = (
        db.session.query(
            Player.username,
            Player.multiplayer_name,
            Player.leader_level,
            Player.last_online,
        )
        .filter(Player.game.isnot(None), Player.leader_level.isnot(None))
    )

    if active in PLAYER_ACTIVE_WINDOWS:
        cutoff = int(time.time()) - PLAYER_ACTIVE_WINDOWS[active]
        base = base.filter(Player.last_online >= cutoff)

    if query:
        needle = f"%{query}%"
        base = base.filter(
            db.or_(
                Player.username.ilike(needle),
                Player.multiplayer_name.ilike(needle),
            )
        )

    banned = _ActiveBannedUsernames()
    if banned:
        base = base.filter(~Player.username.in_(banned))

    total = base.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(page, 1), total_pages)

    if sort_query in PLAYER_LIST_SORTS:
        column = PLAYER_LIST_SORTS[sort_query]
        ordered = base.order_by(column.desc().nullslast(), Player.username.asc())
    else:
        # "Creation" order = newest rows first (physical insert order).
        order = db.text("ctid DESC") if IsPostgres() else db.text("rowid DESC")
        ordered = base.order_by(order)

    rows = ordered.limit(per_page).offset((page - 1) * per_page).all()

    # Resolve a display name from the save for page rows missing one.
    missing = [row.username for row in rows if not row.multiplayer_name]
    fallback = {}
    if missing:
        for username, game in (
            db.session.query(Player.username, Player.game)
            .filter(Player.username.in_(missing))
            .all()
        ):
            if game:
                name = GetNameFromSave(game)
                if name:
                    fallback[username] = name

    players = []
    for row in rows:
        last_online = row.last_online
        if last_online:
            try:
                last_online = datetime.fromtimestamp(
                    int(last_online), tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S UTC")
            except (ValueError, TypeError, OSError):
                last_online = str(last_online)
        players.append(
            {
                "username": row.username,
                "multiplayer_name": row.multiplayer_name
                or fallback.get(row.username)
                or "Unnamed Player",
                "leader_level": row.leader_level,
                "last_online": last_online or "",
            }
        )

    return {
        "players": players,
        "player_count": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "start_index": (page - 1) * per_page + 1 if total else 0,
        "end_index": min(page * per_page, total),
    }


_TOPPVP_CACHE = {"at": 0.0, "entries": None}
_TOPPVP_CACHE_TTL = 300  # seconds
_TOPPVP_LOCK = threading.Lock()


def _ComputeTopPvpEntries():
    """Decrypt every save once to rank players by Multiplayer Level.

    This is expensive, so callers should use ``GetTopPvpEntries`` (cached).
    Rows are streamed to avoid holding every save in memory at once.
    """
    banned = _ActiveBannedUsernames()

    rows = (
        db.session.query(
            Player.username,
            Player.multiplayer_name,
            Player.leader_level,
            Player.last_online,
            Player.game,
        )
        .filter(Player.game.isnot(None))
        .yield_per(500)
    )

    entries = []
    for username, name, leader_level, last_online, game in rows:
        if not game or game in (b"", b" "):
            continue
        try:
            data = DecryptGameData(game)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        if last_online is not None:
            try:
                last_online = datetime.fromtimestamp(
                    last_online, tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S UTC")
            except (ValueError, TypeError, OSError):
                last_online = str(last_online)

        multiplayer_level = safe_int(data.get("MultiplayerLevel", 0))
        entries.append(
            {
                "username": username,
                "multiplayer_name": name
                or data.get("MultiplayerPlayerName")
                or "Unnamed Player",
                "multiplayer_level": multiplayer_level,
                "pvp_rank_name": GetPvpRankName(multiplayer_level),
                "leader_level": safe_int(leader_level, 0),
                "best_multiplayer_level": safe_int(
                    data.get("BestMultiplayerLevel", 0)
                ),
                "rank_xp": safe_int(data.get("RankXP", 0)),
                "is_banned": username in banned,
                "last_online": last_online,
            }
        )

    # Lower MultiplayerLevel = better PVP rank (1 = Super Amadeus, 25 = Dweeb).
    entries.sort(
        key=lambda e: (e["multiplayer_level"] if e["multiplayer_level"] > 0 else 999)
    )
    for index, entry in enumerate(entries):
        entry["ranking"] = index + 1

    return entries


def GetTopPvpEntries(force=False):
    """Return the cached Top PVP ranking, recomputing when stale or forced."""
    now = time.time()
    with _TOPPVP_LOCK:
        if (
            not force
            and _TOPPVP_CACHE["entries"] is not None
            and (now - _TOPPVP_CACHE["at"]) < _TOPPVP_CACHE_TTL
        ):
            return _TOPPVP_CACHE["entries"]

    entries = _ComputeTopPvpEntries()
    with _TOPPVP_LOCK:
        _TOPPVP_CACHE["entries"] = entries
        _TOPPVP_CACHE["at"] = time.time()
    return entries


@admin_bp.route("/admin/top_pvp")
@login_required
def AdminTopPvp():
    if not isAdmin(current_user):
        return abort(404)

    force = request.args.get("refresh") == "1"
    entries = GetTopPvpEntries(force=force)

    cache_age = int(time.time() - _TOPPVP_CACHE["at"]) if _TOPPVP_CACHE["at"] else 0

    return render_template(
        "admin_top_pvp.html",
        players=entries[:50],
        total_players=len(entries),
        cache_age=cache_age,
        cache_ttl=_TOPPVP_CACHE_TTL,
    )


@admin_bp.route("/admin/players/<player>")
@login_required
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

    Friends, FriendRequests = BuildFriendsView(player)

    trade_row = TradeCoinBalance.query.filter_by(player_id=player["username"]).first()
    TradeCoins = int(trade_row.coins) if trade_row else 0

    google_link = AccountLink.query.filter_by(provider="google", username=player["username"]).first()
    GoogleEmail = None if google_link is None else (google_link.email or "(linked, no email)")

    if game is None:
        return render_template(
            "admin_player.html",
            player=player,
            is_banned=IsUserBanned(player["username"]),
            Friends=Friends,
            FriendRequests=FriendRequests,
            save_issues=[
                "Game save could not be decrypted. Use Import JSON to restore it."
            ],
            SoftCurrency=0,
            HardCurrency=0,
            PvpCurrency=0,
            EvolutionShards=0,
            CraftCurrency=0,
            TradeCoins=TradeCoins,
            GoogleEmail=GoogleEmail,
            InstalledDate="N/A",
            PVPBanned=False,
            MultiplayerLevel=0,
            InventorySpace=0,
            RankXP=0,
            BattleHistory=[],
            DeviceName=player["devicename"],
            Inventory=[],
            CardCollection=[],
            CardInventory=[],
            Leaders=[],
            leader_skins={},
            Loadouts=[],
            SelectedLoadout=0,
            CreatureByUid={},
            MaxLoadouts=MAX_LOADOUTS,
            DefaultLoadoutCount=DEFAULT_LOADOUT_COUNT,
            TeamSlots=[],
            TeamCreatureCount=DEFAULT_TEAM_CREATURES,
            MaxTeamCreatures=MAX_TEAM_CREATURES,
            BannedBattleCount=0,
            TeamBans=[],
            BannedCreatures=set(),
            BannedLeaders=set(),
            HelperCreature=None,
            invalid_creature_count=0,
            gift_catalog=GetGiftCatalog(),
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

    # Opponent loadout per match + PVP ban screening. BattleHistory only
    # stores the opponent's side (opponentLeader + creatures).
    banlist = GetPvpBanlist()
    banned_creature_set = set(banlist.get("banned_creatures") or [])
    banned_leader_set = set(banlist.get("banned_leaders") or [])

    battle_history = [
        DescribeBattleRecord(b, banned_creature_set, banned_leader_set)
        for b in battle_history
    ]
    battle_history = [b for b in battle_history if b is not None]
    banned_battle_count = sum(1 for b in battle_history if b.get("has_ban"))

    # fix device name
    if player["devicename"] is not None:
        player["devicename"] = re.sub(
            r"%[0-9A-Fa-f]{2}",
            lambda m: chr(int(m.group(0)[1:], 16)),
            player["devicename"],
        )

    raw_inventory = game.get("Inventory", [])
    if not isinstance(raw_inventory, list):
        raw_inventory = []

    # creatures vs individual action-card copies
    Inventory = [
        item
        for item in raw_inventory
        if isinstance(item, dict) and item.get("_T") == "CR"
    ]
    CardInventory = [
        item
        for item in raw_inventory
        if isinstance(item, dict) and item.get("_T") == "CA"
    ]

    # Friendly display names for inventory rows (creatures, Auguments, heroes)
    creature_names = GetCreatureNameMap()
    card_names = GetActionCardNameMap()
    for item in Inventory:
        item["Name"] = creature_names.get(item.get("ID"), "")
    for item in CardInventory:
        item["Name"] = card_names.get(item.get("ID"), "")

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
    effective_rank = max(
        player.get("leader_level") or 0, game_saved_lvl, game_xp_lvl, admin_lvl
    )
    if effective_rank > (player.get("leader_level") or 0):
        player["leader_level"] = effective_rank

    card_collection = game.get("CardCollection", [])
    if not isinstance(card_collection, list):
        card_collection = []
    leaders = game.get("Leaders", [])
    if not isinstance(leaders, list):
        leaders = []

    loadouts = game.get("Loadouts", [])
    if not isinstance(loadouts, list):
        loadouts = []
    loadouts = [lo if isinstance(lo, dict) else {} for lo in loadouts]

    try:
        selected_loadout = int(game.get("SelectedLoadout", 0) or 0)
    except (TypeError, ValueError):
        selected_loadout = 0

    # Creature slots per team. Teams already in this save may carry more
    # slots than the global CreaturesOnTeam default, so the widest team wins.
    team_creature_count = max((LoadoutCreatureCount(lo) for lo in loadouts), default=0)
    if not team_creature_count:
        team_creature_count = max(
            1,
            min(
                MAX_TEAM_CREATURES,
                safe_int(ReadMiscParam("CreaturesOnTeam"), DEFAULT_TEAM_CREATURES),
            ),
        )

    team_slots = []
    for loadout in loadouts:
        width = max(LoadoutCreatureCount(loadout), team_creature_count)
        team_slots.append(
            [loadout.get("CreatureID" + str(index)) for index in range(width)]
        )

    # UniqueID -> creature blueprint ID so team rows can show creature names
    creature_by_uid = {}
    for item in Inventory:
        if item.get("_T") == "CR" and item.get("UniqueID") is not None:
            creature_by_uid[safe_int(item.get("UniqueID"), 0)] = item.get("ID", "")

    # Per-hero list of skins the player does not own yet (for the Add Skin picker)
    leader_skins = {}
    for leader in leaders:
        if not isinstance(leader, dict):
            continue
        base_id = leader.get("ID")
        if not base_id:
            continue
        owned = leader.get("OwnedSkins")
        if not isinstance(owned, list):
            owned = []
        leader_skins[base_id] = [
            skin for skin in GetLeaderSkins(base_id) if skin not in owned
        ]

    # Friendly hero names for the Leaders table and helper creature card
    leader_names = GetLeaderNameMap()
    for leader in leaders:
        if isinstance(leader, dict):
            leader["Name"] = leader_names.get(leader.get("ID"), "")
    if isinstance(helper_creature, dict):
        helper_creature["Name"] = creature_names.get(helper_creature.get("ID"), "")

    # This player's current teams screened against the PVP ban list
    team_bans = []
    for index, slots in enumerate(team_slots):
        loadout = loadouts[index]
        leader_id = loadout.get("LeaderID") or ""
        banned_here = []
        for uid in slots:
            if not uid:
                continue
            creature_id = creature_by_uid.get(safe_int(uid, 0))
            if creature_id and creature_id in banned_creature_set:
                banned_here.append(creature_id)
        if banned_here or (leader_id and leader_id in banned_leader_set):
            team_bans.append(
                {
                    "index": index + 1,
                    "leader": leader_id,
                    "leader_banned": bool(leader_id) and leader_id in banned_leader_set,
                    "creatures": banned_here,
                }
            )

    return render_template(
        "admin_player.html",
        player=player,
        is_banned=IsUserBanned(player["username"]),
        Friends=Friends,
        FriendRequests=FriendRequests,
        save_issues=save_issues,
        SoftCurrency=game.get("SoftCurrency", 0),
        HardCurrency=int(game.get("PaidHardCurrency", 0))
        + int(game.get("FreeHardCurrency", 0)),
        PvpCurrency=game.get("PvpCurrency", 0),
        EvolutionShards=game.get("EvolutionShards", 0),
        CraftCurrency=game.get("CraftCurrency", 0),
        TradeCoins=TradeCoins,
        GoogleEmail=GoogleEmail,
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
        CardInventory=CardInventory,
        Leaders=leaders,
        leader_skins=leader_skins,
        Loadouts=loadouts,
        SelectedLoadout=selected_loadout,
        CreatureByUid=creature_by_uid,
        MaxLoadouts=MAX_LOADOUTS,
        DefaultLoadoutCount=DEFAULT_LOADOUT_COUNT,
        TeamSlots=team_slots,
        TeamCreatureCount=team_creature_count,
        MaxTeamCreatures=MAX_TEAM_CREATURES,
        BannedBattleCount=banned_battle_count,
        TeamBans=team_bans,
        BannedCreatureCount=len(banned_creature_set),
        BannedLeaderCount=len(banned_leader_set),
        BannedCreatures=banned_creature_set,
        BannedLeaders=banned_leader_set,
        HelperCreature=helper_creature,
        invalid_creature_count=invalid_creature_count,
        gift_catalog=GetGiftCatalog(),
        rank_xp_json=json.dumps(GetRankXPTable()),
    )


@admin_bp.route("/admin/players/<player>/game")
@login_required
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


@admin_bp.route("/admin/players/<player>/game/edit", methods=["POST"])
@login_required
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
            safe_int(game_json.get("AdminLeaderLevel", 0)),
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


@admin_bp.route("/admin/players/<player>/edit", methods=["POST"])
@login_required
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
        game["SoftCurrency"] = safe_int(
            request.form["SoftCurrency"], game.get("SoftCurrency", 0)
        )
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
        game["PvpCurrency"] = safe_int(
            request.form["PvpCurrency"], game.get("PvpCurrency", 0)
        )
    if "InventorySpace" in request.form:
        game["InventorySpace"] = safe_int(
            request.form["InventorySpace"], game.get("InventorySpace", 0)
        )
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
            request.form["PointsInMultiplayerLevel"],
            game.get("PointsInMultiplayerLevel", 0),
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

    new_leader_level = (
        safe_int(request.form.get("leader_level"), old_leader_level)
        if "leader_level" in request.form
        else old_leader_level
    )
    new_level = (
        safe_int(request.form.get("level"), old_level)
        if "level" in request.form
        else old_level
    )
    submitted_rank_xp = (
        safe_int(request.form.get("RankXP"), old_rank_xp)
        if "RankXP" in request.form
        else old_rank_xp
    )

    # Determine desired target rank and XP
    if new_leader_level != old_leader_level:
        # Admin explicitly changed Rank (leader_level)
        target_rank = new_leader_level
        required_xp = GetXPForRank(target_rank)
        if target_rank < old_leader_level:
            # Demotion: reset XP to the required XP for the lower rank unless submitted XP is valid for it
            if (
                submitted_rank_xp >= GetXPForRank(target_rank + 1)
                or submitted_rank_xp < required_xp
            ):
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
        game["EvolutionShards"] = safe_int(
            request.form["EvolutionShards"], game.get("EvolutionShards", 0)
        )
    if "CraftCurrency" in request.form:
        game["CraftCurrency"] = safe_int(
            request.form["CraftCurrency"], game.get("CraftCurrency", 0)
        )
    if "TradeCoins" in request.form:
        coins = max(0, safe_int(request.form["TradeCoins"], 0))
        bal = TradeCoinBalance.query.filter_by(player_id=player).first()
        if bal is None:
            db.session.add(TradeCoinBalance(player_id=player, coins=coins, updated=int(time.time())))
        else:
            bal.coins = coins
            bal.updated = int(time.time())
    if "Zxcvbnm" in request.form:
        game["Zxcvbnm"] = 1
    else:
        game["Zxcvbnm"] = 0

    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log("admin", current_user.username + " edited resources for player: " + player)
    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/gift", methods=["POST"])
@login_required
def AdminPlayerGift(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    gift_type = request.form.get("gift_type", "").strip()
    gift_id = request.form.get("gift_id", "").strip()
    gift_amount = safe_int(request.form.get("gift_amount", 1), 1)
    gift_title = request.form.get("gift_title", "").strip()
    gift_body = request.form.get("gift_body", "").strip()

    if gift_type == "Creature" and IsTutorialOnlyCreature(gift_id):
        return make_response(
            "This is a tutorial-only creature and cannot be gifted.", 400
        )

    # Mailable rewards ride the client's db_NewsMail blueprint (per PlayerID).
    if gift_type in GIFT_MAIL_TYPES:
        ok, result = AddNewsMailGift(
            player, gift_type, gift_id, gift_amount, gift_title, gift_body
        )
        if not ok:
            return make_response(result, 400)
        Log(
            "admin",
            current_user.username
            + f" mailed a {gift_type} gift ({gift_id or 'currency'}) to player: "
            + player,
        )
        return redirect("/admin/players/" + player)

    # Heroes / Auguments / Evolution Shards cannot travel by mail, so they are
    # granted directly and a reward-less notice is left in the post office.
    if gift_type in GIFT_DIRECT_TYPES:
        if gift_type == "Leader":
            if not gift_id:
                return make_response("A hero ID is required!", 400)
            leaders = game.get("Leaders", [])
            if not isinstance(leaders, list):
                leaders = []
            by_id = {l.get("ID"): l for l in leaders if isinstance(l, dict)}
            base_id = GetLeaderSkinBase(gift_id)
            if base_id:
                base_entry = by_id.get(base_id)
                if base_entry is None:
                    base_entry = {"ID": base_id, "Skin": base_id, "OwnedSkins": []}
                    leaders.append(base_entry)
                owned = base_entry.get("OwnedSkins")
                if not isinstance(owned, list):
                    owned = []
                    base_entry["OwnedSkins"] = owned
                if gift_id not in owned:
                    owned.append(gift_id)
                game["Leaders"] = leaders
                desc = f"hero skin {gift_id}"
            elif gift_id not in by_id:
                leaders.append({"ID": gift_id, "Skin": gift_id, "OwnedSkins": []})
                game["Leaders"] = leaders
                desc = f"hero {gift_id}"
            else:
                desc = f"hero {gift_id} (already owned)"
        else:
            ok, desc = ApplyRedeemReward(game, gift_type, gift_amount, gift_id)
            if not ok:
                return make_response(desc, 400)

        StripLegacyAdminMails(game)
        db_player.game = EncryptGameData(game, player)
        db.session.commit()

        AddNewsMailNotice(
            player,
            gift_title,
            gift_body or f"An admin gift was added to your account: {desc}.",
        )
        Log(
            "admin",
            current_user.username
            + f" granted a {gift_type} gift ({gift_id or 'currency'}) to player: "
            + player,
        )
        return redirect("/admin/players/" + player)

    return make_response("Unsupported reward type!", 400)


@admin_bp.route("/admin/players/<player>/add_creature", methods=["POST"])
@login_required
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
    count = safe_int(request.form.get("count", 1), 1)
    count = max(1, min(10, count))

    if not creature_id:
        return make_response("Creature ID is required!", 400)
    if IsTutorialOnlyCreature(creature_id):
        return make_response(
            "This is a tutorial-only creature and cannot be added to a player.", 400
        )

    inventory = game.get("Inventory")
    if not isinstance(inventory, list):
        inventory = []
    next_uid = (
        max(
            [
                i.get("UniqueID", 0)
                for i in inventory
                if isinstance(i, dict) and i.get("_T") == "CR"
            ],
            default=0,
        )
        + 1
    )

    for _ in range(count):
        inventory.append(
            {
                "_T": "CR",
                "ID": creature_id,
                "UniqueID": next_uid,
                "Xp": creature_xp,
                "Favorite": 0,
                "Passive": 1,
                "PassiveFeeds": 0,
                "StarRating": creature_stars,
            }
        )
        next_uid += 1

    game["Inventory"] = inventory

    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log(
        "admin",
        current_user.username + f" added {count} x {creature_id} to player: " + player,
    )
    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/delete_creature/<int:index>", methods=["POST"])
@login_required
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


@admin_bp.route("/admin/players/<player>/delete_all_creatures", methods=["POST"])
@login_required
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

    Log(
        "admin",
        current_user.username
        + f" deleted all ({initial_count}) creatures from player: "
        + player,
    )
    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/delete_creatures_bulk", methods=["POST"])
@login_required
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

    Log(
        "admin",
        current_user.username
        + f" bulk deleted {len(to_delete)} creatures from player: "
        + player,
    )
    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/max_creature/<int:index>", methods=["POST"])
@login_required
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
            return make_response(
                "This is a tutorial-only creature and cannot be modified.", 400
            )
        creatures[index]["StarRating"] = 5
        creatures[index]["Xp"] = 70325
        db_player.game = EncryptGameData(game, player)
        db.session.commit()
        Log(
            "admin",
            current_user.username
            + f" maxed creature index {index} for player: "
            + player,
        )

    return redirect("/admin/players/" + player)


@admin_bp.route(
    "/admin/players/<player>/downgrade_creature/<int:index>", methods=["POST"]
)
@login_required
def AdminPlayerDowngradeCreature(player, index):
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
        creatures[index]["StarRating"] = 1
        creatures[index]["Xp"] = 0
        db_player.game = EncryptGameData(game, player)
        db.session.commit()
        Log(
            "admin",
            current_user.username
            + f" downgraded creature index {index} for player: "
            + player,
        )

    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/add_card", methods=["POST"])
@login_required
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
    count = safe_int(request.form.get("count", 1), 1)
    count = max(1, min(10, count))
    if not card_id:
        return make_response("Card ID is required!", 400)

    card_collection = game.get("CardCollection")
    if not isinstance(card_collection, list):
        card_collection = []
    if card_id not in {c.get("ID") for c in card_collection if isinstance(c, dict)}:
        card_collection.append({"ID": card_id, "Stat": 1})

    inventory = game.get("Inventory")
    if not isinstance(inventory, list):
        inventory = []
    next_uid = (
        max(
            [item.get("UniqueID", 0) for item in inventory if isinstance(item, dict)],
            default=0,
        )
        + 1
    )

    for _ in range(count):
        inventory.append(
            {
                "_T": "CA",
                "ID": card_id,
                "UniqueID": next_uid,
                "Favorite": 0,
                "CreatureUID": -1,
                "CreatureSlot": 0,
            }
        )
        next_uid += 1

    game["CardCollection"] = card_collection
    game["Inventory"] = inventory

    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log(
        "admin",
        current_user.username + f" added {count} x card {card_id} to player: " + player,
    )
    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/add_card_copy/<int:index>", methods=["POST"])
@login_required
def AdminPlayerAddCardCopy(player, index):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    inventory = game.get("Inventory", [])
    if not isinstance(inventory, list):
        inventory = []
    cards = [
        item for item in inventory if isinstance(item, dict) and item.get("_T") == "CA"
    ]

    if not (0 <= index < len(cards)):
        return redirect("/admin/players/" + player)

    card_id = cards[index].get("ID")
    if not card_id:
        return redirect("/admin/players/" + player)

    card_collection = game.get("CardCollection")
    if not isinstance(card_collection, list):
        card_collection = []
    if card_id not in {c.get("ID") for c in card_collection if isinstance(c, dict)}:
        card_collection.append({"ID": card_id, "Stat": 1})
    game["CardCollection"] = card_collection

    next_uid = (
        max(
            [item.get("UniqueID", 0) for item in inventory if isinstance(item, dict)],
            default=0,
        )
        + 1
    )
    inventory.append(
        {
            "_T": "CA",
            "ID": card_id,
            "UniqueID": next_uid,
            "Favorite": 0,
            "CreatureUID": -1,
            "CreatureSlot": 0,
        }
    )
    game["Inventory"] = inventory

    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log(
        "admin",
        current_user.username
        + f" added a copy of card {card_id} for player: "
        + player,
    )
    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/delete_card/<int:index>", methods=["POST"])
@login_required
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


@admin_bp.route("/admin/players/<player>/delete_all_cards", methods=["POST"])
@login_required
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
    # Also remove Auguments from inventory
    inventory = game.get("Inventory", [])
    game["Inventory"] = [item for item in inventory if item.get("_T") != "CA"]

    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log(
        "admin",
        current_user.username
        + f" deleted all ({initial_count}) Auguments from player: "
        + player,
    )
    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/delete_cards_bulk", methods=["POST"])
@login_required
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
    game["Inventory"] = [
        item
        for item in inventory
        if not (item.get("_T") == "CA" and item.get("ID") in deleted_ids)
    ]

    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log(
        "admin",
        current_user.username
        + f" bulk deleted {len(to_delete)} cards from player: "
        + player,
    )
    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/add_all_creatures", methods=["POST"])
@login_required
def AdminPlayerAddAllCreatures(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    with open(
        os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Creatures.json"), "r"
    ) as f:
        all_creatures = json.load(f)

    tutorial_ids = GetTutorialOnlyCreatureIds()

    existing_ids = set()
    inventory = game.get("Inventory", [])
    for item in inventory:
        if item.get("_T") == "CR":
            existing_ids.add(item.get("ID"))

    next_uid = (
        max(
            [item.get("UniqueID", 0) for item in inventory if item.get("_T") == "CR"],
            default=0,
        )
        + 1
    )
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
            default_cards = [creature.get(f"ActionCard{i}", "") for i in range(1, 6)]
            default_cards = [c for c in default_cards if c][:card_slots]
            if default_cards:
                new_creature["Cards"] = default_cards

            inventory.append(new_creature)
            next_uid += 1
            added += 1

    game["Inventory"] = inventory
    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log(
        "admin",
        current_user.username + f" added {added} creatures to player: " + player,
    )
    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/max_all_creatures", methods=["POST"])
@login_required
def AdminPlayerMaxAllCreatures(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    with open(
        os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Creatures.json"), "r"
    ) as f:
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

    Log(
        "admin",
        current_user.username + f" maxed {count} creatures for player: " + player,
    )
    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/remove_invalid_creatures", methods=["POST"])
@login_required
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


@admin_bp.route("/admin/players/<player>/add_max_creature", methods=["POST"])
@login_required
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
        return make_response(
            "This is a tutorial-only creature and cannot be added to a player.", 400
        )

    inventory = game.get("Inventory", [])
    next_uid = (
        max(
            [item.get("UniqueID", 0) for item in inventory if item.get("_T") == "CR"],
            default=0,
        )
        + 1
    )

    inventory.append(
        {
            "_T": "CR",
            "ID": creature_id,
            "UniqueID": next_uid,
            "Xp": 70325,
            "Favorite": 0,
            "Passive": 1,
            "PassiveFeeds": 0,
            "StarRating": 5,
        }
    )

    game["Inventory"] = inventory
    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log(
        "admin",
        current_user.username
        + f" added max creature {creature_id} to player: "
        + player,
    )
    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/add_all_cards", methods=["POST"])
@login_required
def AdminPlayerAddAllCards(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    with open(
        os.path.join(ROOT_DIR, "data/persist/Blueprints/db_ActionCards.json"), "r"
    ) as f:
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
            inventory.append(
                {
                    "_T": "CA",
                    "ID": cid,
                    "UniqueID": next_uid,
                    "Favorite": 0,
                    "CreatureUID": -1,
                    "CreatureSlot": 0,
                }
            )
            next_uid += 1
            added += 1

    game["CardCollection"] = cards
    game["Inventory"] = inventory
    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log(
        "admin",
        current_user.username + f" added {added} Auguments to player: " + player,
    )
    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/add_all_leaders", methods=["POST"])
@login_required
def AdminPlayerAddAllLeaders(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    with open(
        os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Leaders.json"), "r"
    ) as f:
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


@admin_bp.route("/admin/players/<player>/add_leader", methods=["POST"])
@login_required
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
        Log(
            "admin",
            current_user.username + f" added leader {leader_id} to player: " + player,
        )

    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/add_all_skins", methods=["POST"])
@login_required
def AdminPlayerAddAllSkins(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    with open(
        os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Leaders.json"), "r"
    ) as f:
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


@admin_bp.route("/admin/players/<player>/delete_leader/<int:index>", methods=["POST"])
@login_required
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
        Log(
            "admin",
            current_user.username
            + f" deleted leader {removed.get('ID')} from player: "
            + player,
        )

    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/delete_all_leaders", methods=["POST"])
@login_required
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

    Log(
        "admin",
        current_user.username
        + f" deleted all ({initial_count}) leaders from player: "
        + player,
    )
    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/delete_leaders_bulk", methods=["POST"])
@login_required
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

    Log(
        "admin",
        current_user.username
        + f" bulk deleted {len(to_delete)} leaders from player: "
        + player,
    )
    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/max_resources", methods=["POST"])
@login_required
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


@admin_bp.route("/admin/players/<player>/loadouts/set", methods=["POST"])
@login_required
def AdminPlayerSetLoadouts(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    before = game.get("Loadouts")
    before = len(before) if isinstance(before, list) else 0

    count = request.form.get("preset") or request.form.get("count")
    count = SetLoadoutCount(game, count)
    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log(
        "admin",
        current_user.username
        + f" set team count for player: {player} ({before} -> {count})",
    )
    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/loadouts/creatures", methods=["POST"])
@login_required
def AdminPlayerSetTeamCreatures(player):
    if not isAdmin(current_user):
        return abort(404)

    db_player = Player.query.filter_by(username=player).first()
    if db_player is None:
        return make_response("No player found!", 404)

    game = DecryptGameData(db_player.game)
    if game is None:
        return make_response("No game data found!", 400)

    loadouts = game.get("Loadouts")
    if not isinstance(loadouts, list):
        loadouts = []
    before = max((LoadoutCreatureCount(lo) for lo in loadouts), default=0)

    count = SetTeamCreatureCount(game, request.form.get("count"))
    db_player.game = EncryptGameData(game, player)
    db.session.commit()

    Log(
        "admin",
        current_user.username
        + f" set creatures per team for player: {player} ({before} -> {count})",
    )
    return redirect("/admin/players/" + player)


@admin_bp.route("/admin/players/<player>/export_save", methods=["GET"])
@login_required
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
        headers={
            "Content-Disposition": f"attachment;filename=player_{player}_save.json"
        },
    )
    return response


@admin_bp.route("/admin/players/<player>/import_save", methods=["POST"])
@login_required
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
        safe_int(parsed.get("AdminLeaderLevel", 0)),
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


@admin_bp.route("/admin/players/<player>/fix_save", methods=["POST"])
@login_required
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


@admin_bp.route("/admin/players/<player>/transfer_progress", methods=["POST"])
@login_required
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
        current_user.username
        + " transferred progress from "
        + player
        + " to "
        + target_uuid,
    )
    DiscordWebhookMessage(
        current_user.username
        + " transferred progress from "
        + player
        + " to "
        + target_uuid
    )
    return redirect("/admin/players/" + target.username)


@admin_bp.route("/admin/players/<player>/reset_save", methods=["POST"])
@login_required
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


@admin_bp.route("/admin/players/<player>/delete", methods=["POST"])
@login_required
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


@admin_bp.route("/admin/players/bulk_action", methods=["POST"])
@login_required
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
        Log(
            "admin", current_user.username + f" bulk unbanned {len(player_ids)} players"
        )
    elif action == "delete":
        for pid in player_ids:
            Player.query.filter_by(username=pid).delete()
            Bans.query.filter_by(username=pid).delete()
        db.session.commit()
        Log("admin", current_user.username + f" bulk deleted {len(player_ids)} players")

    return redirect("/admin/players")


@admin_bp.route("/admin/players/<player>/<action>", methods=["GET", "POST"])
@login_required
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
    elif action == "googleunlink":
        # The player lost that Google account; the game then asks them to link a
        # new one (linking again pays no gems - the reward is once per player).
        link = AccountLink.query.filter_by(provider="google", username=player).first()
        if link is not None:
            db.session.delete(link)
            db.session.commit()
    else:
        return make_response("Invalid action!", 400)

    DiscordWebhookMessage(
        current_user.username + " performed " + action + " on ID: " + player
    )
    return redirect("/admin/players/" + player)
