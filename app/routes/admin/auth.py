from ._common import *


@admin_bp.route("/admin", methods=["GET", "POST"], strict_slashes=False)
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
        return redirect(SafeLoginNext(request.args.get("next")))


@admin_bp.route("/admin/home")
@login_required
def AdminHome():
    if not isAdmin(current_user):
        return abort(404)

    adminActivity = AdminActivity.query.order_by(AdminActivity.time).all()

    # reverse list
    adminActivity.reverse()

    total_players = Player.query.filter(
        Player.game.isnot(None), Player.leader_level.isnot(None)
    ).count()
    total_banned = Bans.query.filter_by(bantype="userid").count()
    total_banned_ips = Bans.query.filter_by(bantype="ip").count()
    cutoff = int(time.time()) - 86400
    active_24h = Player.query.filter(
        Player.last_online >= cutoff,
        Player.game.isnot(None),
        Player.leader_level.isnot(None),
    ).count()

    return render_template(
        "admin_home.html",
        Activity=adminActivity,
        total_players=total_players,
        total_banned=total_banned,
        total_banned_ips=total_banned_ips,
        active_24h=active_24h,
    )


@admin_bp.route("/admin/versions", methods=["GET", "POST"])
@login_required
def AdminVersions():
    if not isAdmin(current_user):
        return abort(404)

    if request.method == "GET":

        return render_template(
            "admin_versions.html",
            pc_version=ReadPersistText("version.txt", "0.0.0").strip(),
            android_version=ReadPersistText("android_version.txt", "0.0.0").strip(),
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


@admin_bp.route("/admin/server")
@login_required
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

    settings = LoadSettings()
    from app.config import TelegramConfigured

    return render_template(
        "admin_server.html",
        last_backup=last_backup,
        settings=settings,
        backup_interval=GetBackupIntervalHours(),
        telegram_configured=TelegramConfigured(),
    )


@admin_bp.route("/admin/server/backup")
@login_required
def AdminBackup():
    if not isAdmin(current_user):
        return abort(404)

    backup = Backup()
    if not backup:
        return make_response("Failed to backup", 400)
    settings = LoadSettings()
    settings["last_backup"] = int(time.time())
    SaveSettings(settings)
    if settings.get("backup_to_telegram", True):
        SendBackupToTelegram(backup)
    return redirect("/admin/server")


@admin_bp.route("/admin/server/settings", methods=["POST"])
@login_required
def AdminServerSettings():
    if not isAdmin(current_user):
        return abort(404)

    settings = LoadSettings()
    if "backup_interval_hours" in request.form:
        try:
            hours = float(request.form["backup_interval_hours"])
        except (ValueError, TypeError):
            return make_response("Invalid backup interval!", 400)
        settings["backup_interval_hours"] = max(0.0, hours)
    settings["backup_to_telegram"] = "backup_to_telegram" in request.form
    SaveSettings(settings)

    Log(
        "admin",
        current_user.username
        + " updated backup settings (interval: "
        + str(settings.get("backup_interval_hours"))
        + "h, telegram: "
        + str(settings.get("backup_to_telegram"))
        + ")",
    )
    return redirect("/admin/server")


@admin_bp.route("/admin/server/telegram_test", methods=["POST"])
@login_required
def AdminServerTelegramTest():
    if not isAdmin(current_user):
        return abort(404)

    from app.config import TelegramConfigured
    from app.utils import SendTelegramMessage

    if not TelegramConfigured():
        return make_response(
            "Telegram bot token / admin id not configured in .env", 400
        )
    ok = SendTelegramMessage("CWK Admin: Telegram notifications are working.")
    if not ok:
        return make_response(
            "Failed to send Telegram message. Check the bot token and chat id.", 400
        )
    return redirect("/admin/server")


@admin_bp.route("/admin/server/upload_backup", methods=["POST"])
@login_required
def AdminServerUploadBackup():
    """Restore the server from an uploaded backup .zip (db + persist folder)."""
    if not isAdmin(current_user):
        return abort(404)

    file = request.files.get("backup_file")
    if file is None or file.filename == "":
        return make_response("No backup file uploaded!", 400)
    if not file.filename.lower().endswith(".zip"):
        return make_response("Backup must be a .zip archive.", 400)

    tmp_dir = tempfile.mkdtemp(prefix="cwk_restore_")
    try:
        zip_path = os.path.join(tmp_dir, "upload.zip")
        file.save(zip_path)
        if not zipfile.is_zipfile(zip_path):
            return make_response("Uploaded file is not a valid zip archive.", 400)

        extract_dir = os.path.join(tmp_dir, "extract")
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path) as archive:
            # guard against zip-slip
            real_extract = os.path.realpath(extract_dir)
            for member in archive.namelist():
                if not os.path.realpath(os.path.join(extract_dir, member)).startswith(
                    real_extract
                ):
                    return make_response("Invalid archive: unsafe path detected.", 400)
            archive.extractall(extract_dir)

        db_dump = None
        sqlite_dump = None
        persist_src = None
        for root, dirs, files in os.walk(extract_dir):
            if db_dump is None and DATABASE_DUMP_NAME in files:
                db_dump = os.path.join(root, DATABASE_DUMP_NAME)
            if sqlite_dump is None and SQLITE_DUMP_NAME in files:
                sqlite_dump = os.path.join(root, SQLITE_DUMP_NAME)
            if persist_src is None and "persist" in dirs:
                persist_src = os.path.join(root, "persist")
        if db_dump is None and sqlite_dump is None:
            return make_response(
                "Invalid backup: database dump not found inside archive.", 400
            )

        # Snapshot the current state first so a bad restore can be undone.
        Backup()

        if db_dump is not None:
            ok, error = RestoreDatabaseSql(db_dump)
            if not ok:
                return make_response("Database restore failed: " + error, 400)
        elif IsPostgres():
            # Legacy backup: a SQLite file. Copy its rows into PostgreSQL.
            try:
                MigrateSqliteDatabase(sqlite_dump, replace=True)
            except Exception as e:
                return make_response("Database restore failed: " + str(e), 400)
        else:
            shutil.copy(
                sqlite_dump, os.path.join(ROOT_DIR, "instance/cardwarskingdom.db")
            )

        if persist_src is not None:
            persist_dest = os.path.join(ROOT_DIR, "data/persist")
            if os.path.isdir(persist_dest):
                shutil.rmtree(persist_dest)
            shutil.copytree(persist_src, persist_dest)

        db.session.remove()
        db.engine.dispose()

        Log(
            "admin",
            current_user.username + " restored the server from an uploaded backup",
        )
        DiscordWebhookMessage(
            current_user.username + " restored the server from an uploaded backup"
        )
        return redirect("/admin/server")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@admin_bp.route("/admin/server/pull")
@login_required
def AdminGitPull():
    if not isAdmin(current_user):
        return abort(404)

    Log("admin", current_user.username + " pulled from git.")

    # Git pull and return response
    output = subprocess.check_output(["git", "pull"])

    Log("admin", "Pulled from git. Output: " + output.decode("utf-8"))

    # TODO: restart server

    return make_response(output.decode("utf-8"), 200)


@admin_bp.route("/admin/createadmin", methods=["GET", "POST"])
@login_required
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
        return render_template(
            "admin_createadmin.html",
            created_admin={"username": username, "password": password, "rank": rank},
        )


@admin_bp.route("/admin/passkey", methods=["POST"])
def AdminPasskeyLogin():
    """Passwordless login using a 6-digit passkey only."""
    passkey = (request.form.get("passkey") or "").strip()
    if not re.fullmatch(r"\d{6}", passkey):
        return make_response("Passkey must be exactly 6 digits.", 400)

    for admin in Admin.query.filter_by(passkey_enabled=True).all():
        if admin.passkey and bcrypt.check_password_hash(admin.passkey, passkey):
            login_user(admin, remember=True)
            Log("admin", admin.username + " signed in with passkey")
            return redirect(SafeLoginNext(request.args.get("next")))

    time.sleep(1)
    Log("admin", "Failed passkey login attempt from " + IPFromRequest(request))
    return make_response("Invalid passkey!", 400)


@admin_bp.route("/admin/profile")
@login_required
def AdminProfile():
    if not isAdmin(current_user):
        return abort(404)

    admin = Admin.query.filter_by(username=current_user.username).first()
    if admin is None:
        return abort(404)
    return render_template("admin_profile.html", admin=admin)


@admin_bp.route("/admin/profile/email", methods=["POST"])
@login_required
def AdminProfileEmail():
    if not isAdmin(current_user):
        return abort(404)

    admin = Admin.query.filter_by(username=current_user.username).first()
    if admin is None:
        return abort(404)

    email = (request.form.get("email") or "").strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return make_response("Invalid email address.", 400)
    admin.email = email or None
    db.session.commit()
    Log("admin", admin.username + " updated their profile email")
    return redirect("/admin/profile")


@admin_bp.route("/admin/profile/password", methods=["POST"])
@login_required
def AdminProfilePassword():
    if not isAdmin(current_user):
        return abort(404)

    admin = Admin.query.filter_by(username=current_user.username).first()
    if admin is None:
        return abort(404)

    current = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    if not bcrypt.check_password_hash(admin.password, current):
        return make_response("Current password is incorrect.", 400)
    if len(new_password) < 8:
        return make_response("New password must be at least 8 characters.", 400)
    if new_password != confirm:
        return make_response("New passwords do not match.", 400)

    admin.password = bcrypt.generate_password_hash(new_password).decode("utf-8")
    db.session.commit()
    Log("admin", admin.username + " changed their password")
    DiscordWebhookMessage(admin.username + " changed their admin password")
    return redirect("/admin/profile")


@admin_bp.route("/admin/profile/passkey", methods=["POST"])
@login_required
def AdminProfilePasskey():
    if not isAdmin(current_user):
        return abort(404)

    admin = Admin.query.filter_by(username=current_user.username).first()
    if admin is None:
        return abort(404)

    passkey = (request.form.get("passkey") or "").strip()
    confirm = (request.form.get("confirm_passkey") or "").strip()
    if not re.fullmatch(r"\d{6}", passkey):
        return make_response("Passkey must be exactly 6 digits.", 400)
    if passkey != confirm:
        return make_response("Passkeys do not match.", 400)

    admin.passkey = bcrypt.generate_password_hash(passkey).decode("utf-8")
    admin.passkey_enabled = True
    db.session.commit()
    Log("admin", admin.username + " set a login passkey")
    return redirect("/admin/profile")


@admin_bp.route("/admin/profile/passkey/disable", methods=["POST"])
@login_required
def AdminProfilePasskeyDisable():
    if not isAdmin(current_user):
        return abort(404)

    admin = Admin.query.filter_by(username=current_user.username).first()
    if admin is None:
        return abort(404)

    admin.passkey = None
    admin.passkey_enabled = False
    db.session.commit()
    Log("admin", admin.username + " disabled their login passkey")
    return redirect("/admin/profile")
