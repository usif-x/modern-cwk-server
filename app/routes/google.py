"""Google account linking, recovery and sign-in (ported from the production server).

Two flavours:
  * token endpoints  - the game proves a Google ID token directly (`/link`,
    `/login`, `/status`, `/unlink`, `/token`).
  * browser OAuth    - `/begin` opens a ticket and hands back an auth URL; Google
    returns to `/callback`; the game polls `/poll` until it is done. `/create`
    starts a brand-new player for a verified Google account.
"""

import json
import secrets
import threading
import time
import uuid
from urllib.parse import urlencode

from flask import Blueprint, jsonify, make_response, redirect, request

from app import db
from app.models import AccountLink, Player
from app.utils import (
    IPFromRequest, InvalidUsername, IsUserBanned, PlayerLog, ReadMiscParam, safe_int,
)

google_bp = Blueprint("google_bp", __name__)

_GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

GSIGN_IOS_RETURN = "cwkrevived://google-done"
GSIGN_TTL = 600  # 10 minutes; a pending sign-in should never outlive that


def GoogleClientIds():
    """Client IDs the game's ID tokens may be issued for (audience check)."""
    import os

    raw = os.environ.get("CWK_GOOGLE_CLIENT_IDS", "")
    ids = [c.strip() for c in raw.split(",") if c.strip()]
    web = GoogleWebClientId()
    if web and web not in ids:
        ids.append(web)
    return ids


def GoogleWebClientId():
    import os

    return (os.environ.get("CWK_GOOGLE_WEB_CLIENT_ID") or "").strip()


def GoogleWebClientSecret():
    import os

    return (os.environ.get("CWK_GOOGLE_WEB_CLIENT_SECRET") or "").strip()


def GoogleLinkGems():
    """Gems the town 'Link Google' banner may still pay (0 = hide it)."""
    return safe_int(ReadMiscParam("GoogleLinkGems"), 500) or 500


# --------------------------------------------------------------------------
# token verification
# --------------------------------------------------------------------------


def _google_verify_token(id_token_str):
    """Return the verified claims dict, or None. NEVER trusts the caller."""
    if not id_token_str or len(id_token_str) > 8192:
        return None

    # Preferred: local signature verification via Google's own library.
    try:
        from google.auth.transport import requests as _greq
        from google.oauth2 import id_token as _gid

        gclaims = _gid.verify_oauth2_token(id_token_str, _greq.Request())
        if gclaims.get("iss") not in _GOOGLE_ISSUERS:
            return None
        if not GoogleClientIds() or gclaims.get("aud") not in GoogleClientIds():
            return None
        return gclaims
    except ImportError:
        pass  # library not on this host - use the HTTPS fallback below
    except Exception:
        return None  # present but rejected the token: genuinely invalid

    # Fallback: ask Google directly. Needs no third-party package.
    try:
        import urllib.request

        url = "https://oauth2.googleapis.com/tokeninfo?" + urlencode({"id_token": id_token_str})
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.status != 200:
                return None
            gclaims = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    if gclaims.get("iss") not in _GOOGLE_ISSUERS:
        return None
    if not GoogleClientIds() or gclaims.get("aud") not in GoogleClientIds():
        return None
    try:
        if int(gclaims.get("exp", 0)) <= int(time.time()):
            return None
    except Exception:
        return None
    if not gclaims.get("sub"):
        return None
    return gclaims


def _google_claims_from_request():
    body = request.get_json(silent=True) or {}
    tok = body.get("id_token") or request.form.get("id_token") or ""
    return _google_verify_token(tok)


def _device_refused(player):
    """Same bar as a save write: the device header must match the bound device."""
    if player is None or not player.devicename:
        return False
    dev = request.headers.get("X-Nick-Description")
    if dev is None or dev == player.devicename:
        return False
    return True


def _BindDevice(username, dev):
    if not dev:
        return
    player = Player.query.filter_by(username=username).first()
    if player is not None and not player.devicename:
        player.devicename = dev
        db.session.commit()


def GetGoogleEmail(username):
    link = AccountLink.query.filter_by(provider="google", username=username).first()
    return None if link is None else (link.email or "(linked, no email)")


def GetGoogleSub(username):
    link = AccountLink.query.filter_by(provider="google", username=username).first()
    return link.provider_sub if link else None


# --------------------------------------------------------------------------
# account-creation throttle (per IP)
# --------------------------------------------------------------------------

_new_account_creations = {}
_NEW_ACCOUNT_MAX = 20
_NEW_ACCOUNT_WINDOW = 600


def _IsAccountCreationThrottled(ip):
    key = ip or "unknown"
    now = time.time()
    recent = [t for t in _new_account_creations.get(key, []) if now - t < _NEW_ACCOUNT_WINDOW]
    _new_account_creations[key] = recent
    return len(recent) >= _NEW_ACCOUNT_MAX


def _RecordAccountCreation(ip):
    key = ip or "unknown"
    now = time.time()
    recent = [t for t in _new_account_creations.get(key, []) if now - t < _NEW_ACCOUNT_WINDOW]
    recent.append(now)
    _new_account_creations[key] = recent


def _google_new_player(sub, email):
    """A brand-new player owned by this Google account. Returns (status, error, username)."""
    client_ip = IPFromRequest(request)
    if _IsAccountCreationThrottled(client_ip):
        return "error", "Too many new accounts from this address. Please try again later.", None
    new_username = str(uuid.uuid4())
    db.session.add(Player(username=new_username))
    db.session.add(
        AccountLink(
            provider="google",
            provider_sub=sub,
            username=new_username,
            email=email,
            linked_at=int(time.time()),
        )
    )
    db.session.commit()
    _RecordAccountCreation(client_ip)
    PlayerLog(ip=client_ip, player=new_username, message="Created new player via Google sign-in")
    return "ok", None, new_username


# --------------------------------------------------------------------------
# token endpoints (the game proves a Google ID token directly)
# --------------------------------------------------------------------------


@google_bp.route("/account/google/link", methods=["POST"])
def AccountGoogleLink():
    """Attach a Google account to the caller's EXISTING player."""
    username = request.headers.get("Player-Id")
    if not username or InvalidUsername(username):
        return jsonify({"ok": False, "error": "Invalid Username!"}), 400
    if IsUserBanned(username, IPFromRequest(request)):
        return jsonify({"ok": False, "error": "User is banned!"}), 400

    player = Player.query.filter_by(username=username).first()
    if player is None:
        return jsonify({"ok": False, "error": "No such player"}), 404
    if _device_refused(player):
        return jsonify({"ok": False, "error": "Invalid Username!"}), 400

    gclaims = _google_claims_from_request()
    if gclaims is None:
        return jsonify({"ok": False, "error": "Google sign-in could not be verified"}), 401

    sub = gclaims["sub"]
    existing = AccountLink.query.filter_by(provider="google", provider_sub=sub).first()
    if existing is not None:
        if existing.username == username:
            return jsonify({"ok": True, "already": True, "username": username})
        return jsonify(
            {"ok": False, "error": "That Google account is already linked to another player."}
        ), 409

    if AccountLink.query.filter_by(provider="google", username=username).first() is not None:
        return jsonify(
            {"ok": False, "error": "This player already has a Google account linked."}
        ), 409

    db.session.add(
        AccountLink(
            provider="google",
            provider_sub=sub,
            username=username,
            email=gclaims.get("email"),
            linked_at=int(time.time()),
        )
    )
    db.session.commit()
    PlayerLog(ip=IPFromRequest(request), player=username, message="Linked a Google account")
    return jsonify({"ok": True, "username": username})


@google_bp.route("/account/google/login", methods=["POST"])
def AccountGoogleLogin():
    """Recovery: prove a Google account, get the linked player id back."""
    gclaims = _google_claims_from_request()
    if gclaims is None:
        return jsonify({"ok": False, "error": "Google sign-in could not be verified"}), 401

    link = AccountLink.query.filter_by(provider="google", provider_sub=gclaims["sub"]).first()
    if link is None:
        return jsonify(
            {"ok": False, "error": "No player is linked to that Google account.", "linked": False}
        ), 404
    if IsUserBanned(link.username, IPFromRequest(request)):
        return jsonify({"ok": False, "error": "User is banned!"}), 400

    PlayerLog(ip=IPFromRequest(request), player=link.username, message="Recovered account via Google")
    _BindDevice(link.username, request.headers.get("X-Nick-Description"))
    return jsonify({"ok": True, "linked": True, "username": link.username})


@google_bp.route("/account/google/status", methods=["GET", "POST"])
def AccountGoogleStatus():
    """Which Google account (if any) this player is linked to."""
    username = request.headers.get("Player-Id")
    if not username or InvalidUsername(username):
        return jsonify({"ok": False, "error": "Invalid Username!"}), 400
    player = Player.query.filter_by(username=username).first()
    if player is None:
        return jsonify({"ok": False, "error": "No such player"}), 404
    if _device_refused(player):
        return jsonify({"ok": False, "error": "Invalid Username!"}), 400

    link = AccountLink.query.filter_by(provider="google", username=username).first()
    if link is None:
        return jsonify({"ok": True, "linked": False, "reward": GoogleLinkGems(), "relink": False})
    return jsonify(
        {
            "ok": True,
            "linked": True,
            "email": link.email or "",
            "linked_at": link.linked_at or 0,
            "reward": 0,
        }
    )


@google_bp.route("/account/google/unlink", methods=["POST"])
def AccountGoogleUnlink():
    """Players CHANGE their Google account instead of unlinking. An admin removes
    a lost one from the player page."""
    return jsonify({"ok": False, "error": "Use Change Google account in Settings."}), 410


# --------------------------------------------------------------------------
# browser OAuth flow
# --------------------------------------------------------------------------

_gsign_tickets = {}
_gsign_lock = threading.Lock()


def _gsign_sweep():
    now = time.time()
    for k in [k for k, v in _gsign_tickets.items() if now - v["created"] > GSIGN_TTL]:
        _gsign_tickets.pop(k, None)


def _gsign_page(title, message):
    """Small self-contained page. Only server-supplied strings are shown."""
    return (
        "<!doctype html><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Card Wars Kingdom</title>"
        "<body style=\"margin:0;min-height:100vh;display:flex;align-items:center;"
        "justify-content:center;background:#12161f;color:#eaeef7;"
        "font:16px/1.5 -apple-system,Segoe UI,Roboto,sans-serif\">"
        "<div style='text-align:center;padding:24px;max-width:22rem'>"
        "<div style='font-size:1.3rem;font-weight:600;margin-bottom:.4rem'>" + title + "</div>"
        "<div style='opacity:.75'>" + message + "</div></div>"
    )


def _gsign_auth_url(ticket):
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": GoogleWebClientId(),
            "redirect_uri": request.url_root.rstrip("/") + "/account/google/callback",
            "response_type": "code",
            "scope": "openid email profile",
            "state": ticket,
            "access_type": "online",
            "prompt": "select_account",
            "hl": "en",
        }
    )


def _gsign_end(entry, title, message):
    if entry.get("native") == "ios":
        return redirect(GSIGN_IOS_RETURN)
    return _gsign_page(title, message)


def _google_relink(entry, username, sub, email):
    """Change a player's Google account in two browser steps on one ticket."""
    mine = AccountLink.query.filter_by(provider="google", username=username).first()
    if mine is None:
        return "error", "No Google account is linked to this player.", None, False, False
    if entry.get("stage", 1) == 1:
        if mine.provider_sub != sub:
            return (
                "error",
                "That isn't the Google account linked to this player. Choose the one you linked before.",
                None,
                False,
                False,
            )
        with _gsign_lock:
            entry["stage"] = 2
        return "pending", None, None, False, True
    if sub == mine.provider_sub:
        return "ok", None, username, True, False
    if AccountLink.query.filter_by(provider="google", provider_sub=sub).first() is not None:
        return "error", "That Google account is already linked to another player.", None, False, False
    mine.provider_sub = sub
    mine.email = email
    mine.linked_at = int(time.time())
    db.session.commit()
    PlayerLog(ip="", player=username, message="Changed their linked Google account")
    return "ok", None, username, False, False


def _gsign_apply(entry, gclaims):
    """Link / look up / change for a verified Google identity. Returns 'ok', 'error'
    or 'next' (change account: pick the new one)."""
    sub = gclaims["sub"]
    username = entry["username"]
    mode = entry["mode"]
    entry_already = False
    next_step = False

    try:
        if mode == "relink":
            (
                entry_status,
                entry_error,
                entry_result,
                entry_already,
                next_step,
            ) = _google_relink(entry, username, sub, gclaims.get("email"))
        elif mode == "signin":
            link = AccountLink.query.filter_by(provider="google", provider_sub=sub).first()
            if link is not None:
                if IsUserBanned(link.username, IPFromRequest(request)):
                    entry_status, entry_error, entry_result = "error", "User is banned!", None
                else:
                    entry_status, entry_error, entry_result = "ok", None, link.username
                    PlayerLog(
                        ip=IPFromRequest(request), player=link.username, message="Signed in with Google"
                    )
            else:
                entry_status, entry_error, entry_result = _google_new_player(sub, gclaims.get("email"))
        elif mode == "restore":
            link = AccountLink.query.filter_by(provider="google", provider_sub=sub).first()
            if link is None:
                entry_status, entry_error, entry_result = (
                    "error",
                    "No player is linked to that Google account yet.",
                    None,
                )
                with _gsign_lock:
                    entry["new_sub"] = sub
                    entry["new_email"] = gclaims.get("email")
            elif IsUserBanned(link.username, IPFromRequest(request)):
                entry_status, entry_error, entry_result = "error", "User is banned!", None
            else:
                entry_status, entry_error, entry_result = "ok", None, link.username
                PlayerLog(
                    ip=IPFromRequest(request), player=link.username, message="Recovered account via Google"
                )
        else:
            existing = AccountLink.query.filter_by(provider="google", provider_sub=sub).first()
            mine = AccountLink.query.filter_by(provider="google", username=username).first()
            if existing is not None and existing.username != username:
                entry_status, entry_error, entry_result = (
                    "error",
                    "That Google account is already linked to another player.",
                    None,
                )
            elif existing is not None:
                entry_status, entry_error, entry_result = "ok", None, username
                entry_already = True
            elif mine is not None:
                entry_status, entry_error, entry_result = (
                    "error",
                    "This player already has a Google account linked.",
                    None,
                )
            else:
                db.session.add(
                    AccountLink(
                        provider="google",
                        provider_sub=sub,
                        username=username,
                        email=gclaims.get("email"),
                        linked_at=int(time.time()),
                    )
                )
                db.session.commit()
                PlayerLog(
                    ip=IPFromRequest(request), player=username, message="Linked a Google account"
                )
                entry_status, entry_error, entry_result = "ok", None, username
    except Exception as e:
        db.session.rollback()
        entry_status, entry_error, entry_result = "error", str(e), None

    if next_step:
        return "next"

    with _gsign_lock:
        entry["status"] = entry_status
        entry["error"] = entry_error
        entry["result"] = entry_result
        entry["email"] = gclaims.get("email") if entry_status == "ok" else None
        entry["already"] = entry_already

    if entry_status == "ok":
        if mode in ("signin", "restore"):
            _BindDevice(entry_result, entry.get("device"))
        return "ok"
    return "error"


@google_bp.route("/account/google/begin", methods=["POST"])
def AccountGoogleBegin():
    """Start a sign-in. Proves the caller owns the player the same way a save write does."""
    if not GoogleWebClientId() or not GoogleWebClientSecret():
        return jsonify({"ok": False, "configured": False}), 503

    body = request.get_json(silent=True) or {}
    mode = body.get("mode") or request.args.get("mode") or "link"
    if mode not in ("link", "restore", "signin", "relink"):
        return jsonify({"ok": False, "error": "bad mode"}), 400

    username = None
    if mode in ("link", "relink"):
        username = request.headers.get("Player-Id")
        if not username or InvalidUsername(username):
            return jsonify({"ok": False, "error": "Invalid Username!"}), 400
        if IsUserBanned(username, IPFromRequest(request)):
            return jsonify({"ok": False, "error": "User is banned!"}), 400
        player = Player.query.filter_by(username=username).first()
        if player is None:
            return jsonify({"ok": False, "error": "No such player"}), 404
        if _device_refused(player):
            return jsonify({"ok": False, "error": "Invalid Username!"}), 400
        if (
            mode == "relink"
            and AccountLink.query.filter_by(provider="google", username=username).first() is None
        ):
            return jsonify({"ok": False, "error": "No Google account is linked yet."}), 409

    ticket = secrets.token_urlsafe(24)
    with _gsign_lock:
        _gsign_sweep()
        _gsign_tickets[ticket] = {
            "mode": mode,
            "username": username,
            "device": request.headers.get("X-Nick-Description"),
            "created": time.time(),
            "status": "pending",
            "result": None,
            "error": None,
            "stage": 1,
            "native": body.get("native") if body.get("native") in ("android", "ios") else None,
        }
    return jsonify(
        {
            "ok": True,
            "ticket": ticket,
            "client_id": GoogleWebClientId(),
            "auth_url": _gsign_auth_url(ticket),
        }
    )


@google_bp.route("/account/google/start")
def AccountGoogleStart():
    ticket = request.args.get("ticket", "")
    with _gsign_lock:
        _gsign_sweep()
        entry = _gsign_tickets.get(ticket)
    if entry is None:
        return make_response(_gsign_page("Link expired", "Go back to the game and try again."), 400)
    return redirect(_gsign_auth_url(ticket))


@google_bp.route("/account/google/callback")
def AccountGoogleCallback():
    """Google sends the player back here. Everything secret happens server-side."""
    ticket = request.args.get("state", "")
    with _gsign_lock:
        _gsign_sweep()
        entry = _gsign_tickets.get(ticket)
    if entry is None:
        return make_response(_gsign_page("Link expired", "Go back to the game and try again."), 400)

    if request.args.get("error"):
        with _gsign_lock:
            entry["status"] = "error"
            entry["error"] = "Sign-in was cancelled."
        return _gsign_end(entry, "Sign-in cancelled", "You can close this tab.")

    code = request.args.get("code", "")
    if not code:
        with _gsign_lock:
            entry["status"] = "error"
            entry["error"] = "Google did not return a sign-in."
        return _gsign_end(entry, "Something went wrong", "Go back to the game and try again.")

    try:
        import urllib.request

        payload = urlencode(
            {
                "client_id": GoogleWebClientId(),
                "client_secret": GoogleWebClientSecret(),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": request.url_root.rstrip("/") + "/account/google/callback",
            }
        ).encode("utf-8")
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=payload)
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_data = json.loads(resp.read().decode("utf-8"))
        id_token_str = token_data.get("id_token")
    except Exception:
        id_token_str = None

    gclaims = _google_verify_token(id_token_str) if id_token_str else None
    if gclaims is None:
        with _gsign_lock:
            entry["status"] = "error"
            entry["error"] = "Google sign-in could not be verified."
        return _gsign_end(entry, "Couldn't verify that", "Go back to the game and try again.")

    outcome = _gsign_apply(entry, gclaims)
    if outcome == "next":
        return _gsign_page(
            "Now choose your new Google account",
            "<a href='/account/google/start?ticket=" + ticket + "' style='display:inline-block;"
            "margin-top:1rem;padding:.7rem 1.4rem;border-radius:10px;background:#2f6fed;"
            "color:#fff;text-decoration:none;font-weight:600'>Choose account</a>",
        )
    if outcome == "ok":
        return _gsign_end(entry, "You're signed in", "Close this tab and go back to Card Wars Kingdom.")
    return _gsign_end(entry, "Couldn't finish", "Go back to the game and try again.")


@google_bp.route("/account/google/token", methods=["POST"])
def AccountGoogleToken():
    """Android: the game signed in with Google's own picker and sends the id_token here."""
    body = request.get_json(silent=True) or {}
    with _gsign_lock:
        _gsign_sweep()
        entry = _gsign_tickets.get(body.get("ticket") or "")
    if entry is None or entry["status"] != "pending":
        return jsonify({"status": "expired"}), 404
    gclaims = _google_verify_token(body.get("id_token"))
    if gclaims is None:
        with _gsign_lock:
            entry["status"] = "error"
            entry["error"] = "Google sign-in could not be verified."
        return jsonify({"status": "done"})
    return jsonify({"status": "next" if _gsign_apply(entry, gclaims) == "next" else "done"})


@google_bp.route("/account/google/poll")
def AccountGooglePoll():
    """The game asks here until the browser half is done. Single use."""
    ticket = request.args.get("ticket", "")
    with _gsign_lock:
        _gsign_sweep()
        entry = _gsign_tickets.get(ticket)
        if entry is None:
            return jsonify({"status": "expired"}), 404
        status = entry["status"]
        if status == "pending":
            return jsonify({"status": "pending"})
        can_create = bool(entry.get("new_sub"))
        if not can_create:
            _gsign_tickets.pop(ticket, None)
        return jsonify(
            {
                "status": status,
                "username": entry["result"],
                "error": entry["error"],
                "email": entry.get("email"),
                "already": bool(entry.get("already")),
                "can_create": can_create,
            }
        )


@google_bp.route("/account/google/create", methods=["POST"])
def AccountGoogleCreate():
    """First launch: start a new game for a verified Google account (ticket is the proof)."""
    body = request.get_json(silent=True) or {}
    with _gsign_lock:
        _gsign_sweep()
        entry = _gsign_tickets.get(body.get("ticket") or "")
        if (
            entry is None
            or entry.get("mode") != "restore"
            or not entry.get("new_sub")
            or entry.get("device") != request.headers.get("X-Nick-Description")
        ):
            return jsonify({"ok": False, "error": "That sign-in expired. Please sign in again."}), 404
        _gsign_tickets.pop(body.get("ticket"), None)

    sub = entry["new_sub"]
    try:
        if AccountLink.query.filter_by(provider="google", provider_sub=sub).first() is not None:
            return jsonify(
                {"ok": False, "error": "That Google account is already linked to another player."}
            ), 409
        status, error, username = _google_new_player(sub, entry.get("new_email"))
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
    if status != "ok":
        return jsonify({"ok": False, "error": error}), 429
    _BindDevice(username, entry.get("device"))
    return jsonify({"ok": True, "username": username, "email": entry.get("new_email")})
