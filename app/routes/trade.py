"""Client-facing trade market endpoints (ported from the production server).

All routes are POST, form-encoded, and respond with {"success": bool, ...}.
"""

import json

from flask import Blueprint, request

from app import db
from app.models import (
    Player,
    TradeCoinBalance,
    TradeDelta,
    TradeEscrow,
    TradeListing,
    TradeOffer,
)
from app.services.trade_market import (
    MARKET_CAP,
    TRADE_INV_CAP,
    TRADE_PACKS,
    PublicId,
    RealId,
    _client_too_old,
    _device_refused,
    _market_expire,
    _market_page,
    _tbalance,
    _tcreatures,
    _tcsv_ints,
    _terr,
    _tfind_creature,
    _tinv,
    _tload_save,
    _tlog,
    _tmax_uid,
    _tok,
    _tnow,
    _tparse,
    _trade_lock,
    _tspace_full,
    _ttrade_refused,
    _tvalid_creature,
    _twrite_save,
)

trade_bp = Blueprint("trade_bp", __name__)


@trade_bp.route("/persist/trade_balanceDW/", methods=["POST"])
def TradeBalance():
    try:
        p = _tparse()
        pid = p.get("player_id")
        if not pid:
            return _terr("player_id required")
        with _trade_lock:
            row = _tbalance(pid, create=False)  # don't create rows on a plain read
            return _tok({"coins": int(row.coins) if row else 0})
    except Exception as e:
        db.session.rollback()
        return _terr(f"internal: {e}", 500)


@trade_bp.route("/persist/trade_syncDW/", methods=["POST"])
def TradeSync():
    """The trade changes this app has not seen yet, so it can show them without a restart."""
    try:
        p = _tparse()
        pid = p.get("player_id")
        if not pid:
            return _terr("player_id required")
        if _device_refused(Player.query.filter_by(username=str(pid)).first()):
            return _terr("this device is not linked to that account", 403)
        rows = TradeDelta.query.filter_by(username=pid, done_at=None).order_by(TradeDelta.id).all()
        return _tok(
            {
                "add": [json.loads(r.item_json) for r in rows if r.action == "add"],
                "remove": [
                    {"unique_id": r.unique_id, "creature_id": r.creature_id}
                    for r in rows
                    if r.action == "remove"
                ],
            }
        )
    except Exception as e:
        db.session.rollback()
        return _terr(f"internal: {e}", 500)


@trade_bp.route("/persist/trade_listDW/", methods=["POST"])
def TradeList():
    try:
        p = _tparse()
        refused = _ttrade_refused(p.get("player_id"))
        if refused:
            return _terr(refused, 403)
        if _client_too_old():
            return _terr("please update the game to keep playing", 426)
        pid = p.get("player_id")
        try:
            uid = int(p.get("unique_id"))
            price = int(p.get("price"))
        except Exception:
            return _terr("unique_id and integer price required")
        if not pid or price <= 0:
            return _terr("player_id and price>0 required")
        if price > 1000000:
            return _terr("the highest price is 1,000,000 trade coins")
        with _trade_lock:
            player = Player.query.filter_by(username=pid).first()
            if player is None:
                return _terr("player not found", 404)
            if TradeListing.query.filter_by(seller_id=pid, status="active").count() >= MARKET_CAP:
                return _terr(
                    "you can list up to %d creatures at a time. Take one off or wait for one to sell"
                    % MARKET_CAP
                )
            save = _tload_save(player)
            inv = _tinv(save)
            cre = _tfind_creature(inv, uid)
            if cre is None:
                return _terr("creature not in your inventory")
            if not _tvalid_creature(cre):
                return _terr("invalid creature")
            inv.remove(cre)
            _twrite_save(player, save)
            esc = TradeEscrow(
                player_id=pid,
                kind="creature",
                item_json=json.dumps(cre, ensure_ascii=False),
                created=_tnow(),
            )
            db.session.add(esc)
            db.session.flush()
            lst = TradeListing(
                seller_id=pid,
                escrow_id=esc.id,
                price_coins=price,
                status="active",
                created=_tnow(),
            )
            db.session.add(lst)
            db.session.flush()
            _tlog("list", pid, f"listing={lst.id} cre={cre.get('ID')} uid={uid} price={price}")
            db.session.commit()
            return _tok({"listing_id": lst.id})
    except Exception as e:
        db.session.rollback()
        return _terr(f"internal: {e}", 500)


@trade_bp.route("/persist/trade_browseDW/", methods=["POST"])
def TradeBrowse():
    try:
        p = _tparse()
        with _trade_lock:
            try:
                _market_expire()
            except Exception:
                db.session.rollback()
        if str(p.get("v") or "") == "2":
            return _tok(_market_page(p))
        try:
            start = max(1, int(p.get("startpos", 1)))
            end = int(p.get("endpos", 30))
        except Exception:
            start, end = 1, 30
        end = max(end, start)
        rows = (
            TradeListing.query.filter_by(status="active")
            .order_by(TradeListing.created.desc())
            .offset(start - 1)
            .limit(end - start + 1)
            .all()
        )
        out = []
        for lst in rows:
            esc = TradeEscrow.query.get(lst.escrow_id)
            item = json.loads(esc.item_json) if esc else {}
            out.append(
                {
                    "listing_id": lst.id,
                    "seller_id": PublicId(lst.seller_id, request.headers.get("Player-Id")),
                    "price": lst.price_coins,
                    "kind": esc.kind if esc else "creature",
                    "creature_id": item.get("ID"),
                    "star_rating": item.get("StarRating"),
                    "created": lst.created,
                }
            )
        return _tok(out)
    except Exception as e:
        return _terr(f"internal: {e}", 500)


@trade_bp.route("/persist/trade_buyDW/", methods=["POST"])
def TradeBuy():
    try:
        p = _tparse()
        refused = _ttrade_refused(p.get("player_id"))
        if refused:
            return _terr(refused, 403)
        if _client_too_old():
            return _terr("please update the game to keep playing", 426)
        pid = p.get("player_id")
        try:
            listing_id = int(p.get("listing_id"))
        except Exception:
            return _terr("listing_id required")
        if not pid:
            return _terr("player_id required")
        with _trade_lock:
            lst = TradeListing.query.filter_by(id=listing_id, status="active").first()
            if lst is None:
                return _terr("listing not available", 404)
            if lst.seller_id == pid:
                return _terr("cannot buy your own listing")
            buyer = Player.query.filter_by(username=pid).first()
            if buyer is None:
                return _terr("buyer not found", 404)
            bbal = _tbalance(pid, create=True)
            if int(bbal.coins) < int(lst.price_coins):
                return _terr("not enough trade coins")
            esc = TradeEscrow.query.get(lst.escrow_id)
            if esc is None:
                return _terr("escrow missing", 500)
            item = json.loads(esc.item_json)
            bsave = _tload_save(buyer)
            if _tspace_full(bsave, adding=1):
                return _terr("your inventory is full")
            binv = _tinv(bsave)
            item = dict(item)
            item["UniqueID"] = _tmax_uid(binv) + 1
            binv.append(item)
            _twrite_save(buyer, bsave)
            bbal.coins = int(bbal.coins) - int(lst.price_coins)
            bbal.updated = _tnow()
            sbal = _tbalance(lst.seller_id, create=True)
            sbal.coins = int(sbal.coins) + int(lst.price_coins)
            sbal.updated = _tnow()
            lst.status = "sold"
            lst.buyer_id = pid
            # Snapshot so the admin can revert this sale exactly.
            lst.item_json = json.dumps(item, ensure_ascii=False)
            lst.buyer_uid = item["UniqueID"]
            db.session.delete(esc)
            _tlog(
                "buy",
                pid,
                f"listing={listing_id} seller={lst.seller_id} price={lst.price_coins} cre={item.get('ID')}",
            )
            db.session.commit()
            return _tok({"listing_id": listing_id, "coins": int(bbal.coins)})
    except Exception as e:
        db.session.rollback()
        return _terr(f"internal: {e}", 500)


@trade_bp.route("/persist/trade_cancelDW/", methods=["POST"])
def TradeCancel():
    try:
        p = _tparse()
        if _device_refused(Player.query.filter_by(username=str(p.get("player_id"))).first()):
            return _terr("this device is not linked to that account", 403)
        if _client_too_old():
            return _terr("please update the game to keep playing", 426)
        pid = p.get("player_id")
        try:
            listing_id = int(p.get("listing_id"))
        except Exception:
            return _terr("listing_id required")
        with _trade_lock:
            lst = TradeListing.query.filter_by(id=listing_id, status="active").first()
            if lst is None:
                return _terr("listing not available", 404)
            if lst.seller_id != pid:
                return _terr("not your listing", 403)
            seller = Player.query.filter_by(username=pid).first()
            if seller is None:
                return _terr("player not found", 404)
            esc = TradeEscrow.query.get(lst.escrow_id)
            if esc is None:
                return _terr("escrow missing", 500)
            item = dict(json.loads(esc.item_json))
            ssave = _tload_save(seller)
            sinv = _tinv(ssave)
            item["UniqueID"] = _tmax_uid(sinv) + 1
            sinv.append(item)
            _twrite_save(seller, ssave)
            lst.status = "cancelled"
            db.session.delete(esc)
            _tlog("cancel", pid, f"listing={listing_id} cre={item.get('ID')}")
            db.session.commit()
            return _tok({"listing_id": listing_id})
    except Exception as e:
        db.session.rollback()
        return _terr(f"internal: {e}", 500)


@trade_bp.route("/persist/trade_buycoinsDW/", methods=["POST"])
def TradeBuyCoins():
    try:
        p = _tparse()
        refused = _ttrade_refused(p.get("player_id"))
        if refused:
            return _terr(refused, 403)
        if _client_too_old():
            return _terr("please update the game to keep playing", 426)
        pid = p.get("player_id")

        currency = str(p.get("currency") or "gems").strip().lower()
        if currency not in ("gems", "coins"):
            return _terr("currency must be gems or coins")

        want = p.get("pack", p.get("coins"))
        if want is not None:
            try:
                want = int(want)
            except Exception:
                return _terr("integer coins required")
        else:
            try:
                paid = int(p.get("gems"))
            except Exception:
                return _terr("integer gems required")
            currency = "gems"
            want = next((n for n, (g, c) in TRADE_PACKS.items() if g == paid), None)
        if want not in TRADE_PACKS:
            return _terr("that trade coin pack is not available")
        cost = TRADE_PACKS[want][0 if currency == "gems" else 1]
        credited_coins = want

        if not pid:
            return _terr("player_id required")
        if cost <= 0:
            return _terr("player_id and price>0 required")
        with _trade_lock:
            player = Player.query.filter_by(username=pid).first()
            if player is None:
                return _terr("player not found", 404)
            save = _tload_save(player)

            if currency == "gems":
                free = int(save.get("FreeHardCurrency", 0) or 0)
                paid = int(save.get("PaidHardCurrency", 0) or 0)
                if free + paid < cost:
                    return _terr("not enough gems")
                take_free = min(free, cost)
                take_paid = cost - take_free
                save["FreeHardCurrency"] = free - take_free
                save["PaidHardCurrency"] = paid - take_paid
            else:
                soft = int(save.get("SoftCurrency", 0) or 0)
                if soft < cost:
                    return _terr("not enough coins")
                save["SoftCurrency"] = soft - cost

            _twrite_save(player, save)
            bal = _tbalance(pid, create=True)
            bal.coins = int(bal.coins) + credited_coins
            bal.updated = _tnow()
            _tlog("buycoins", pid, f"{currency}={cost} credited={credited_coins}")
            db.session.commit()
            return _tok(
                {
                    "coins": int(bal.coins),
                    "credited": credited_coins,
                    "spent": cost,
                    "currency": currency,
                }
            )
    except Exception as e:
        db.session.rollback()
        return _terr(f"internal: {e}", 500)


@trade_bp.route("/persist/trade_offerDW/", methods=["POST"])
def TradeOfferCreate():
    try:
        p = _tparse()
        refused = _ttrade_refused(p.get("from_id"))
        if refused:
            return _terr(refused, 403)
        if _client_too_old():
            return _terr("please update the game to keep playing", 426)
        frm = p.get("from_id")
        to = RealId(p.get("to_id"))
        if not frm or not to or frm == to:
            return _terr("from_id and distinct to_id required")
        offer_uids = _tcsv_ints(p.get("offer_unique_ids"))
        req_uids = _tcsv_ints(p.get("request_unique_ids"))
        try:
            offer_coins = int(p.get("offer_coins", 0) or 0)
            request_coins = int(p.get("request_coins", 0) or 0)
        except Exception:
            return _terr("integer coins required")
        if offer_coins < 0 or request_coins < 0:
            return _terr("coins must be >= 0")
        if offer_coins > 1000000 or request_coins > 1000000:
            return _terr("the most you can trade is 1,000,000 trade coins")
        if not offer_uids and offer_coins == 0:
            return _terr("offer something")
        with _trade_lock:
            sender = Player.query.filter_by(username=frm).first()
            if sender is None or Player.query.filter_by(username=to).first() is None:
                return _terr("player not found", 404)
            sbal = _tbalance(frm, create=True)
            if offer_coins > 0 and int(sbal.coins) < offer_coins:
                return _terr("not enough trade coins to offer")
            save = _tload_save(sender)
            inv = _tinv(save)
            escrow_ids = []
            for uid in offer_uids:
                cre = _tfind_creature(inv, uid)
                if cre is None:
                    return _terr(f"creature {uid} not in your inventory")
                inv.remove(cre)
                esc = TradeEscrow(
                    player_id=frm,
                    kind="creature",
                    item_json=json.dumps(cre, ensure_ascii=False),
                    created=_tnow(),
                )
                db.session.add(esc)
                db.session.flush()
                escrow_ids.append(esc.id)
            _twrite_save(sender, save)
            if offer_coins > 0:
                sbal.coins = int(sbal.coins) - offer_coins
                sbal.updated = _tnow()
            offer = TradeOffer(
                from_id=frm,
                to_id=to,
                offer_json=json.dumps({"escrow_ids": escrow_ids, "coins": offer_coins}),
                request_json=json.dumps({"unique_ids": req_uids, "coins": request_coins}),
                status="pending",
                created=_tnow(),
            )
            db.session.add(offer)
            db.session.flush()
            _tlog(
                "offer",
                frm,
                f"offer={offer.id} to={to} give={escrow_ids}+{offer_coins}c want={req_uids}+{request_coins}c",
            )
            db.session.commit()
            return _tok({"offer_id": offer.id})
    except Exception as e:
        db.session.rollback()
        return _terr(f"internal: {e}", 500)


@trade_bp.route("/persist/trade_offers_receivedDW/", methods=["POST"])
def TradeOffersReceived():
    try:
        p = _tparse()
        pid = p.get("player_id")
        if not pid:
            return _terr("player_id required")
        rows = (
            TradeOffer.query.filter_by(to_id=pid, status="pending")
            .order_by(TradeOffer.created.desc())
            .all()
        )
        out = []
        for o in rows:
            offer = json.loads(o.offer_json)
            req = json.loads(o.request_json)
            gives = []
            for eid in offer.get("escrow_ids", []):
                esc = TradeEscrow.query.get(eid)
                if esc:
                    it = json.loads(esc.item_json)
                    gives.append(
                        {
                            "creature_id": it.get("ID"),
                            "star_rating": it.get("StarRating"),
                            "item": it,
                        }
                    )
            sender = Player.query.filter_by(username=o.from_id).first()
            out.append(
                {
                    "offer_id": o.id,
                    "from_id": PublicId(o.from_id, pid),
                    "from_name": getattr(sender, "multiplayer_name", None) or "",
                    "they_give": {"creatures": gives, "coins": offer.get("coins", 0)},
                    "they_want": {
                        "unique_ids": req.get("unique_ids", []),
                        "coins": req.get("coins", 0),
                    },
                    "created": o.created,
                }
            )
        return _tok(out)
    except Exception as e:
        return _terr(f"internal: {e}", 500)


@trade_bp.route("/persist/trade_inventoryDW/", methods=["POST"])
def TradeInventory():
    """The other player's tradeable creatures for the offer screen's Theirs tab."""
    try:
        args = _tparse()
        pid = RealId(args.get("player_id"))
        if not pid:
            return _terr("player_id required")
        player = Player.query.filter_by(username=pid).first()
        if player is None:
            return _terr("player not found", 404)
        save = _tload_save(player)
        busy = {str(save.get("MyHelperCreatureID"))}
        for lo in save.get("Loadouts") or []:
            if isinstance(lo, dict):
                busy.update(str(v) for k, v in lo.items() if k.startswith("CreatureID"))
        out = []
        for uid, it in _tcreatures(save).items():
            if (
                str(uid) in busy
                or str(it.get("Favorite")).lower() in ("1", "true")
                or not _tvalid_creature(it)
            ):
                continue
            try:
                star = int(it.get("StarRating") or 1)
            except Exception:
                star = 1
            try:
                xp = int(float(it.get("Xp") or 0))
            except Exception:
                xp = 0
            out.append(({"unique_id": uid, "creature_id": it.get("ID"), "star": star}, xp))
        out.sort(key=lambda o: (-o[0]["star"], -o[1]))
        total = len(out)
        if args.get("paged") != "1":
            out = out[:TRADE_INV_CAP]
        return _tok({"creatures": [o[0] for o in out], "total": total})
    except Exception as e:
        return _terr(f"internal: {e}", 500)


@trade_bp.route("/persist/trade_acceptDW/", methods=["POST"])
def TradeAccept():
    try:
        p = _tparse()
        refused = _ttrade_refused(p.get("player_id"))
        if refused:
            return _terr(refused, 403)
        if _client_too_old():
            return _terr("please update the game to keep playing", 426)
        pid = p.get("player_id")  # the accepter == to_id
        try:
            offer_id = int(p.get("offer_id"))
        except Exception:
            return _terr("offer_id required")
        with _trade_lock:
            o = TradeOffer.query.filter_by(id=offer_id, status="pending").first()
            if o is None:
                return _terr("offer not available", 404)
            if o.to_id != pid:
                return _terr("not your offer", 403)
            offer = json.loads(o.offer_json)
            req = json.loads(o.request_json)
            frm = o.from_id
            accepter = Player.query.filter_by(username=pid).first()
            sender = Player.query.filter_by(username=frm).first()
            if accepter is None or sender is None:
                return _terr("player not found", 404)
            asave = _tload_save(accepter)
            ainv = _tinv(asave)
            want_uids = req.get("unique_ids", [])
            want_coins = int(req.get("coins", 0))
            abal = _tbalance(pid, create=True)
            if int(abal.coins) < want_coins:
                return _terr("you don't have enough trade coins")
            wanted = []
            for uid in want_uids:
                cre = _tfind_creature(ainv, uid)
                if cre is None:
                    return _terr(f"you no longer have creature {uid}")
                wanted.append(cre)
            ssave = _tload_save(sender)
            sinv = _tinv(ssave)
            if _tspace_full(asave, adding=len(offer.get("escrow_ids", [])) - len(wanted)):
                return _terr("your inventory is full")
            if _tspace_full(ssave, adding=len(wanted)):
                return _terr("their inventory is full")
            for cre in wanted:
                ainv.remove(cre)
                cre2 = dict(cre)
                cre2["UniqueID"] = _tmax_uid(sinv) + 1
                sinv.append(cre2)
            sender_got = [dict(c) for c in sinv[-len(wanted):]] if wanted else []
            accepter_got = []
            for eid in offer.get("escrow_ids", []):
                esc = TradeEscrow.query.get(eid)
                if esc is None:
                    return _terr("escrow missing", 500)
                it = dict(json.loads(esc.item_json))
                it["UniqueID"] = _tmax_uid(ainv) + 1
                ainv.append(it)
                accepter_got.append(dict(it))
                db.session.delete(esc)
            offer_coins = int(offer.get("coins", 0))
            abal.coins = int(abal.coins) + offer_coins - want_coins
            abal.updated = _tnow()
            sbal = _tbalance(frm, create=True)
            sbal.coins = int(sbal.coins) + want_coins
            sbal.updated = _tnow()
            _twrite_save(accepter, asave)
            _twrite_save(sender, ssave)
            o.status = "accepted"
            # Snapshot so the admin can revert this trade exactly.
            o.revert_json = json.dumps(
                {
                    "sender": {"id": frm, "items": sender_got, "coins": want_coins},
                    "accepter": {"id": pid, "items": accepter_got, "coins": offer_coins},
                },
                ensure_ascii=False,
            )
            _tlog("accept", pid, f"offer={offer_id} from={frm}")
            db.session.commit()
            return _tok({"offer_id": offer_id})
    except Exception as e:
        db.session.rollback()
        return _terr(f"internal: {e}", 500)


@trade_bp.route("/persist/trade_declineDW/", methods=["POST"])
def TradeDecline():
    try:
        p = _tparse()
        if _device_refused(Player.query.filter_by(username=str(p.get("player_id"))).first()):
            return _terr("this device is not linked to that account", 403)
        if _client_too_old():
            return _terr("please update the game to keep playing", 426)
        pid = p.get("player_id")  # to_id declines, OR from_id cancels
        try:
            offer_id = int(p.get("offer_id"))
        except Exception:
            return _terr("offer_id required")
        with _trade_lock:
            o = TradeOffer.query.filter_by(id=offer_id, status="pending").first()
            if o is None:
                return _terr("offer not available", 404)
            if pid not in (o.to_id, o.from_id):
                return _terr("not your offer", 403)
            offer = json.loads(o.offer_json)
            sender = Player.query.filter_by(username=o.from_id).first()
            if sender is not None:
                ssave = _tload_save(sender)
                sinv = _tinv(ssave)
                for eid in offer.get("escrow_ids", []):
                    esc = TradeEscrow.query.get(eid)
                    if esc:
                        it = dict(json.loads(esc.item_json))
                        it["UniqueID"] = _tmax_uid(sinv) + 1
                        sinv.append(it)
                        db.session.delete(esc)
                _twrite_save(sender, ssave)
            sbal = _tbalance(o.from_id, create=True)
            sbal.coins = int(sbal.coins) + int(offer.get("coins", 0))
            sbal.updated = _tnow()
            o.status = "declined" if pid == o.to_id else "cancelled"
            _tlog(o.status, pid, f"offer={offer_id}")
            db.session.commit()
            return _tok({"offer_id": offer_id, "status": o.status})
    except Exception as e:
        db.session.rollback()
        return _terr(f"internal: {e}", 500)
