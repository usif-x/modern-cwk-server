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
    rewards = db.Column(db.Text, nullable=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_by = db.Column(db.String(128), nullable=True)


class Admin(UserMixin, db.Model):
    username: Mapped[str] = mapped_column(
        db.String(80), primary_key=True, unique=True, nullable=False
    )
    password: Mapped[str] = mapped_column(db.String(80), nullable=False)
    rank: Mapped[int] = mapped_column(db.Integer, nullable=False)
    email = db.Column(db.String(255), nullable=True)
    passkey = db.Column(db.String(80), nullable=True)
    passkey_enabled = db.Column(db.Boolean, nullable=False, default=False)

    def get_id(self):
        return str(self.username)


class Bans(db.Model):
    username = db.Column(db.String(80), primary_key=True)
    bantype = db.Column(db.String(80), nullable=False)
    author = db.Column(db.String(80), nullable=True)
    time = db.Column(db.Integer, nullable=True, default=int(_time.time()))
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


class TradeCoinBalance(db.Model):
    __tablename__ = "trade_coin_balance"
    player_id = db.Column(db.String(80), primary_key=True)
    coins = db.Column(db.Integer, nullable=False, default=0)
    updated = db.Column(db.Integer, nullable=False, default=0)


class TradeEscrow(db.Model):
    __tablename__ = "trade_escrow"
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.String(80), nullable=False, index=True)
    kind = db.Column(db.String(16), nullable=False, default="creature")
    item_json = db.Column(db.Text, nullable=False)
    created = db.Column(db.Integer, nullable=False, default=0)


class TradeListing(db.Model):
    __tablename__ = "trade_listing"
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.String(80), nullable=False, index=True)
    escrow_id = db.Column(db.Integer, nullable=False)
    price_coins = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="active", index=True)
    buyer_id = db.Column(db.String(80), nullable=True)
    created = db.Column(db.Integer, nullable=False, default=0)
    # Snapshot taken when the listing sells, so an admin can revert it: the
    # creature that was delivered and the UniqueID it got in the buyer's save.
    item_json = db.Column(db.Text, nullable=True)
    buyer_uid = db.Column(db.Integer, nullable=True)


class TradeOffer(db.Model):
    __tablename__ = "trade_offer"
    id = db.Column(db.Integer, primary_key=True)
    from_id = db.Column(db.String(80), nullable=False, index=True)
    to_id = db.Column(db.String(80), nullable=False, index=True)
    offer_json = db.Column(db.Text, nullable=False)
    request_json = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="pending", index=True)
    created = db.Column(db.Integer, nullable=False, default=0)
    # Snapshot taken when the offer is accepted, so an admin can revert it:
    # every creature that moved (with the UniqueID it got) and the coin flow.
    revert_json = db.Column(db.Text, nullable=True)


class TradeDelta(db.Model):
    """A creature a trade moved into or out of a player's save on the server.

    The app never reloads its save after a trade, so its next upload is the old
    copy: every upload re-applies the pending deltas until the uploaded save
    already agrees. Stored in the `trade_pending` table (legacy name).
    """

    __tablename__ = "trade_pending"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, index=True)
    action = db.Column(db.String(8), nullable=False)  # "add" | "remove"
    unique_id = db.Column(db.Integer, nullable=False)
    creature_id = db.Column(db.String(128), nullable=False)
    item_json = db.Column(db.Text, nullable=False)
    created = db.Column(db.Integer, nullable=False, default=0)
    done_at = db.Column(db.Integer, nullable=True, index=True)


class TradeLog(db.Model):
    __tablename__ = "trade_log"
    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.Integer, nullable=False, default=0)
    action = db.Column(db.String(32), nullable=False)
    actor = db.Column(db.String(80), nullable=True)
    detail = db.Column(db.Text, nullable=True)


class RouletteState(db.Model):
    """Daily Gift roulette cooldown + paid spin tokens (production keeps these on
    CurrencyState; cwk-server keeps them in their own table so a client save
    cannot reset them)."""

    __tablename__ = "roulette_state"
    username = db.Column(db.String(80), primary_key=True)
    spin_at = db.Column(db.Integer, nullable=False, default=0)
    spin_tokens = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.Integer, nullable=True)


class AccountLink(db.Model):
    """One row per linked third-party identity (Google). `provider` is kept
    generic so Apple or anything else can be added later without a schema change."""

    __tablename__ = "account_link"
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(32), nullable=False, default="google")
    provider_sub = db.Column(db.String(255), nullable=False, unique=True, index=True)
    username = db.Column(db.String(80), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=True)
    linked_at = db.Column(db.Integer, nullable=True)

class AdminGift(db.Model):
    """A Post Office gift for one player (production 6.1.2+ protocol).

    The app lists unclaimed rows via ``POST /mail/gifts`` and claims each once
    through ``user_action2`` with ``evt="admin gift"`` (ctx = row id). Currency
    columns are granted server-side; ``items`` carries a comma-separated list of
    ``CR:<creature>,CA:<augment>,LD:<leader>,XP:<material>`` tags that the app
    adds to the save and reports back.
    """

    __tablename__ = "admin_gift"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, index=True)
    gems = db.Column(db.Integer, nullable=False, default=0)
    coins = db.Column(db.Integer, nullable=False, default=0)
    pvp = db.Column(db.Integer, nullable=False, default=0)
    shards = db.Column(db.Integer, nullable=False, default=0)
    items = db.Column(db.Text, nullable=False, default="")
    title = db.Column(db.String(80), nullable=False, default="")
    message = db.Column(db.String(400), nullable=False, default="")
    sender = db.Column(db.String(80), nullable=False, default="")
    created_at = db.Column(db.Integer, nullable=False, default=0)
    claimed_at = db.Column(db.Integer, nullable=True)


class MonthlyStoreConfig(db.Model):
    """The single row holding the curated Monthly Store offer lists.

    Kept in the database (not a file) so an admin's curation survives a dyno
    restart; ``data`` is the JSON payload the GET endpoint serves.
    """

    __tablename__ = "monthly_store_config"
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text, nullable=False, default="{}")
    updated_at = db.Column(
        db.Integer,
        nullable=False,
        default=lambda: int(_time.time()),
        onupdate=lambda: int(_time.time()),
    )


class MonthlyStorePurchase(db.Model):
    """How often a player bought a Monthly Store offer this month.

    Offer lists live in ``MonthlyStoreConfig``; the counters live here so a
    client save upload cannot reset them.
    """

    __tablename__ = "monthly_store_purchase"
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.String(80), nullable=False, index=True)
    store_type = db.Column(db.String(32), nullable=False)
    offer_id = db.Column(db.String(255), nullable=False)
    month_key = db.Column(db.String(7), nullable=False)
    buy_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.Integer, nullable=False, default=lambda: int(_time.time()))
    updated_at = db.Column(
        db.Integer,
        nullable=False,
        default=lambda: int(_time.time()),
        onupdate=lambda: int(_time.time()),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "player_id",
            "store_type",
            "offer_id",
            "month_key",
            name="uq_monthly_store_purchase",
        ),
    )


class MailClaim(db.Model):
    """One claimed db_NewsMail entry (production ``once_key = "mail|<id>[|<date>]"``).

    Repeatable mails carry the weekday date they were shown on, so a daily mail
    can be claimed once per matching day; a one-shot mail is keyed by its id
    alone. Rows live in the database because a client save upload must never be
    able to reset a claim.
    """

    __tablename__ = "mail_claim"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, index=True)
    once_key = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.Integer, nullable=False, default=lambda: int(_time.time()))

    __table_args__ = (
        db.UniqueConstraint("username", "once_key", name="uq_mail_claim"),
    )
