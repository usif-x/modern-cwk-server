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
app = Flask(__name__, template_folder=os.path.join(_root_dir, "templates"), static_folder=os.path.join(_root_dir, "static"))

if not os.path.exists("flaskkey"):
    print("Creating new Flask secret key")
    with open("flaskkey", "w") as f:
        f.write(
            "".join(
                random.choice(string.ascii_letters + string.digits) for i in range(50)
            )
        )
app.secret_key = open("flaskkey", "r").read()

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
    "/", "\\", ":", "*", "?", '"', "<", ">", "|", ";",
    "%", "^", "&", "(", ")", "{", "}", "[", "]", ".",
    ",", "'", "`", "!", "$", "#", "@", "+", "=",
]

from app.utils import Log


@login_manager.user_loader
def load_user(user_id):
    from app.models import Admin
    return Admin.query.get(user_id)


def run_scheduler():
    from app.utils import Backup
    schedule.every(4).hours.do(Backup)
    while True:
        schedule.run_pending()
        time.sleep(1)


with app.app_context():
    db.create_all()
    try:
        from sqlalchemy import text
        cols = [r[1] for r in db.session.execute(text("PRAGMA table_info(redeem_code)")).fetchall()]
        if cols and "reward_item" not in cols:
            db.session.execute(text("ALTER TABLE redeem_code ADD COLUMN reward_item VARCHAR(128)"))
            db.session.commit()
    except Exception as e:
        print(f"Migration notice: {e}")

from app.routes import register_blueprints
register_blueprints(app)

scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
scheduler_thread.start()
