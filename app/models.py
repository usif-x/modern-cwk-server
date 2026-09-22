import time as _time

from flask_login import UserMixin
from sqlalchemy.orm import Mapped, mapped_column

from app import db


class AdminActivity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    time = db.Column(db.Integer, nullable=False, default=int(_time.time()))
    message = db.Column(db.String(8192), nullable=True)


class RedeemCode(db.Model):
    code = db.Column(db.String(128), primary_key=True)
    reward_type = db.Column(db.String(128), nullable=False)
    reward_amount = db.Column(db.Integer, nullable=False, default=0)
    reward_item = db.Column(db.String(128), nullable=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_by = db.Column(db.String(128), nullable=True)


class Admin(UserMixin, db.Model):
    username: Mapped[str] = mapped_column(
        db.String(80), primary_key=True, unique=True, nullable=False
    )
    password: Mapped[str] = mapped_column(db.String(80), nullable=False)
    rank: Mapped[int] = mapped_column(db.Integer, nullable=False)

    def get_id(self):
        return str(self.username)


class Bans(db.Model):
    username = db.Column(db.String(80), primary_key=True)
    bantype = db.Column(db.String(80), nullable=False)
    author = db.Column(db.String(80), nullable=True)
    time = db.Column(db.Integer, nullable=True, default=int(_time.time()))
    # Unix timestamp when the ban expires. 0 or NULL = permanent.
    expires = db.Column(db.Integer, nullable=True, default=0)

    def as_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class Logs(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(80), nullable=False)
    time = db.Column(db.String(80), nullable=False)
    player = db.Column(db.String(80), nullable=False)
    ip = db.Column(db.String(80), nullable=True)
    message = db.Column(db.String(8192), nullable=False)


class UpsightLogs(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.String(80), nullable=False)
    time = db.Column(db.Integer, nullable=False, default=int(_time.time()))
    event = db.Column(db.String(80), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    message = db.Column(db.String(1024), nullable=True)


class Player(db.Model):
    username = db.Column(db.String(80), primary_key=True, unique=True, nullable=False)
    game = db.Column(db.Text, nullable=True)
    multiplayer_name = db.Column(db.String(128), nullable=True)
    icon = db.Column(db.String(128), nullable=True)
    deck = db.Column(db.String(1024), nullable=True)
    deck_rank = db.Column(db.String(16), nullable=True)
    landscapes = db.Column(db.String(1024), nullable=True)
    helper_creature = db.Column(db.String(1024), nullable=True)
    leader = db.Column(db.String(128), nullable=True)
    leader_level = db.Column(db.Integer, nullable=True)
    allyboxspace = db.Column(db.Integer, nullable=True)
    level = db.Column(db.Integer, nullable=True)
    friends = db.Column(db.Text, nullable=True, default="[]")
    friend_requests = db.Column(db.String(8192), nullable=True, default="[]")
    last_online = db.Column(db.Integer, nullable=True, default=int(_time.time()))
    helpcount = db.Column(db.Integer, nullable=True, default=0)
    anonymoushelpcount = db.Column(db.Integer, nullable=True, default=0)
    devicename = db.Column(db.String(128), nullable=True)

    def as_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}
