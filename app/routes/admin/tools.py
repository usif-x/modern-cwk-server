from ._common import *


@admin_bp.route("/admin/misc")
@login_required
def AdminMisc():
    if not isAdmin(current_user):
        return abort(404)

    try:
        starting_loadouts = int(safe_int(ReadMiscParam("StartingLoadoutCount"), 5))
    except (TypeError, ValueError):
        starting_loadouts = DEFAULT_LOADOUT_COUNT

    try:
        creatures_on_team = int(
            safe_int(ReadMiscParam("CreaturesOnTeam"), DEFAULT_TEAM_CREATURES)
        )
    except (TypeError, ValueError):
        creatures_on_team = DEFAULT_TEAM_CREATURES
    creatures_on_team = max(1, min(MAX_TEAM_CREATURES, creatures_on_team))

    return render_template(
        "admin_misc.html",
        starting_loadouts=starting_loadouts,
        max_loadouts=MAX_LOADOUTS,
        default_loadouts=DEFAULT_LOADOUT_COUNT,
        creatures_on_team=creatures_on_team,
        max_team_creatures=MAX_TEAM_CREATURES,
        default_team_creatures=DEFAULT_TEAM_CREATURES,
    )


@admin_bp.route("/admin/misc/loadout_count", methods=["POST"])
@login_required
def AdminMiscLoadoutCount():
    if not isAdmin(current_user):
        return abort(404)

    raw = request.form.get("preset") or request.form.get("count")
    try:
        count = int(raw)
    except (TypeError, ValueError):
        count = DEFAULT_LOADOUT_COUNT
    count = max(1, min(MAX_LOADOUTS, count))

    old_value = WriteMiscParam("StartingLoadoutCount", count)

    Log(
        "admin",
        current_user.username
        + f" set blueprint StartingLoadoutCount: {old_value} -> {count}",
    )
    DiscordWebhookMessage(
        f"**{current_user.username}** set `StartingLoadoutCount` to **{count}** (was {old_value})"
    )
    return redirect("/admin/misc")


@admin_bp.route("/admin/misc/creatures_on_team", methods=["POST"])
@login_required
def AdminMiscCreaturesOnTeam():
    if not isAdmin(current_user):
        return abort(404)

    raw = request.form.get("preset") or request.form.get("count")
    try:
        count = int(raw)
    except (TypeError, ValueError):
        count = DEFAULT_TEAM_CREATURES
    count = max(1, min(MAX_TEAM_CREATURES, count))

    old_value = WriteMiscParam("CreaturesOnTeam", count)

    Log(
        "admin",
        current_user.username
        + f" set blueprint CreaturesOnTeam: {old_value} -> {count}",
    )
    DiscordWebhookMessage(
        f"**{current_user.username}** set `CreaturesOnTeam` to **{count}** (was {old_value})"
    )
    return redirect("/admin/misc")


@admin_bp.route("/admin/redeemcodes")
@login_required
def AdminRedeemCodes():
    if not isAdmin(current_user):
        return abort(404)

    codes = [
        {
            "code": db_code.code,
            "enabled": db_code.enabled,
            "created_by": db_code.created_by,
            "rewards": ParseRedeemRewards(db_code),
        }
        for db_code in RedeemCode.query.order_by(RedeemCode.code).all()
    ]

    creatures = []
    cards = []
    leaders = []
    try:
        with open(
            os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Creatures.json"), "r"
        ) as f:
            c_data = json.load(f)
            creatures = sorted(
                [
                    {
                        "id": c.get("ID", ""),
                        "name": FormatCreatureName(c)[0],
                    }
                    for c in c_data
                    if c.get("ID")
                ],
                key=lambda x: x["name"],
            )
    except Exception:
        pass

    try:
        with open(
            os.path.join(ROOT_DIR, "data/persist/Blueprints/db_ActionCards.json"), "r"
        ) as f:
            ac_data = json.load(f)
            cards = sorted(
                [
                    {
                        "id": c.get("ID", ""),
                        "name": FormatActionCardName(c),
                    }
                    for c in ac_data
                    if c.get("ID")
                ],
                key=lambda x: x["name"],
            )
    except Exception:
        pass

    try:
        with open(
            os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Leaders.json"), "r"
        ) as f:
            l_data = json.load(f)
            leaders = sorted(
                [
                    {
                        "id": l.get("ID", ""),
                        "name": FormatLeaderName(l),
                    }
                    for l in l_data
                    if l.get("ID")
                ],
                key=lambda x: x["name"],
            )
    except Exception:
        pass

    return render_template(
        "admin_redeemcodes.html",
        codes=codes,
        creatures=creatures,
        cards=cards,
        leaders=leaders,
    )


@admin_bp.route("/admin/redeemcodes/add", methods=["POST"])
@login_required
def AdminRedeemCodeAdd():
    if not isAdmin(current_user):
        return abort(404)

    code = request.form.get("code", "").strip().upper()
    if not code:
        return make_response("Code is required!", 400)

    raw_rewards = request.form.get("rewards_json", "").strip()
    try:
        parsed_rewards = json.loads(raw_rewards) if raw_rewards else []
    except (ValueError, TypeError):
        return make_response("Invalid rewards payload!", 400)
    if not isinstance(parsed_rewards, list) or not parsed_rewards:
        return make_response("At least one reward is required!", 400)

    rewards = []
    for entry in parsed_rewards:
        if not isinstance(entry, dict):
            continue
        reward_type = (entry.get("type") or "").strip()
        if not reward_type:
            return make_response("Each reward needs a type!", 400)
        reward_amount = safe_int(entry.get("amount", 1), 1)
        reward_item = (entry.get("item") or "").strip()

        if reward_type in ("Creature", "ActionCard", "Card", "Leader", "Hero"):
            if not reward_item:
                return make_response(
                    f"Item selection is required for {reward_type} reward!", 400
                )
            if reward_type == "Creature":
                # For creatures, reward_amount acts as star rating (1-5)
                reward_amount = min(max(reward_amount, 1), 5)
            elif reward_type in ("Leader", "Hero"):
                reward_amount = 1
            else:
                reward_amount = max(reward_amount, 1)
        else:
            if reward_amount <= 0:
                return make_response("Reward amount must be greater than 0!", 400)
            reward_item = ""

        rewards.append(
            {"type": reward_type, "amount": reward_amount, "item": reward_item}
        )

    if not rewards:
        return make_response("At least one valid reward is required!", 400)

    primary = rewards[0]
    existing = RedeemCode.query.filter_by(code=code).first()
    if existing:
        existing.reward_type = primary["type"]
        existing.reward_amount = primary["amount"]
        existing.reward_item = primary["item"] or None
        existing.rewards = json.dumps(rewards)
        existing.enabled = True
    else:
        new_code = RedeemCode(
            code=code,
            reward_type=primary["type"],
            reward_amount=primary["amount"],
            reward_item=primary["item"] or None,
            rewards=json.dumps(rewards),
            enabled=True,
            created_by=current_user.username,
        )
        db.session.add(new_code)

    db.session.commit()
    Log(
        "admin",
        current_user.username
        + f" added/updated redeem code: {code} with {len(rewards)} reward(s)",
    )
    return redirect("/admin/redeemcodes")


@admin_bp.route("/admin/redeemcodes/delete/<code>", methods=["POST"])
@login_required
def AdminRedeemCodeDelete(code):
    if not isAdmin(current_user):
        return abort(404)

    RedeemCode.query.filter_by(code=code).delete()
    db.session.commit()
    Log("admin", current_user.username + f" deleted redeem code: {code}")
    return redirect("/admin/redeemcodes")


@admin_bp.route("/admin/redeemcodes/toggle/<code>", methods=["POST"])
@login_required
def AdminRedeemCodeToggle(code):
    if not isAdmin(current_user):
        return abort(404)

    db_code = RedeemCode.query.filter_by(code=code).first()
    if db_code:
        db_code.enabled = not db_code.enabled
        db.session.commit()
    Log("admin", current_user.username + f" toggled redeem code: {code}")
    return redirect("/admin/redeemcodes")


@admin_bp.route("/admin/logs/delete/olderthan/<days>")
@login_required
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


@admin_bp.route("/admin/upsight/delete/olderthan/<days>")
@login_required
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


@admin_bp.route("/admin/logs", methods=["GET"])
@login_required
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


@admin_bp.route("/admin/upsight", methods=["GET"])
@login_required
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

    return render_template("admin_upsight.html", logs=logs, query=query)
