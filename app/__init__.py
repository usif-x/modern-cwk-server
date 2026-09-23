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

secret_key_path = os.path.join(_root_dir, "flaskkey")
if not os.path.exists(secret_key_path):
    print("Creating new Flask secret key")
    with open(secret_key_path, "w") as f:
        f.write(
            "".join(
                random.choice(string.ascii_letters + string.digits) for i in range(50)
            )
        )
app.secret_key = os.getenv("SECRET_KEY") or open(secret_key_path, "r").read()

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///cardwarskingdom.db"


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)
db.init_app(app)

bcrypt = Bcrypt(app)

login_manager = LoginManager(app)
login_manager.login_view = "/"

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

from app.utils import Log


@login_manager.user_loader
def load_user(user_id):
    from app.models import Admin

    return Admin.query.get(user_id)


def run_scheduler():
    from app.utils import RunScheduledBackup

    while True:
        try:
            RunScheduledBackup()
        except Exception as e:
            print(f"Scheduler notice: {e}")
        time.sleep(60)


with app.app_context():
    db.create_all()
    try:
        from sqlalchemy import text

        cols = [
            r[1]
            for r in db.session.execute(
                text("PRAGMA table_info(redeem_code)")
            ).fetchall()
        ]
        if cols and "reward_item" not in cols:
            db.session.execute(
                text("ALTER TABLE redeem_code ADD COLUMN reward_item VARCHAR(128)")
            )
            db.session.commit()
        ban_cols = [
            r[1] for r in db.session.execute(text("PRAGMA table_info(bans)")).fetchall()
        ]
        if ban_cols and "expires" not in ban_cols:
            db.session.execute(
                text("ALTER TABLE bans ADD COLUMN expires INTEGER DEFAULT 0")
            )
            db.session.commit()
        admin_cols = [
            r[1]
            for r in db.session.execute(text("PRAGMA table_info(admin)")).fetchall()
        ]
        if admin_cols:
            if "email" not in admin_cols:
                db.session.execute(
                    text("ALTER TABLE admin ADD COLUMN email VARCHAR(255)")
                )
            if "passkey" not in admin_cols:
                db.session.execute(
                    text("ALTER TABLE admin ADD COLUMN passkey VARCHAR(80)")
                )
            if "passkey_enabled" not in admin_cols:
                db.session.execute(
                    text(
                        "ALTER TABLE admin ADD COLUMN passkey_enabled BOOLEAN DEFAULT 0"
                    )
                )
            db.session.commit()
    except Exception as e:
        print(f"Migration notice: {e}")

from app.routes import register_blueprints

register_blueprints(app)

scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
scheduler_thread.start()
