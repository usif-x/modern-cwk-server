import argparse
import os
import random
import string
import threading
import time

import schedule
from flask import Flask
from flask_bcrypt import Bcrypt
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=5000)
parser.add_argument("--debug", action="store_true")

args, _ = parser.parse_known_args()

_root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(
    __name__,
    template_folder=os.path.join(_root_dir, "templates"),
    static_folder=os.path.join(_root_dir, "static"),
)

# Load the gitignored `.env` before anything reads configuration.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_root_dir, ".env"))
except Exception:
    pass

secret_key_path = os.path.join(_root_dir, "flaskkey")
_secret_env = (os.getenv("SECRET_KEY") or "").strip()
if _secret_env:
    app.secret_key = _secret_env
else:
    if not os.path.exists(secret_key_path):
        print("Creating new Flask secret key")
        with open(secret_key_path, "w") as f:
            f.write(
                "".join(
                    random.choice(string.ascii_letters + string.digits) for i in range(50)
                )
            )
    app.secret_key = open(secret_key_path, "r").read()
    if os.getenv("DYNO"):
        # Heroku wipes the slug's files between releases: a regenerated key
        # silently invalidates every admin session.
        print(
            "WARNING: SECRET_KEY is not set — sessions are invalidated on every "
            "restart. Set one with: "
            'heroku config:set SECRET_KEY="$(openssl rand -hex 32)"'
        )

# PostgreSQL is the primary database. Point DATABASE_URL (or POSTGRES_URL) at
# any PostgreSQL server; without one we use the local development server.
DEFAULT_POSTGRES_URI = "postgresql+psycopg2://localhost:5432/cardwarskingdom"


def ResolveDatabaseUri():
    """Build the SQLAlchemy URI from the environment (PostgreSQL by default).

    Every common scheme is normalised onto psycopg2: `postgres://` (Heroku),
    `postgresql://`, `postgres+psycopg2://` and `postgresql+psycopg2://` all
    end up as `postgresql+psycopg2://`. Set `DATABASE_URL` (or `POSTGRES_URL`)
    to `sqlite:///...` to opt back into the legacy single-file database.
    """
    raw = (os.getenv("DATABASE_URL") or "").strip() or (
        os.getenv("POSTGRES_URL") or ""
    ).strip()
    if not raw:
        return DEFAULT_POSTGRES_URI
    if raw.startswith("sqlite:"):
        return raw
    for scheme in (
        "postgresql+psycopg2",
        "postgres+psycopg2",
        "postgresql",
        "postgres",
    ):
        prefix = scheme + "://"
        if raw.startswith(prefix):
            return "postgresql+psycopg2://" + raw[len(prefix) :]
    return raw


app.config["SQLALCHEMY_DATABASE_URI"] = ResolveDatabaseUri()

_engine_options = {"pool_pre_ping": True, "pool_recycle": 1800}
if app.config["SQLALCHEMY_DATABASE_URI"].split("://")[0].startswith("sqlite"):
    _engine_options["connect_args"] = {"check_same_thread": False}
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = _engine_options


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)
db.init_app(app)

bcrypt = Bcrypt(app)

login_manager = LoginManager(app)
login_manager.login_view = "/admin"

maintenance = False

badcharaters = [
    "/",
    "\\",
    ":",
    "*",
    "?",
    '"',
    "<",
    ">",
    "|",
    ";",
    "%",
    "^",
    "&",
    "(",
    ")",
    "{",
    "}",
    "[",
    "]",
    ".",
    ",",
    "'",
    "`",
    "!",
    "$",
    "#",
    "@",
    "+",
    "=",
]

from app.utils import EnsurePersistLayout, FormatTimestamp, Log

# Templates format stored unix timestamps through this filter so routes never
# overwrite ORM rows with display strings (PostgreSQL rejects that on flush).
app.jinja_env.filters["fmt_ts"] = FormatTimestamp

# Ship-time repairs for files git may have tracked under a different case.
EnsurePersistLayout()


@login_manager.user_loader
def load_user(user_id):
    from app.models import Admin

    return Admin.query.get(user_id)


def run_scheduler():
    from app.utils import RunScheduledBackup

    while True:
        try:
            # The backup path touches the database (pg_dump connection info),
            # which Flask-SQLAlchemy only exposes inside an app context.
            with app.app_context():
                RunScheduledBackup()
        except Exception as e:
            print(f"Scheduler notice: {e}")
        time.sleep(60)


with app.app_context():
    print(f"Database: {db.engine.url.render_as_string(hide_password=True)}")
    db.create_all()
    try:
        from sqlalchemy import Boolean, Integer, String, Text, inspect, text

        engine = db.engine
        is_postgres = engine.dialect.name == "postgresql"
        inspector = inspect(engine)

        # `db.create_all()` only creates missing tables, so columns added after
        # the first release have to be backfilled by hand. The DDL is dialect
        # aware because PostgreSQL and SQLite disagree on boolean literals.
        required_columns = {
            "redeem_code": [
                ("reward_item", String(128), None),
                ("rewards", Text, None),
            ],
            "bans": [("expires", Integer, 0)],
            "admin": [
                ("email", String(255), None),
                ("passkey", String(80), None),
                ("passkey_enabled", Boolean, False),
            ],
        }

        table_names = set(inspector.get_table_names())
        for table, columns in required_columns.items():
            if table not in table_names:
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, col_type, default in columns:
                if name in existing:
                    continue
                statement = (
                    f"ALTER TABLE {table} ADD COLUMN {name} "
                    f"{col_type.compile(dialect=engine.dialect)}"
                )
                if isinstance(default, bool):
                    if is_postgres:
                        statement += " DEFAULT " + ("TRUE" if default else "FALSE")
                    else:
                        statement += " DEFAULT " + ("1" if default else "0")
                elif default is not None:
                    statement += f" DEFAULT {default}"
                db.session.execute(text(statement))
                print(f"Migration notice: added {table}.{name}")
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Migration notice: {e}")

from app.routes import register_blueprints

register_blueprints(app)

scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
scheduler_thread.start()
