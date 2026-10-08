"""Admin curation for the Monthly Store: offer lists, buy limits, counters."""

from ._common import *
from app.models import MonthlyStorePurchase, Player
from app.services.monthly_store import (
    CONFIG_NAME,
    DEFAULT_BUY_LIMITS,
    STORE_TYPES,
    CurrentBuyLimits,
    LoadStoreConfig,
    MonthKey,
    OfferCatalog,
    ReseedStoreConfig,
    ResetBuyCounts,
    SaveStoreConfig,
)


def _player_names(ids):
    ids = {str(i) for i in ids if i}
    if not ids:
        return {}
    rows = Player.query.filter(Player.username.in_(ids)).all()
    return {r.username: (r.multiplayer_name or "Unnamed") for r in rows}


def _store_context(error=""):
    cfg = LoadStoreConfig()
    limits = CurrentBuyLimits(cfg)
    catalog = {store_type: OfferCatalog(store_type) for store_type in STORE_TYPES}

    selected = {}
    for store_type, spec in STORE_TYPES.items():
        monthly = set(cfg.get(spec["monthly_key"]) or [])
        specials = set(cfg.get(spec["special_key"]) or [])
        selected[store_type] = {
            "monthly": monthly,
            "special": specials,
            "total": len(monthly) + len(specials),
        }

    purchases = (
        MonthlyStorePurchase.query.order_by(MonthlyStorePurchase.updated_at.desc())
        .limit(100)
        .all()
    )
    names = _player_names(p.player_id for p in purchases)

    return {
        "error": error,
        "cfg": cfg,
        "limits": limits,
        "store_types": STORE_TYPES,
        "catalog": catalog,
        "selected": selected,
        "purchases": purchases,
        "player_names": names,
        "month_key": MonthKey(),
        "config_name": CONFIG_NAME,
        "default_limits": DEFAULT_BUY_LIMITS,
    }


def _form_config():
    """Build a config candidate from the posted ``sel_<type>_<offer>`` fields."""
    cfg = {"buy_limits": {}}
    for store_type, spec in STORE_TYPES.items():
        monthly, specials = [], []
        for row in OfferCatalog(store_type):
            mode = request.form.get(f"sel_{store_type}_{row['id']}", "").strip().lower()
            if mode == "monthly":
                monthly.append(row["id"])
            elif mode == "special":
                specials.append(row["id"])
        cfg[spec["monthly_key"]] = monthly
        cfg[spec["special_key"]] = specials

        raw_limit = request.form.get(f"limit_{store_type}")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = DEFAULT_BUY_LIMITS[store_type]
        cfg["buy_limits"][store_type] = limit
    return cfg


@admin_bp.route("/admin/monthly_store")
@login_required
def AdminMonthlyStore():
    if not isAdmin(current_user):
        return abort(404)

    return render_template("admin_monthly_store.html", **_store_context())


@admin_bp.route("/admin/monthly_store/save", methods=["POST"])
@login_required
def AdminMonthlyStoreSave():
    if not isAdmin(current_user):
        return abort(404)

    try:
        cfg = SaveStoreConfig(_form_config())
    except ValueError as e:
        return render_template("admin_monthly_store.html", **_store_context(str(e)))

    Log(
        "admin",
        current_user.username
        + " set monthly store: "
        + ", ".join(
            f"{spec['label']}={len(cfg[spec['monthly_key']])} monthly"
            f"+{len(cfg[spec['special_key']])} special"
            for spec in STORE_TYPES.values()
        )
        + f", limits={cfg['buy_limits']}",
    )
    DiscordWebhookMessage(
        f"**{current_user.username}** updated the Monthly Store offers "
        f"(limits: action {cfg['buy_limits']['action']}, "
        f"evo {cfg['buy_limits']['evo']})"
    )
    return redirect("/admin/monthly_store")


@admin_bp.route("/admin/monthly_store/reroll", methods=["POST"])
@login_required
def AdminMonthlyStoreReroll():
    if not isAdmin(current_user):
        return abort(404)

    cfg = ReseedStoreConfig()
    Log(
        "admin",
        current_user.username
        + " rerolled the monthly store rotation: "
        + ", ".join(
            f"{spec['label']}={cfg[spec['monthly_key']]}" for spec in STORE_TYPES.values()
        ),
    )
    return redirect("/admin/monthly_store")


@admin_bp.route("/admin/monthly_store/reset_counts", methods=["POST"])
@login_required
def AdminMonthlyStoreResetCounts():
    if not isAdmin(current_user):
        return abort(404)

    player_id = (request.form.get("player_id") or "").strip()
    store_type = (request.form.get("store_type") or "").strip()
    if store_type not in STORE_TYPES:
        store_type = ""

    removed = ResetBuyCounts(player_id=player_id, store_type=store_type)
    Log(
        "admin",
        current_user.username
        + f" reset monthly store buy counts ({removed} rows"
        + (f", player {player_id}" if player_id else "")
        + (f", {store_type}" if store_type else "")
        + ")",
    )
    return redirect("/admin/monthly_store#purchases")
