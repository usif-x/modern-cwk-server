"""Admin control panel for the player-to-player trade market."""

import json

from ._common import *
from app.models import (
    Player,
    TradeCoinBalance,
    TradeDelta,
    TradeEscrow,
    TradeListing,
    TradeLog,
    TradeOffer,
)
from app.services.trade_market import (
    MARKET_CAP,
    MARKET_EXPIRE_SECONDS,
    _market_expire,
    _market_return,
    _tinv,
    _tload_save,
    _tmax_uid,
    _tnow,
    _twrite_save,
)


def _player_names(ids):
    ids = {str(i) for i in ids if i}
    if not ids:
        return {}
    rows = Player.query.filter(Player.username.in_(ids)).all()
    return {r.username: (r.multiplayer_name or "Unnamed") for r in rows}


@admin_bp.route("/admin/market")
@login_required
def AdminMarket():
    if not isAdmin(current_user):
        return abort(404)

    status = request.args.get("status", "active", type=str)
    if status not in ("active", "sold", "cancelled", "expired", "removed", "stuck", "all"):
        status = "active"

    creature_names = GetCreatureNameMap()

    query = TradeListing.query
    if status != "all":
        query = query.filter(TradeListing.status == status)
    listings_db = query.order_by(TradeListing.created.desc()).limit(300).all()

    escrows = {e.id: e for e in TradeEscrow.query.all()}
    sellers = _player_names(l.seller_id for l in listings_db)

    listings = []
    for l in listings_db:
        esc = escrows.get(l.escrow_id)
        item = {}
        if esc is not None:
            try:
                item = json.loads(esc.item_json)
            except Exception:
                item = {}
        cid = item.get("ID", "")
        listings.append(
            {
                "id": l.id,
                "seller_id": l.seller_id,
                "seller_name": sellers.get(l.seller_id, "Unknown"),
                "price": l.price_coins,
                "status": l.status,
                "buyer_id": l.buyer_id,
                "created": l.created,
                "escrow_id": l.escrow_id,
                "escrow_missing": esc is None,
                "creature_id": cid,
                "creature_name": creature_names.get(cid, ""),
                "star_rating": item.get("StarRating"),
            }
        )

    # Orphan escrows (not referenced by an active listing or pending offer)
    keep = {l.escrow_id for l in TradeListing.query.filter_by(status="active").all()}
    offers_db = (
        TradeOffer.query.filter_by(status="pending").order_by(TradeOffer.created.desc()).limit(200).all()
    )
    for o in offers_db:
        try:
            keep.update(json.loads(o.offer_json).get("escrow_ids", []))
        except Exception:
            pass

    escrow_rows = []
    for e in TradeEscrow.query.order_by(TradeEscrow.id.desc()).limit(300).all():
        try:
            it = json.loads(e.item_json)
        except Exception:
            it = {}
        cid = it.get("ID", "")
        escrow_rows.append(
            {
                "id": e.id,
                "player_id": e.player_id,
                "kind": e.kind,
                "created": e.created,
                "creature_id": cid,
                "creature_name": creature_names.get(cid, ""),
                "star_rating": it.get("StarRating"),
                "orphan": e.id not in keep,
            }
        )

    names = _player_names(
        [o.from_id for o in offers_db] + [o.to_id for o in offers_db]
    )
    offers = []
    for o in offers_db:
        try:
            off = json.loads(o.offer_json)
            req = json.loads(o.request_json)
        except Exception:
            off, req = {}, {}
        offers.append(
            {
                "id": o.id,
                "from_id": o.from_id,
                "from_name": names.get(o.from_id, "Unknown"),
                "to_id": o.to_id,
                "to_name": names.get(o.to_id, "Unknown"),
                "coins": off.get("coins", 0),
                "escrow_ids": off.get("escrow_ids", []),
                "want_coins": req.get("coins", 0),
                "want_uids": req.get("unique_ids", []),
                "created": o.created,
            }
        )

    balances = []
    for b in TradeCoinBalance.query.order_by(TradeCoinBalance.coins.desc()).limit(200).all():
        balances.append(
            {
                "player_id": b.player_id,
                "coins": b.coins,
                "updated": b.updated,
            }
        )

    logs = []
    for lg in TradeLog.query.order_by(TradeLog.id.desc()).limit(100).all():
        logs.append(
            {
                "ts": lg.ts,
                "action": lg.action,
                "actor": lg.actor,
                "detail": lg.detail,
            }
        )

    stats = {
        "active": TradeListing.query.filter_by(status="active").count(),
        "sold": TradeListing.query.filter_by(status="sold").count(),
        "total_listings": TradeListing.query.count(),
        "escrows": TradeEscrow.query.count(),
        "offers": TradeOffer.query.filter_by(status="pending").count(),
        "coins_in_circulation": db.session.query(
            db.func.coalesce(db.func.sum(TradeCoinBalance.coins), 0)
        ).scalar(),
        "pending_deltas": TradeDelta.query.filter_by(done_at=None).count(),
    }

    return render_template(
        "admin_market.html",
        listings=listings,
        escrows=escrow_rows,
        offers=offers,
        balances=balances,
        logs=logs,
        stats=stats,
        status=status,
        market_cap=MARKET_CAP,
        expire_days=MARKET_EXPIRE_SECONDS // 86400,
    )


@admin_bp.route("/admin/market/listing/<int:listing_id>/remove", methods=["POST"])
@login_required
def AdminMarketListingRemove(listing_id):
    if not isAdmin(current_user):
        return abort(404)

    lst = TradeListing.query.get(listing_id)
    if lst is None:
        return make_response("Listing not found!", 404)

    try:
        if lst.status == "active":
            returned = _market_return(lst, "removed")
            if not returned:
                lst.status = "removed"
        else:
            lst.status = "removed"
        db.session.commit()
        Log("admin", current_user.username + f" removed trade listing {listing_id}")
    except Exception as e:
        db.session.rollback()
        return make_response(f"Failed to remove listing: {e}", 500)

    return redirect(request.referrer or "/admin/market")


@admin_bp.route("/admin/market/listing/<int:listing_id>/delete", methods=["POST"])
@login_required
def AdminMarketListingDelete(listing_id):
    if not isAdmin(current_user):
        return abort(404)

    lst = TradeListing.query.get(listing_id)
    if lst is None:
        return make_response("Listing not found!", 404)

    esc = TradeEscrow.query.get(lst.escrow_id)
    if esc is not None:
        db.session.delete(esc)
    db.session.delete(lst)
    db.session.commit()
    Log(
        "admin",
        current_user.username
        + f" deleted trade listing {listing_id} (escrow destroyed, creature lost)",
    )
    DiscordWebhookMessage(
        f"**{current_user.username}** deleted trade listing `{listing_id}` (escrow destroyed)"
    )
    return redirect(request.referrer or "/admin/market")


@admin_bp.route("/admin/market/escrow/<int:escrow_id>/delete", methods=["POST"])
@login_required
def AdminMarketEscrowDelete(escrow_id):
    if not isAdmin(current_user):
        return abort(404)

    esc = TradeEscrow.query.get(escrow_id)
    if esc is None:
        return make_response("Escrow not found!", 404)

    db.session.delete(esc)
    db.session.commit()
    Log("admin", current_user.username + f" deleted trade escrow {escrow_id}")
    return redirect(request.referrer or "/admin/market")


@admin_bp.route("/admin/market/offer/<int:offer_id>/cancel", methods=["POST"])
@login_required
def AdminMarketOfferCancel(offer_id):
    if not isAdmin(current_user):
        return abort(404)

    o = TradeOffer.query.get(offer_id)
    if o is None:
        return make_response("Offer not found!", 404)

    try:
        if o.status == "pending":
            offer = json.loads(o.offer_json)
            sender = Player.query.filter_by(username=o.from_id).first()
            if sender is not None:
                ssave = _tload_save(sender)
                sinv = _tinv(ssave)
                for eid in offer.get("escrow_ids", []):
                    esc = TradeEscrow.query.get(eid)
                    if esc is not None:
                        it = dict(json.loads(esc.item_json))
                        it["UniqueID"] = _tmax_uid(sinv) + 1
                        sinv.append(it)
                        db.session.delete(esc)
                _twrite_save(sender, ssave)
            bal = TradeCoinBalance.query.filter_by(player_id=o.from_id).first()
            if bal is None:
                bal = TradeCoinBalance(player_id=o.from_id, coins=0, updated=_tnow())
                db.session.add(bal)
            bal.coins = int(bal.coins) + int(offer.get("coins", 0))
            bal.updated = _tnow()
            o.status = "cancelled"
        db.session.commit()
        Log("admin", current_user.username + f" cancelled trade offer {offer_id}")
    except Exception as e:
        db.session.rollback()
        return make_response(f"Failed to cancel offer: {e}", 500)

    return redirect(request.referrer or "/admin/market")


@admin_bp.route("/admin/market/balance/set", methods=["POST"])
@login_required
def AdminMarketBalanceSet():
    if not isAdmin(current_user):
        return abort(404)

    player_id = (request.form.get("player_id") or "").strip()
    try:
        coins = int(request.form.get("coins", "0"))
    except (TypeError, ValueError):
        return make_response("Invalid coin amount!", 400)

    if not player_id:
        return make_response("Player id is required!", 400)
    coins = max(0, coins)
    if Player.query.filter_by(username=player_id).first() is None:
        return make_response("Player not found!", 404)

    bal = TradeCoinBalance.query.filter_by(player_id=player_id).first()
    if bal is None:
        bal = TradeCoinBalance(player_id=player_id, coins=coins, updated=_tnow())
        db.session.add(bal)
    else:
        bal.coins = coins
        bal.updated = _tnow()
    db.session.commit()
    Log(
        "admin",
        current_user.username + f" set trade coins for {player_id} to {coins}",
    )
    return redirect(request.referrer or "/admin/market")


@admin_bp.route("/admin/market/expire", methods=["POST"])
@login_required
def AdminMarketExpire():
    if not isAdmin(current_user):
        return abort(404)

    from app.services.trade_market import _market_swept

    _market_swept[0] = 0  # force a sweep regardless of the once-a-minute throttle
    try:
        done = _market_expire(limit=500)
        db.session.commit()
        Log("admin", current_user.username + f" ran trade expiry sweep ({done} returned)")
    except Exception as e:
        db.session.rollback()
        return make_response(f"Expiry sweep failed: {e}", 500)
    return redirect(request.referrer or "/admin/market")


@admin_bp.route("/admin/market/purge", methods=["POST"])
@login_required
def AdminMarketPurge():
    if not isAdmin(current_user):
        return abort(404)

    # Delete closed listings, then any escrow no longer referenced by an active
    # listing or pending offer.
    closed = TradeListing.query.filter(TradeListing.status != "active").all()
    deleted_listings = len(closed)
    for l in closed:
        db.session.delete(l)
    db.session.flush()

    keep = {l.escrow_id for l in TradeListing.query.filter_by(status="active").all()}
    for o in TradeOffer.query.filter_by(status="pending").all():
        try:
            keep.update(json.loads(o.offer_json).get("escrow_ids", []))
        except Exception:
            pass
    deleted_escrows = 0
    for e in TradeEscrow.query.all():
        if e.id not in keep:
            db.session.delete(e)
            deleted_escrows += 1
    db.session.commit()
    Log(
        "admin",
        current_user.username
        + f" purged trade market ({deleted_listings} listings, {deleted_escrows} escrows)",
    )
    return redirect(request.referrer or "/admin/market")
