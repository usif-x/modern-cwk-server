"""Server-authoritative player-to-player trade market.

Ported from the production trade_* endpoints. Saves are decoded with the shared
game-data codec; every trade mutation rewrites the owner's save and records a
TradeDelta so the owner's next (stale) upload is corrected (ApplyTradeDeltasToGame).
"""

import base64
import gzip
import hashlib
import hmac
import io
import json
import os
import re
import threading
import time
from urllib.parse import parse_qs

from flask import jsonify, request

from app import app as flask_app

from ._common import *
from .game_data import DecryptGameData, EncryptGameData

TRADE_PACKS = {100: (7000, 700000), 500: (21500, 2500000), 1000: (40000, 4500000)}

_trade_lock = threading.Lock()  # serialize trade mutations

MARKET_CAP = 10  # at most 10 creatures listed per player at once
MARKET_EXPIRE_SECONDS = 7 * 86400  # unsold for 7 days -> returns to seller
MARKET_SORTS = {
    "new": (lambda r: -r[0].created),
    "old": (lambda r: r[0].created),
    "cheap": (lambda r: (r[0].price_coins, -r[0].created)),
    "dear": (lambda r: (-r[0].price_coins, -r[0].created)),
    "stars": (lambda r: (-int(r[2].get("StarRating") or 0), r[0].price_coins)),
}

TRADE_HOLD_SECONDS = 48 * 3600
LOCK_MOVES_PATH = os.path.join(ROOT_DIR, "data/persist/lock_moves.json")
TRADE_INV_CAP = int(os.environ.get("CWK_TRADE_INV_CAP", "200"))

_min_client_cache = {"at": 0, "version": ""}


def _tnow():
    return int(time.time())


def _tlog(action, actor, detail):
    from app.models import TradeLog

    try:
        db.session.add(
            TradeLog(ts=_tnow(), action=action, actor=actor, detail=(detail or "")[:1900])
        )
    except Exception:
        pass


def _tparse():
    d = parse_qs(request.get_data().decode("utf-8"))
    return {k: (v[0] if len(v) == 1 else v) for k, v in d.items()}


def _tok(data):
    return jsonify({"success": True, "data": data})


def _terr(msg, code=400):
    return jsonify({"success": False, "error": msg}), code


# --------------------------------------------------------------------------
# save codec
# --------------------------------------------------------------------------


def _as_text(raw):
    if isinstance(raw, (bytes, bytearray)):
        return raw.decode("utf-8", "replace")
    return str(raw)


def _decode_save(raw):
    """Return the game dict, tolerating the client's malformed JSON. None on failure."""
    if not raw:
        return None
    try:
        text = _as_text(raw)
        marker = text.find("&data=")
        if marker == -1:
            stripped = text.strip()
            if stripped.startswith("{"):
                try:
                    parsed = json.loads(stripped)
                    return parsed if isinstance(parsed, dict) else None
                except Exception:
                    return None
            return None
        blob = base64.b64decode(text[marker + 6 :])
        with gzip.GzipFile(fileobj=io.BytesIO(blob), mode="rb") as gz:
            body = gz.read().decode("utf-8")
    except Exception:
        return None
    try:
        parsed = json.loads(body)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    repaired = (
        body.replace(",}", "}").replace(",],", "],").replace(",]", "]").replace(",,", ",")
    )
    repaired = re.sub(r'":\s*(?=[,}\]])', '":null', repaired)
    try:
        parsed = json.loads(repaired)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _tload_save(player):
    g = player.game
    if g is None:
        return {}
    txt = g.decode("utf-8", "replace") if isinstance(g, (bytes, bytearray)) else str(g)
    if txt.strip().startswith("{"):
        try:
            d = json.loads(txt)
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    d = DecryptGameData(g)
    if not isinstance(d, dict):
        d = _decode_save(g)
    if not isinstance(d, dict):
        raise ValueError("unreadable save")
    return d


def _tcreatures(save_json):
    out = {}
    for it in save_json.get("Inventory") or []:
        if isinstance(it, dict) and it.get("_T") == "CR":
            try:
                out[int(it.get("UniqueID"))] = it
            except Exception:
                pass
    return out


def _tinv(save_json):
    inv = save_json.get("Inventory")
    if not isinstance(inv, list):
        inv = []
        save_json["Inventory"] = inv
    return inv


def _tmax_uid(inv):
    m = 0
    for it in inv:
        try:
            u = int(it.get("UniqueID", 0))
            if u > m:
                m = u
        except Exception:
            continue
    return m


def _tfind_creature(inv, unique_id):
    for it in inv:
        try:
            if (
                isinstance(it, dict)
                and it.get("_T") == "CR"
                and int(it.get("UniqueID", -1)) == int(unique_id)
            ):
                return it
        except Exception:
            continue
    return None


def _tspace_full(save_json, adding=1):
    if adding <= 0:
        return False
    inv = save_json.get("Inventory") or []
    filled = sum(
        1 for it in inv if isinstance(it, dict) and it.get("_T") in ("CR", "CA", "EV", "XP")
    )
    try:
        cap = int(save_json.get("InventorySpace"))
    except Exception:
        return False
    return (filled + adding) > cap


def _tvalid_creature(item):
    return (
        isinstance(item, dict)
        and item.get("_T") == "CR"
        and str(item.get("ID", "")).strip() != ""
    )


def _twrite_save(player, save_json):
    """Store the save and record what changed, so stale uploads are corrected."""
    from app.models import TradeDelta

    before, after, now = _tcreatures(_tload_save(player)), _tcreatures(save_json), _tnow()
    changes = [
        ("remove", u, it) for u, it in before.items() if after.get(u, {}).get("ID") != it.get("ID")
    ]
    changes += [
        ("add", u, it) for u, it in after.items() if before.get(u, {}).get("ID") != it.get("ID")
    ]
    for action, uid, it in changes:
        cid = str(it.get("ID"))
        opposite = TradeDelta.query.filter_by(
            username=player.username,
            unique_id=uid,
            creature_id=cid,
            action="add" if action == "remove" else "remove",
            done_at=None,
        ).first()
        if opposite is not None:
            opposite.done_at = now
            continue
        db.session.add(
            TradeDelta(
                username=player.username,
                action=action,
                unique_id=uid,
                creature_id=cid,
                item_json=json.dumps(it, ensure_ascii=False),
                created=now,
            )
        )
    player.game = EncryptGameData(save_json, player.username)


def ApplyTradeDeltasToGame(username, game):
    """Correct a freshly uploaded save with trades the app has not seen yet."""
    from app.models import TradeDelta

    rows = TradeDelta.query.filter_by(username=username, done_at=None).order_by(TradeDelta.id).all()
    if not rows or not isinstance(game, dict):
        return game
    inv = _tinv(game)
    by_uid = _tcreatures(game)
    now = _tnow()
    for r in rows:
        it = by_uid.get(r.unique_id)
        same = it is not None and str(it.get("ID")) == r.creature_id
        if r.action == "remove":
            if same:
                try:
                    inv.remove(it)
                except ValueError:
                    pass
                by_uid.pop(r.unique_id, None)
            else:
                r.done_at = now
        else:
            if same:
                r.done_at = now
            else:
                item = json.loads(r.item_json)
                if it is not None:
                    item["UniqueID"] = _tmax_uid(inv) + 1
                    r.unique_id = item["UniqueID"]
                    r.item_json = json.dumps(item, ensure_ascii=False)
                inv.append(item)
                by_uid[item["UniqueID"]] = item
    db.session.commit()
    return game


# --------------------------------------------------------------------------
# balances
# --------------------------------------------------------------------------


def _tbalance(pid, create=True):
    from app.models import TradeCoinBalance

    row = TradeCoinBalance.query.filter_by(player_id=pid).first()
    if row is None and create:
        row = TradeCoinBalance(player_id=pid, coins=0, updated=_tnow())
        db.session.add(row)
    return row


# --------------------------------------------------------------------------
# public ids (hide real player ids in the market)
# --------------------------------------------------------------------------

_PUBLIC_KEY = hashlib.sha256(("public-id|" + flask_app.secret_key).encode()).digest()
_public_book = {"at": 0.0, "map": {}}


def PublicId(real, viewer=None):
    real = str(real or "")
    if not real or real == str(viewer or "") or real.startswith("bot_"):
        return real
    return "z" + hmac.new(_PUBLIC_KEY, real.encode(), hashlib.sha256).hexdigest()[:23]


def RealId(value):
    value = str(value or "")
    if len(value) != 24 or value[0] != "z" or any(c not in "0123456789abcdef" for c in value[1:]):
        return value
    hit = _public_book["map"].get(value)
    if hit is None and time.time() - _public_book["at"] > 30:
        _public_book.update(
            at=time.time(),
            map={PublicId(u): u for (u,) in db.session.query(Player.username)},
        )
        hit = _public_book["map"].get(value)
    return hit or value


# --------------------------------------------------------------------------
# device / client guards
# --------------------------------------------------------------------------


def _read_json_file(path, default):
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default
    except (OSError, ValueError):
        return default


def _device_refused(player):
    """True when the request's device header does not match the account's bound device."""
    if player is None or not player.devicename:
        return False
    dev = request.headers.get("X-Nick-Description")
    if dev is None or dev == player.devicename:
        return False
    return True


def _ttrade_refused(pid):
    """Why this trade request is refused, or None."""
    player = Player.query.filter_by(username=str(pid)).first()
    if _device_refused(player):
        return "this device is not linked to that account"
    if player is None or not player.devicename:
        return None
    moved = _read_json_file(LOCK_MOVES_PATH, {}).get(str(pid))
    if moved and time.time() - moved < TRADE_HOLD_SECONDS:
        return "trading unlocks 48 hours after this account moved to a new device"
    return None


def _ver(value):
    try:
        return tuple(int(x) for x in str(value).split(".")[:3])
    except Exception:
        return (0,)


def _client_too_old():
    """True when data/persist/min_client_version.txt names a version newer than the client."""
    try:
        with open(os.path.join(ROOT_DIR, "data/persist/min_client_version.txt")) as handle:
            wanted = handle.read().strip()
    except Exception:
        return False
    return bool(wanted) and _ver(request.headers.get("version")) < _ver(wanted)


# --------------------------------------------------------------------------
# market sweep / paging
# --------------------------------------------------------------------------

_market_swept = [0]


def _market_return(lst, status):
    """Close an active listing and return its creature to the seller (like a cancel)."""
    from app.models import TradeEscrow

    seller = Player.query.filter_by(username=lst.seller_id).first()
    esc = TradeEscrow.query.get(lst.escrow_id)
    if seller is None or esc is None:
        return False
    item = dict(json.loads(esc.item_json))
    ssave = _tload_save(seller)
    sinv = _tinv(ssave)
    item["UniqueID"] = _tmax_uid(sinv) + 1
    sinv.append(item)
    _twrite_save(seller, ssave)
    lst.status = status
    db.session.delete(esc)
    _tlog(status, lst.seller_id, f"listing={lst.id} cre={item.get('ID')}")
    return True


def _market_expire(limit=25):
    """Return unsold listings older than MARKET_EXPIRE_SECONDS, at most once a minute."""
    from app.models import TradeListing

    now = _tnow()
    if now - _market_swept[0] < 60:
        return 0
    _market_swept[0] = now
    old = (
        TradeListing.query.filter(
            TradeListing.status == "active",
            TradeListing.created < now - MARKET_EXPIRE_SECONDS,
        )
        .order_by(TradeListing.created)
        .limit(limit)
        .all()
    )
    done = 0
    for lst in old:
        try:
            if _market_return(lst, "expired"):
                done += 1
            else:
                lst.status = "stuck"
                _tlog("stuck", lst.seller_id, f"listing={lst.id} seller or escrow missing")
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            lst = TradeListing.query.get(lst.id)
            if lst is not None and lst.status == "active":
                lst.status = "stuck"
                _tlog("stuck", lst.seller_id, f"listing={lst.id} return failed: {e}")
                db.session.commit()
    return done


def _market_page(p):
    """trade_browseDW v=2 payload."""
    from app.models import TradeListing, TradeEscrow

    viewer = str(p.get("player_id") or "")
    try:
        start = max(0, int(p.get("start", 0)))
        count = min(1000, max(1, int(p.get("count", 20))))
    except Exception:
        start, count = 0, 20
    ids = set(x for x in str(p.get("ids") or "").split(",") if x)

    def num(k, d):
        try:
            return int(p.get(k, d))
        except Exception:
            return d

    smin, smax, pmin, pmax = num("smin", 0), num("smax", 99), num("pmin", 0), num(
        "pmax", 10 ** 18
    )
    mine = str(p.get("mine") or "") == "1"
    rows = []
    q = (
        db.session.query(TradeListing, TradeEscrow)
        .join(TradeEscrow, TradeEscrow.id == TradeListing.escrow_id)
        .filter(TradeListing.status == "active")
    )
    for lst, esc in q.all():
        try:
            item = json.loads(esc.item_json)
        except Exception:
            continue
        stars = int(item.get("StarRating") or 0)
        if mine and lst.seller_id != viewer:
            continue
        if ids and str(item.get("ID")) not in ids:
            continue
        if not (smin <= stars <= smax and pmin <= lst.price_coins <= pmax):
            continue
        rows.append((lst, esc, item))
    rows.sort(key=MARKET_SORTS.get(str(p.get("sort") or "new"), MARKET_SORTS["new"]))
    out = [
        {
            "listing_id": lst.id,
            "seller_id": PublicId(lst.seller_id, request.headers.get("Player-Id")),
            "price": lst.price_coins,
            "kind": esc.kind,
            "creature_id": item.get("ID"),
            "star_rating": item.get("StarRating"),
            "created": lst.created,
            "expires": lst.created + MARKET_EXPIRE_SECONDS,
            "mine": bool(viewer) and lst.seller_id == viewer,
            "item": item,
        }
        for lst, esc, item in rows[start : start + count]
    ]
    listed = TradeListing.query.filter_by(seller_id=viewer, status="active").count() if viewer else 0
    return {
        "rows": out,
        "total": len(rows),
        "start": start,
        "listed": listed,
        "cap": MARKET_CAP,
        "expire_days": MARKET_EXPIRE_SECONDS // 86400,
        "now": _tnow(),
    }


def _tcsv_ints(s):
    out = []
    for part in str(s or "").split(","):
        part = part.strip()
        if part:
            try:
                out.append(int(part))
            except Exception:
                pass
    return out
