from ._common import *


@admin_bp.route("/admin/creatures")
def AdminCreatures():
    if not isAdmin(current_user):
        return abort(404)
    query = (request.args.get("q") or request.args.get("query") or "").strip().lower()
    with open(
        os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Creatures.json"), "r"
    ) as f:
        creatures = json.load(f)
    if query:
        creatures = [
            c
            for c in creatures
            if query in c.get("ID", "").lower() or query in c.get("Name", "").lower()
        ]
    banned_set = set(GetPvpBanlist().get("banned_creatures", []))
    return render_template(
        "admin_creatures.html",
        creatures=creatures,
        query=query,
        total=len(creatures),
        banned_set=banned_set,
    )


@admin_bp.route("/admin/cards")
def AdminCards():
    if not isAdmin(current_user):
        return abort(404)
    query = (request.args.get("q") or request.args.get("query") or "").strip().lower()
    with open(
        os.path.join(ROOT_DIR, "data/persist/Blueprints/db_ActionCards.json"), "r"
    ) as f:
        cards = json.load(f)
    if query:
        cards = [
            c
            for c in cards
            if query in c.get("ID", "").lower()
            or query in c.get("Name", "").lower()
            or query in c.get("Description", "").lower()
        ]
    return render_template(
        "admin_cards.html", cards=cards, query=query, total=len(cards)
    )


@admin_bp.route("/admin/leaders")
def AdminLeaders():
    if not isAdmin(current_user):
        return abort(404)
    query = (request.args.get("q") or request.args.get("query") or "").strip().lower()
    with open(
        os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Leaders.json"), "r"
    ) as f:
        all_leaders = json.load(f)
    # Leader Book shows base heroes only; skins live under their hero's OwnedSkins.
    leaders = [l for l in all_leaders if not l.get("SkinOf")]
    if query:
        leaders = [
            l
            for l in leaders
            if query in l.get("ID", "").lower() or query in l.get("Name", "").lower()
        ]
    banned_set = set(GetPvpBanlist().get("banned_leaders", []))
    return render_template(
        "admin_leaders.html",
        leaders=leaders,
        query=query,
        total=len(leaders),
        banned_set=banned_set,
    )


@admin_bp.route("/admin/pvp_banlist")
@login_required
def AdminPvpBanlist():
    if not isAdmin(current_user):
        return abort(404)

    banlist = GetPvpBanlist()

    creatures = []
    try:
        with open(
            os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Creatures.json"), "r"
        ) as f:
            creatures = json.load(f)
    except Exception:
        pass

    leaders = []
    try:
        with open(
            os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Leaders.json"), "r"
        ) as f:
            leaders = json.load(f)
    except Exception:
        pass

    creature_map = {
        c.get("ID"): c.get("Name", c.get("ID")) for c in creatures if "ID" in c
    }
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


@admin_bp.route("/admin/pvp_banlist/add_creature", methods=["POST"])
@login_required
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
            Log(
                "admin",
                f"{current_user.username} added creature '{creature_id}' to PVP banlist",
            )

    return redirect(return_to)


@admin_bp.route(
    "/admin/pvp_banlist/remove_creature/<path:creature_id>", methods=["POST", "GET"]
)
@login_required
def AdminPvpBanlistRemoveCreature(creature_id):
    if not isAdmin(current_user):
        return abort(404)

    return_to = (
        request.args.get("return_to")
        or request.form.get("return_to")
        or "/admin/pvp_banlist"
    )
    banlist = GetPvpBanlist()
    banned = banlist.get("banned_creatures", [])
    if creature_id in banned:
        banned.remove(creature_id)
        banlist["banned_creatures"] = banned
        SavePvpBanlist(banlist)
        Log(
            "admin",
            f"{current_user.username} removed creature '{creature_id}' from PVP banlist",
        )

    return redirect(return_to)


@admin_bp.route("/admin/pvp_banlist/add_leader", methods=["POST"])
@login_required
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
            Log(
                "admin",
                f"{current_user.username} added leader '{leader_id}' to PVP banlist",
            )

    return redirect(return_to)


@admin_bp.route(
    "/admin/pvp_banlist/remove_leader/<path:leader_id>", methods=["POST", "GET"]
)
@login_required
def AdminPvpBanlistRemoveLeader(leader_id):
    if not isAdmin(current_user):
        return abort(404)

    return_to = (
        request.args.get("return_to")
        or request.form.get("return_to")
        or "/admin/pvp_banlist"
    )
    banlist = GetPvpBanlist()
    banned = banlist.get("banned_leaders", [])
    if leader_id in banned:
        banned.remove(leader_id)
        banlist["banned_leaders"] = banned
        SavePvpBanlist(banlist)
        Log(
            "admin",
            f"{current_user.username} removed leader '{leader_id}' from PVP banlist",
        )

    return redirect(return_to)


@admin_bp.route("/admin/pvp_banlist/edit_raw", methods=["POST"])
@login_required
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
