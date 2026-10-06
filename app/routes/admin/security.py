from ._common import *


@admin_bp.route("/admin/ipban/<ip>/unban")
@login_required
def AdminIPBan(ip):
    if not isAdmin(current_user):
        return abort(404)

    Log("admin", current_user.username + " performed unban on " + ip)

    player_check = Bans.query.filter_by(username=ip).first()
    db.session.delete(player_check)
    db.session.commit()

    DiscordWebhookMessage(current_user.username + " performed unban on IP: " + ip)
    return redirect("/admin/bannedips")


@admin_bp.route("/admin/ipban", methods=["POST"])
@login_required
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


@admin_bp.route("/admin/bannedplayers")
@login_required
def AdminBannedPlayers():
    if not isAdmin(current_user):
        return abort(404)

    # purge bans that have already expired
    now = int(time.time())
    Bans.query.filter(
        Bans.bantype == "userid",
        Bans.expires.isnot(None),
        Bans.expires != 0,
        Bans.expires <= now,
    ).delete(synchronize_session=False)
    db.session.commit()

    bans = Bans.query.filter_by(bantype="userid").all()
    bans = [ban.as_dict() for ban in bans]

    # get player name
    for ban in bans:
        player = Player.query.filter_by(username=ban["username"]).first()
        ban["multiplayer_name"] = (
            player.multiplayer_name if player else "Unnamed Player"
        )
        if ban["multiplayer_name"] is None and player is not None:
            ban["multiplayer_name"] = GetNameFromSave(player.game)
        if ban["time"] is not None:
            ban["time"] = datetime.fromtimestamp(ban["time"], tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
        ban["expires_display"] = FormatBanExpiry(ban.get("expires"))
        ban["is_permanent"] = ban.get("expires") in (None, 0)

    return render_template("admin_bannedplayers.html", bans=bans)


@admin_bp.route("/admin/bannedips")
@login_required
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


@admin_bp.route("/admin/maintenance")
@login_required
def AdminMaintenance():
    if not isAdmin(current_user):
        return abort(404)

    live_status = LoadLiveStatus()
    return render_template(
        "admin_maintenance.html",
        maintenance=maintenance,
        live_status_json=json.dumps(live_status, indent=2, ensure_ascii=False),
    )


@admin_bp.route("/admin/maintenance/live", methods=["POST"])
@login_required
def AdminLiveStatusSave():
    if not isAdmin(current_user):
        return abort(404)

    raw = request.form.get("live_status_json", "").strip()
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Live status must be a JSON object")
        SaveLiveStatus(parsed)
        Log("admin", current_user.username + " updated the live status config")
    except (ValueError, TypeError) as e:
        Log("admin", f"Failed to save live status JSON: {e}")

    return redirect("/admin/maintenance")


@admin_bp.route("/admin/maintenance/<action>")
@login_required
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
