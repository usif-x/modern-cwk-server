import re

from ._common import *
from .game_data import Log


def DatabaseBackend():
    """`postgresql` or `sqlite` for the active connection."""
    return db.engine.dialect.name


def IsPostgres():
    return DatabaseBackend().startswith("postgres")


def _PgCliArgs():
    """Connection flags shared by pg_dump and psql."""
    url = db.engine.url
    args = []
    if url.host:
        args += ["-h", url.host]
    if url.port:
        args += ["-p", str(url.port)]
    if url.username:
        args += ["-U", str(url.username)]
    return args


def _PgCliEnv():
    env = dict(os.environ)
    env.setdefault("PGAPPNAME", "cwk-server")
    if db.engine.url.password:
        env["PGPASSWORD"] = str(db.engine.url.password)
    return env


def _SqliteDatabasePath():
    path = db.engine.url.database
    if not path or path == ":memory:":
        return None
    if not os.path.isabs(path):
        path = os.path.join(ROOT_DIR, path)
    return path


def DumpDatabase(dest_dir):
    """Write a copy of the database into `dest_dir`.

    Returns the dumped file name, or `None` when the dump could not be
    produced (the caller keeps the rest of the backup usable).
    """
    if IsPostgres():
        out_path = os.path.join(dest_dir, DATABASE_DUMP_NAME)
        cmd = [
            "pg_dump",
            "--no-owner",
            "--no-privileges",
            "--clean",
            "--if-exists",
            "-f",
            out_path,
            *_PgCliArgs(),
            str(db.engine.url.database),
        ]
        try:
            subprocess.run(
                cmd,
                env=_PgCliEnv(),
                check=True,
                capture_output=True,
                text=True,
            )
            return DATABASE_DUMP_NAME
        except FileNotFoundError:
            message = "pg_dump is not installed - database backup skipped"
            Log("admin", message)
            print(message, flush=True)
        except subprocess.CalledProcessError as e:
            Log(
                "admin",
                "pg_dump failed: " + (e.stderr or str(e)).strip()[:500],
            )
        return None

    src_path = _SqliteDatabasePath()
    if not src_path or not os.path.exists(src_path):
        Log("admin", "SQLite database file not found - database backup skipped")
        return None
    shutil.copy(src_path, os.path.join(dest_dir, SQLITE_DUMP_NAME))
    return SQLITE_DUMP_NAME


# A pg_dump line that sets a session parameter: `SET name = value;` (pg_dump
# also writes `SET name TO value;`).
_SET_LINE = re.compile(r"^\s*SET\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|TO)\s", re.IGNORECASE)

# The first schema statement of a dump: everything before it is the header
# where the session settings live, so function bodies further down are never
# touched.
_HEADER_END = re.compile(r"^\s*(CREATE|ALTER|COPY|INSERT|DROP)\b", re.IGNORECASE)


def _ServerAcceptsSetting(name, psql_prefix, dbname, env):
    """True when the target server knows `SHOW <name>`.

    A dump carries the settings of the server it was taken from, so one made
    on a newer major (PostgreSQL 17 added `transaction_timeout`) contains
    parameters an older server rejects.
    """
    try:
        proc = subprocess.run(
            [*psql_prefix, "-c", "SHOW " + name, dbname],
            env=env,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return True  # psql is missing; the restore itself reports that
    return proc.returncode == 0


def _StripUnknownSettings(sql_path, psql_prefix, dbname, env):
    """Copy a pg_dump without the `SET <param> = ...` lines the server rejects.

    Such a line aborts an `ON_ERROR_STOP=1` restore even though dropping it is
    harmless - the parameter keeps its default for the session. Returns
    ``(path_to_restore, removed_line_count)``, the original path when nothing
    had to go.
    """
    accepted = {}
    cleaned_path = str(sql_path) + ".clean"
    removed = 0
    in_header = True
    try:
        with open(sql_path, "r", encoding="utf-8", errors="replace") as src, open(
            cleaned_path, "w", encoding="utf-8"
        ) as dst:
            for line in src:
                if in_header:
                    if _HEADER_END.match(line):
                        in_header = False
                    else:
                        match = _SET_LINE.match(line)
                        if match:
                            name = match.group(1)
                            if name not in accepted:
                                accepted[name] = _ServerAcceptsSetting(
                                    name, psql_prefix, dbname, env
                                )
                            if not accepted[name]:
                                removed += 1
                                continue
                dst.write(line)
    except OSError as e:
        Log("admin", f"restore: could not filter the dump ({e}); restoring it as-is")
        return sql_path, 0

    if not removed:
        try:
            os.remove(cleaned_path)
        except OSError:
            pass
        return sql_path, 0
    return cleaned_path, removed


def RestoreDatabaseSql(sql_path):
    """Replace the active PostgreSQL database with a pg_dump SQL file."""
    if not IsPostgres():
        return False, "Restoring a SQL dump requires PostgreSQL."
    if not os.path.exists(sql_path):
        return False, "Dump file not found."

    # Release our own ACCESS SHARE locks first: the dump starts with DROP
    # TABLE, which would otherwise block forever on connections we still hold.
    db.session.remove()
    db.engine.dispose()

    env = _PgCliEnv()
    env["PGOPTIONS"] = "-c lock_timeout=30000 -c statement_timeout=600000"
    dbname = str(db.engine.url.database)
    psql_prefix = ["psql", "-v", "ON_ERROR_STOP=1", "-q", *_PgCliArgs()]

    # A dump from a newer PostgreSQL (e.g. `SET transaction_timeout = 0;` from
    # 17) would abort the restore on this server, so drop what it rejects.
    dump_path, removed = _StripUnknownSettings(sql_path, psql_prefix, dbname, env)
    if removed:
        Log(
            "admin",
            f"restore: dropped {removed} SET line(s) this server does not know "
            f"({os.path.basename(sql_path)})",
        )

    cmd = [*psql_prefix, "-f", dump_path, dbname]
    try:
        subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        return False, "psql is not installed."
    except subprocess.CalledProcessError as e:
        return False, (e.stderr or str(e)).strip()[:1000]
    finally:
        db.session.remove()
        db.engine.dispose()
    return True, ""


def _CoerceMigratedValue(value, target_type):
    """Adapt a SQLite value to the type of the matching target column.

    SQLite is dynamically typed, so its files happily contain e.g. date strings
    inside an `INTEGER` column. PostgreSQL rejects those, so they are converted
    here.
    """
    if value is None:
        return None

    # SQLite stores the (text) save payload as a BLOB; decoding it keeps the
    # value usable instead of the `b'...'` repr leaking into a text column.
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            value = str(value)

    if isinstance(target_type, db.Boolean):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "t", "y", "yes")
        return bool(value)

    if isinstance(target_type, db.Integer):
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        text = str(value).strip()
        try:
            return int(text)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
                return int(parsed.timestamp())
            except ValueError:
                continue
        return 0

    if isinstance(target_type, (db.String, db.Text)):
        if not isinstance(value, str):
            value = str(value)
        # PostgreSQL rejects NUL bytes inside text; SQLite allows them.
        if "\x00" in value:
            value = value.replace("\x00", "")
        # SQLite does not enforce VARCHAR lengths, so malformed rows can carry
        # values longer than the target column allows. Truncate to fit instead
        # of aborting the whole migration (TEXT columns have no length).
        length = getattr(target_type, "length", None)
        if length and len(value) > length:
            value = value[:length]
        return value

    return value


def SyncPostgresSequences():
    """Advance SERIAL sequences to `MAX(id) + 1`.

    Rows copied over with explicit primary keys do not move the sequence, so
    the next insert would otherwise fail with a duplicate key error.
    """
    if not IsPostgres():
        return

    from sqlalchemy import text

    preparer = db.engine.dialect.identifier_preparer
    with db.engine.begin() as conn:
        for table in db.metadata.tables.values():
            for column in table.columns:
                if not column.primary_key or not isinstance(column.type, db.Integer):
                    continue
                sequence = conn.execute(
                    text("SELECT pg_get_serial_sequence(:t, :c)"),
                    {"t": table.name, "c": column.name},
                ).scalar()
                if not sequence:
                    continue
                quoted_table = preparer.quote(table.name)
                quoted_column = preparer.quote(column.name)
                conn.execute(
                    text(
                        "SELECT setval(CAST(:seq AS regclass), "
                        f"COALESCE((SELECT MAX({quoted_column}) FROM {quoted_table}), 0) "
                        "+ 1, false)"
                    ),
                    {"seq": sequence},
                )


def MigrateSqliteDatabase(sqlite_path, replace=True):
    """Copy every table of a SQLite file into the active database.

    Used both for the one-off SQLite -> PostgreSQL migration and for restoring
    an old backup that still contains `cardwarskingdom.db`. Returns a
    `{table: row_count}` map.
    """
    from sqlalchemy import MetaData, Table, create_engine, inspect, select

    from app import models  # noqa: F401  - registers the target metadata

    if not sqlite_path or not os.path.exists(sqlite_path):
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    src_engine = create_engine(f"sqlite:///{sqlite_path}")
    dst_engine = db.engine
    src_inspect = inspect(src_engine)
    src_tables = [
        name for name in src_inspect.get_table_names() if not name.startswith("sqlite_")
    ]

    counts = {}
    with dst_engine.begin() as dst_conn:
        if replace:
            for target in reversed(list(db.metadata.tables.values())):
                dst_conn.execute(target.delete())

        for table_name in src_tables:
            if table_name not in db.metadata.tables:
                continue
            src_meta = MetaData()
            src_table = Table(table_name, src_meta, autoload_with=src_engine)
            dst_table = db.metadata.tables[table_name]

            # Only carry across columns both sides know about.
            dst_columns = {c.name: c for c in dst_table.columns}
            columns = [c for c in src_table.columns if c.name in dst_columns]
            if not columns:
                continue

            with src_engine.connect() as src_conn:
                rows = (
                    src_conn.execute(select(*columns).select_from(src_table))
                    .mappings()
                    .all()
                )

            payload = []
            for row in rows:
                record = {}
                for name, column in dst_columns.items():
                    if name not in row:
                        continue
                    record[name] = _CoerceMigratedValue(row[name], column.type)
                payload.append(record)

            if payload:
                dst_conn.execute(dst_table.insert(), payload)
            counts[table_name] = len(payload)

    SyncPostgresSequences()
    return counts
