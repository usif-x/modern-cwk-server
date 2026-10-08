"""Monthly Store: offer lists, per-player buy counters and admin curation.

``GET /persist/static/monthly_store?player_id=...`` tells the app which offers
are up this month plus how many of them the player already bought, and
``POST /persist/static/monthly_store/buy`` records one more purchase and
charges the save (the save is the wallet).

Which offers are featured lives in one ``MonthlyStoreConfig`` row so an admin
can curate it (seeded with a random rotation the first time it is read); the
counters live in ``MonthlyStorePurchase`` so a client save upload cannot reset
them. The counters reset every month, the lists only when the admin changes
them.
"""

import random
import time

from ._common import *
from app.models import MonthlyStoreConfig, MonthlyStorePurchase
from app.services.game_data import FormatBlueprintName, GetActionCardNameMap, Log

CONFIG_ROW = 1
# Optional hand-written override, read once when no config row exists yet.
CONFIG_PATH = os.path.join(ROOT_DIR, "data/persist", "monthly_store.json")

# store_type -> label, blueprint, how many monthly slots the app renders, the
# config keys the offer lists live under and the price currency. "gems" and
# "PvpCurrency" are the strings the buy reply has to report back.
STORE_TYPES = {
    "action": {
        "label": "Action cards",
        "blueprint": "db_StoreBuyActionCards.json",
        "size": 6,
        "monthly_key": "action_cards",
        "special_key": "action_card_special",
        "currency": "gems",
        "bucket": "gems",
    },
    "evo": {
        "label": "Evolution materials",
        "blueprint": "db_StoreBuyEvoMaterials.json",
        "size": 4,
        "monthly_key": "evo_materials",
        "special_key": "evo_special",
        "currency": "PvpCurrency",
        "bucket": "pvp",
    },
}

DEFAULT_BUY_LIMITS = {"action": 3, "evo": 1}

_rows_cache = {}
_ROWS_TTL = 300


def _now():
    return int(time.time())


def MonthKey():
    """``YYYY-MM`` - buy counters reset with the month, like production."""
    now = datetime.now(timezone.utc)
    return f"{now.year}-{now.month:02d}"


def _uniq(values):
    if not isinstance(values, (list, tuple)):
        values = [] if values in (None, "") else [values]
    return list(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))


def _IsSpecialRow(row):
    raw = row.get("IsSpecial", False)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() == "true"


def OfferRows(store_type):
    """Every offer row of one store type straight from its blueprint."""
    spec = STORE_TYPES[store_type]
    cached = _rows_cache.get(store_type)
    if cached and time.time() - cached[0] < _ROWS_TTL:
        return cached[1]

    path = os.path.join(ROOT_DIR, "data/persist/Blueprints", spec["blueprint"])
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            raw = raw.get("data", [])
        rows = [
            r
            for r in (raw if isinstance(raw, list) else [])
            if isinstance(r, dict) and r.get("ID")
        ]
    except Exception as e:
        Log("admin", f"Monthly store: cannot read {spec['blueprint']}: {e}")

    _rows_cache[store_type] = (time.time(), rows)
    return rows


def OfferExists(store_type, offer_id):
    return str(offer_id) in {str(r.get("ID")) for r in OfferRows(store_type)}


def OfferPrice(store_type, offer_id):
    """``{cost, quantity, currency, bucket, item_id}`` for one offer."""
    if store_type not in STORE_TYPES:
        return None
    spec = STORE_TYPES[store_type]
    for row in OfferRows(store_type):
        if str(row.get("ID")) != str(offer_id):
            continue
        try:
            cost = max(0, int(row.get("BuyCost")))
        except (TypeError, ValueError):
            cost = 0
        try:
            quantity = max(1, int(row.get("Quantity")))
        except (TypeError, ValueError):
            quantity = 1
        return {
            "cost": cost,
            "quantity": quantity,
            "currency": spec["currency"],
            "bucket": spec["bucket"],
            "item_id": str(row.get("CardID") or row.get("EvoMaterialID") or ""),
        }
    return None


def _offer_name(store_type, row):
    """Readable offer name: card/material name, falling back to the ID."""
    card_map = GetActionCardNameMap() if store_type == "action" else None
    ident = str(row.get("CardID") or row.get("EvoMaterialID") or "")
    if card_map and ident in card_map:
        return card_map[ident]

    name = row.get("Name") or ""
    if name and not (name.startswith("!!") and name.endswith("_NAME")):
        return FormatBlueprintName(name)
    texture = str(row.get("UITexture") or "")
    for prefix in ("UI/Icons_Materials/", "Spell_", "Spel_"):
        if texture.startswith(prefix):
            texture = texture[len(prefix) :]
            break
    if texture:
        return FormatBlueprintName(texture)
    return ident or str(row.get("ID") or "")


def OfferCatalog(store_type):
    """Every offer of a type with display names, for the admin panel."""
    out = []
    for row in OfferRows(store_type):
        out.append(
            {
                "id": str(row.get("ID")),
                "name": _offer_name(store_type, row),
                "cost": safe_offer_int(row.get("BuyCost")),
                "quantity": safe_offer_int(row.get("Quantity"), 1),
                "blueprint_special": _IsSpecialRow(row),
            }
        )
    return out


def safe_offer_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _seed_config():
    """A fresh rotation: as many monthly offers as the app has slots, plus
    whatever the blueprint already marks as a permanent special."""
    cfg = {"buy_limits": dict(DEFAULT_BUY_LIMITS)}
    for store_type, spec in STORE_TYPES.items():
        rows = OfferRows(store_type)
        pool = [str(r["ID"]) for r in rows if not _IsSpecialRow(r)]
        specials = [str(r["ID"]) for r in rows if _IsSpecialRow(r)]
        count = min(spec["size"], len(pool))
        cfg[spec["monthly_key"]] = random.sample(pool, count) if count else []
        cfg[spec["special_key"]] = specials
    return cfg


def _normalize_config(cfg):
    clean, _ = ValidateStoreConfig(cfg, strict=False)
    return clean


def _read_config_file():
    """A hand-written ``data/persist/monthly_store.json``, if one exists."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except ValueError as e:
        Log("admin", f"Monthly store: broken monthly_store.json ({e})")
        return None
    return data if isinstance(data, dict) else None


def _write_config(cfg):
    """Upsert the single config row (the admin's curation)."""
    row = MonthlyStoreConfig.query.filter_by(id=CONFIG_ROW).first()
    payload = json.dumps(cfg, ensure_ascii=False, sort_keys=True)
    if row is None:
        row = MonthlyStoreConfig(id=CONFIG_ROW, data=payload)
        db.session.add(row)
    else:
        row.data = payload
    db.session.commit()
    return cfg


def LoadStoreConfig():
    """The stored offer lists, seeded (and stored) the first time."""
    row = MonthlyStoreConfig.query.filter_by(id=CONFIG_ROW).first()
    if row is not None:
        try:
            data = json.loads(row.data or "{}")
        except ValueError as e:
            Log("admin", f"Monthly store: broken config row ({e}) - reseeding")
            data = None
        if isinstance(data, dict):
            return _normalize_config(data)

    # First run: take a hand-written override if there is one, else pick a
    # fresh rotation and store it so the admin page shows what was chosen.
    cfg = _read_config_file()
    if not isinstance(cfg, dict):
        cfg = _seed_config()
    clean = _normalize_config(cfg)
    try:
        _write_config(clean)
    except Exception as e:
        Log("admin", f"Monthly store: cannot store the initial config: {e}")
        db.session.rollback()
    return clean


def SaveStoreConfig(cfg):
    """Validate and write the offer lists. Raises ``ValueError`` on bad input."""
    clean, errors = ValidateStoreConfig(cfg, strict=True)
    if errors:
        raise ValueError(errors[0])
    return _write_config(clean)


def ReseedStoreConfig():
    """A new random rotation (admin "reroll"). Keeps the buy limits."""
    cfg = _seed_config()
    cfg["buy_limits"] = CurrentBuyLimits()
    return SaveStoreConfig(cfg)


def ValidateStoreConfig(raw, strict=True):
    """Coerce a candidate config into shape; returns ``(clean, errors)``.

    ``strict`` reports the problems an admin has to fix (wrong ids, wrong
    number of slots); without it only unusable values are corrected.
    """
    raw = raw if isinstance(raw, dict) else {}
    errors = []
    clean = {}

    for store_type, spec in STORE_TYPES.items():
        known = {str(r.get("ID")) for r in OfferRows(store_type)}
        monthly = _uniq(raw.get(spec["monthly_key"]))
        specials = _uniq(raw.get(spec["special_key"]))

        if strict:
            unknown = [i for i in monthly + specials if i not in known]
            if unknown:
                errors.append(
                    f"{spec['label']}: not in {spec['blueprint']}: "
                    + ", ".join(unknown[:5])
                    + ("..." if len(unknown) > 5 else "")
                )
            overlap = [i for i in monthly if i in set(specials)]
            if overlap:
                errors.append(
                    f"{spec['label']}: offer can be monthly or special, not both: "
                    + ", ".join(overlap)
                )
            if len(monthly) != spec["size"]:
                errors.append(
                    f"{spec['label']}: pick exactly {spec['size']} monthly offers "
                    f"(got {len(monthly)})."
                )

        clean[spec["monthly_key"]] = monthly
        clean[spec["special_key"]] = specials

    raw_limits = raw.get("buy_limits")
    raw_limits = raw_limits if isinstance(raw_limits, dict) else {}
    limits = {}
    for store_type in STORE_TYPES:
        try:
            limit = int(raw_limits.get(store_type, DEFAULT_BUY_LIMITS[store_type]))
        except (TypeError, ValueError):
            limit = DEFAULT_BUY_LIMITS[store_type]
        if strict and (limit < 1 or limit > 99):
            errors.append(f"Buy limit for {store_type} must be between 1 and 99.")
            limit = min(99, max(1, limit))
        limits[store_type] = min(99, max(1, limit))
    clean["buy_limits"] = limits

    return clean, errors


def CurrentBuyLimits(cfg=None):
    cfg = cfg if isinstance(cfg, dict) else LoadStoreConfig()
    limits = cfg.get("buy_limits") if isinstance(cfg.get("buy_limits"), dict) else {}
    out = {}
    for store_type in STORE_TYPES:
        try:
            out[store_type] = int(limits.get(store_type, DEFAULT_BUY_LIMITS[store_type]))
        except (TypeError, ValueError):
            out[store_type] = DEFAULT_BUY_LIMITS[store_type]
    return out


def OffersInRotation(cfg, store_type, offer_id):
    spec = STORE_TYPES[store_type]
    offer_id = str(offer_id)
    return offer_id in set(cfg.get(spec["monthly_key"]) or []) or offer_id in set(
        cfg.get(spec["special_key"]) or []
    )


def GetBuyCounts(player_id, store_type, offer_ids):
    """``{offer_id: bought this month}`` for one player."""
    offer_ids = [str(i) for i in _uniq(offer_ids)]
    out = {oid: 0 for oid in offer_ids}
    if not player_id or not out:
        return out
    rows = MonthlyStorePurchase.query.filter_by(
        player_id=str(player_id),
        store_type=store_type,
        month_key=MonthKey(),
    ).all()
    for row in rows:
        if row.offer_id in out:
            out[row.offer_id] = int(row.buy_count or 0)
    return out


def GetBuyCount(player_id, store_type, offer_id):
    return GetBuyCounts(player_id, store_type, [offer_id]).get(str(offer_id), 0)


def IncrementBuyCount(player_id, store_type, offer_id):
    """Count one purchase. Returns ``(ok, {buy_count, buy_limit, error?})``."""
    limit = CurrentBuyLimits().get(store_type, DEFAULT_BUY_LIMITS.get(store_type, 1))
    month_key = MonthKey()
    row = MonthlyStorePurchase.query.filter_by(
        player_id=str(player_id),
        store_type=store_type,
        offer_id=str(offer_id),
        month_key=month_key,
    ).first()
    current = int(row.buy_count or 0) if row is not None else 0

    if current >= limit:
        return False, {
            "buy_count": current,
            "buy_limit": limit,
            "error": "BUY_LIMIT_REACHED",
        }

    if row is None:
        row = MonthlyStorePurchase(
            player_id=str(player_id),
            store_type=store_type,
            offer_id=str(offer_id),
            month_key=month_key,
            buy_count=current + 1,
        )
        db.session.add(row)
    else:
        row.buy_count = current + 1
        row.updated_at = _now()
    db.session.commit()
    return True, {"buy_count": row.buy_count, "buy_limit": limit}


def ResetBuyCounts(player_id="", store_type=""):
    """Drop counters (all, or one player / one store). Returns rows removed."""
    query = MonthlyStorePurchase.query
    if player_id:
        query = query.filter_by(player_id=str(player_id))
    if store_type:
        query = query.filter_by(store_type=store_type)
    rows = query.all()
    for row in rows:
        db.session.delete(row)
    db.session.commit()
    return len(rows)


def MonthlyStoreResponse(player_id):
    """The payload the app expects from GET /persist/static/monthly_store."""
    cfg = LoadStoreConfig()
    return {
        "success": True,
        "action_cards": cfg["action_cards"],
        "action_card_special": cfg["action_card_special"],
        "evo_materials": cfg["evo_materials"],
        "evo_special": cfg["evo_special"],
        "buy_counts": {
            "action": GetBuyCounts(
                player_id,
                "action",
                cfg["action_cards"] + cfg["action_card_special"],
            ),
            "evo": GetBuyCounts(
                player_id,
                "evo",
                cfg["evo_materials"] + cfg["evo_special"],
            ),
        },
        "buy_limits": {
            "action": cfg["buy_limits"]["action"],
            "evo": cfg["buy_limits"]["evo"],
        },
    }
