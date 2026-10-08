"""Gateway runtime files: status, heartbeats and the portal handshake.

A gateway is one named model instance (``mimo-v2.6-flash-free``, ...). Every
instance keeps its own files in ``data/gateways/<name>/``:

``status.json``
    Curated status - ``online`` / ``offline`` / ``busy`` / ``maintenance`` -
    written by ``SetGatewayStatus`` and reported as ``online`` again once its
    ``expires_at`` passes.
``state.json``
    Volatile state: the last heartbeat, the session id, the current task and
    the busy flag.
``portal.log``
    JSONL record of the portal handshake described below.

Heartbeats keep ``state`` fresh; a gateway nobody has heard from for
``GATEWAY_STALE_SECONDS`` (5 minutes) is reported - and written - as offline
by :func:`GatewayScan` / :func:`GatewaySweep`.

Portal handshake - two sessions of a gateway sharing one portal:

1. an entrant appends ``greet``: it is at the door,
2. every peer greeting is answered with ``return``: "greeting returned, go
   ahead",
3. ``enter`` is appended once nobody holds the portal; when two sessions race
   for it, the earliest record (``ts``, ``session``) wins and the loser backs
   out with ``exit`` and waits its turn,
4. ``exit`` releases the portal for the next entrant.

A session that holds the portal for longer than ``PORTAL_MAX_HOLD`` is treated
as crashed and no longer blocks the portal.
"""

import re
import time as _time

from ._common import *
from .game_data import Log, safe_int

# Base directory; every function takes ``base_dir`` to point tests elsewhere.
GATEWAY_DATA_DIR = os.path.join(ROOT_DIR, "data/gateways")

# No heartbeat for this long -> the gateway is offline.
GATEWAY_STALE_SECONDS = 300

GATEWAY_STATUSES = ("online", "offline", "busy", "maintenance")

# How many events state.json keeps for the operator to look back on.
GATEWAY_EVENTS_KEPT = 20

# A portal "enter" older than this is assumed to belong to a crashed session.
PORTAL_MAX_HOLD = 3600

GATEWAY_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _now():
    return int(_time.time())


def _check_name(name):
    name = str(name or "").strip()
    if not GATEWAY_NAME_RE.match(name):
        raise ValueError(
            "Gateway names are 1-64 letters, digits, dots, dashes or "
            f"underscores (got {name!r})"
        )
    return name


def GatewayDir(name, base_dir=None):
    """Directory holding one gateway's runtime files."""
    return os.path.join(base_dir or GATEWAY_DATA_DIR, _check_name(name))


def GatewayStatusPath(name, base_dir=None):
    return os.path.join(GatewayDir(name, base_dir), "status.json")


def GatewayStatePath(name, base_dir=None):
    return os.path.join(GatewayDir(name, base_dir), "state.json")


def GatewayPortalPath(name, base_dir=None):
    return os.path.join(GatewayDir(name, base_dir), "portal.log")


def _read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return default
    return data if isinstance(data, dict) else default


def _write_json(path, payload):
    """Write JSON through a temp file so a reader never sees a half file."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}.{os.urandom(4).hex()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def _record_event(name, event, session="", detail="", base_dir=None):
    """Append one event to state.json's rolling list."""
    path = GatewayStatePath(name, base_dir)
    state = _read_json(path) or {"gateway": _check_name(name)}
    events = state.get("events")
    if not isinstance(events, list):
        events = []
    events.append(
        {
            "ts": _now(),
            "event": event,
            "session": str(session or ""),
            "detail": str(detail or ""),
        }
    )
    state["events"] = events[-GATEWAY_EVENTS_KEPT:]
    state["gateway"] = _check_name(name)
    state["updated_at"] = _now()
    _write_json(path, state)
    return state


def _effective_status(name, status, state, now):
    """Merge status.json + state.json into what an operator should see."""
    status = status or {}
    state = state or {}

    state_seen = safe_int(state.get("last_seen"), 0)
    set_at = safe_int(status.get("set_at"), 0)
    expires = safe_int(status.get("expires_at"), 0)
    raw = str(status.get("status") or "").strip().lower()

    # Freshness is judged from the newest of heartbeat / status change.
    reference = state_seen or set_at
    age = (now - reference) if reference else None
    stale = reference == 0 or age > GATEWAY_STALE_SECONDS

    if not raw and not reference:
        effective = "unknown"
    elif stale:
        # A silent gateway is offline whatever status.json claims.
        effective = "offline"
    elif expires and now > expires:
        # The special status lapsed: back to normal operation.
        effective = "online"
    elif raw in GATEWAY_STATUSES:
        effective = raw
    elif reference:
        effective = "online"
    else:
        effective = "unknown"

    return {
        "gateway": name,
        "status": effective,
        "raw_status": raw or "unknown",
        "stale": stale,
        "age": age,
        "busy": bool(state.get("busy")),
        "session": status.get("session") or state.get("session") or "",
        "current_task": status.get("current_task") or state.get("current_task") or "",
        "last_seen": state_seen,
        "set_by": status.get("set_by") or "",
        "set_at": set_at,
        "expires_at": expires,
        "note": status.get("note") or "",
    }


def GatewayStatus(name, base_dir=None, now=None):
    """Effective status of one gateway. Never writes."""
    name = _check_name(name)
    now = now if now is not None else _now()
    return _effective_status(
        name,
        _read_json(GatewayStatusPath(name, base_dir)),
        _read_json(GatewayStatePath(name, base_dir)),
        now,
    )


def GatewayList(base_dir=None):
    """Names of every gateway that has a directory."""
    base = base_dir or GATEWAY_DATA_DIR
    try:
        entries = os.listdir(base)
    except OSError:
        return []
    names = []
    for entry in sorted(entries):
        if GATEWAY_NAME_RE.match(entry) and os.path.isdir(os.path.join(base, entry)):
            names.append(entry)
    return names


def SetGatewayStatus(
    name,
    status,
    set_by="",
    note="",
    expires_at=0,
    session="",
    current_task="",
    base_dir=None,
):
    """Set the curated status of a gateway (``status.json``).

    ``expires_at`` is a unix timestamp after which the status is reported as
    ``online`` again - use it for maintenance windows.
    """
    name = _check_name(name)
    status = str(status or "").strip().lower()
    if status not in GATEWAY_STATUSES:
        raise ValueError(
            f"Unknown gateway status {status!r}; expected one of "
            + ", ".join(GATEWAY_STATUSES)
        )

    now = _now()
    path = GatewayStatusPath(name, base_dir)
    payload = _read_json(path) or {"gateway": name}
    payload.update(
        {
            "gateway": name,
            "status": status,
            "set_by": str(set_by or "unknown"),
            "set_at": now,
            "updated_at": now,
            "expires_at": safe_int(expires_at, 0),
            "note": str(note or ""),
            "session": str(session or payload.get("session") or ""),
            "current_task": str(current_task or payload.get("current_task") or ""),
        }
    )
    _write_json(path, payload)
    _record_event(name, "status", session=payload["session"], detail=status, base_dir=base_dir)
    Log(
        "gateway",
        f"{name}: status -> {status} (by {payload['set_by']}"
        + (f", expires {payload['expires_at']}" if payload["expires_at"] else "")
        + ")",
    )
    return dict(payload)


def GatewayHeartbeat(name, session="", current_task="", busy=None, base_dir=None):
    """Record that a session is alive (``state.json``).

    A heartbeat also undoes an automatic ``offline`` marking, so a gateway
    that comes back does not stay offline until somebody rescans it.
    """
    name = _check_name(name)
    now = _now()

    status_path = GatewayStatusPath(name, base_dir)
    status = _read_json(status_path)
    if (
        status
        and str(status.get("status")) == "offline"
        and str(status.get("set_by")) == "system"
    ):
        status.update({"status": "online", "set_by": "heartbeat", "set_at": now})
        _write_json(status_path, status)

    state_path = GatewayStatePath(name, base_dir)
    state = _read_json(state_path) or {"gateway": name}
    state.update(
        {
            "gateway": name,
            "session": str(session or state.get("session") or ""),
            "current_task": str(current_task or state.get("current_task") or ""),
            "busy": bool(state.get("busy")) if busy is None else bool(busy),
            "last_seen": now,
            "updated_at": now,
        }
    )
    _write_json(state_path, state)
    _record_event(
        name,
        "heartbeat",
        session=state["session"],
        detail=state["current_task"],
        base_dir=base_dir,
    )
    Log("gateway", f"{name}: heartbeat from {state['session'] or 'unknown session'}")
    return dict(state)


def GatewayScan(base_dir=None, now=None):
    """Status of every gateway, marking silent ones offline.

    A gateway whose last heartbeat (or status change) is older than
    ``GATEWAY_STALE_SECONDS`` has its ``status.json`` rewritten to
    ``offline`` with ``set_by = "system"`` so the files on disk tell the
    truth, not just this listing.
    """
    now = now if now is not None else _now()
    rows = []
    for name in GatewayList(base_dir):
        row = GatewayStatus(name, base_dir=base_dir, now=now)
        if row["stale"] and row["raw_status"] != "offline":
            path = GatewayStatusPath(name, base_dir)
            status = _read_json(path) or {"gateway": name}
            status.update(
                {
                    "gateway": name,
                    "status": "offline",
                    "set_by": "system",
                    "set_at": now,
                    "updated_at": now,
                }
            )
            _write_json(path, status)
            _record_event(name, "offline", detail="stale", base_dir=base_dir)
            Log(
                "gateway",
                f"{name}: marked offline (no heartbeat for "
                f"{GATEWAY_STALE_SECONDS}s)",
            )
            row = GatewayStatus(name, base_dir=base_dir, now=now)
            row["marked_offline"] = True
        rows.append(row)
    return rows


def GatewaySweep(base_dir=None, now=None):
    """Scheduler hook - identical to :func:`GatewayScan`."""
    return GatewayScan(base_dir=base_dir, now=now)


# --- Portal ----------------------------------------------------------------
# portal.log lines: {"ts": ..., "event": greet|return|enter|exit|release,
#                    "session": ..., "peer": ...}


def PortalEvents(name, base_dir=None):
    """Parsed portal.log records (bad lines are skipped)."""
    path = GatewayPortalPath(name, base_dir)
    events = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and record.get("event"):
                    events.append(record)
    except OSError:
        pass
    return events


def _portal_append(name, event, session="", peer="", base_dir=None):
    record = {"ts": _now(), "event": event, "session": str(session or "")}
    if peer:
        record["peer"] = str(peer)
    path = GatewayPortalPath(name, base_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def _portal_state(events, now=None):
    """Per-session portal state: ``{session: ("claim"|"enter", ts)}``.

    ``claim`` is "waiting in line", ``enter`` is "holding the portal"; greet /
    return records are conversation and do not count. Records older than
    ``PORTAL_MAX_HOLD`` belong to a crashed session and are dropped.
    """
    now = now if now is not None else _now()
    state = {}
    for record in events:
        session = str(record.get("session") or "")
        event = record.get("event")
        if event == "release":
            # A release with no session name frees every claim and holder.
            if session in ("", "*"):
                state.clear()
            else:
                state.pop(session, None)
            continue
        if not session or event in ("greet", "return"):
            continue
        ts = safe_int(record.get("ts"), now)
        if event in ("claim", "enter"):
            state[session] = (event, ts)
        elif event in ("exit", "abort"):
            state.pop(session, None)
    return {
        session: (kind, ts)
        for session, (kind, ts) in state.items()
        if now - ts <= PORTAL_MAX_HOLD
    }


def PortalEnter(name, session, timeout=30.0, poll=0.25, announce=None, base_dir=None):
    """Run the portal handshake and step in once the portal is free.

    The log decides the order: every entrant appends a ``claim`` and only the
    earliest claim (``ts``, ``session``) may turn it into ``enter``, and only
    while nobody else is holding. Returns ``{"ok", "entered", "peer",
    "greeted_by", "messages", ...}``; everything worth saying out loud is both
    appended to ``messages`` and handed to ``announce`` when given.
    """
    name = _check_name(name)
    session = str(session or "anonymous").strip() or "anonymous"
    deadline = _time.time() + max(0.0, float(timeout))
    messages = []

    def say(text):
        messages.append(text)
        if announce:
            announce(text)

    # 1) At the door: everybody greets and queues before anything else.
    _portal_append(name, "greet", session=session, base_dir=base_dir)
    _portal_append(name, "claim", session=session, base_dir=base_dir)
    say(f"👋 greeted the portal as {session}")

    greeted_by = set()
    returned_to = set()
    answered_us = set()

    def talk(events):
        """Answer peer greetings; note who answered ours."""
        for record in events:
            event = record.get("event")
            peer = str(record.get("session") or "")
            if not peer or peer == session:
                continue
            if event == "greet" and peer not in returned_to:
                returned_to.add(peer)
                greeted_by.add(peer)
                _portal_append(
                    name, "return", session=session, peer=peer, base_dir=base_dir
                )
                say(
                    f"💌 another portal ({peer}) greeted me - returning its greeting"
                )
            elif event == "return" and record.get("peer") == session:
                answered_us.add(peer)

    blocker = None
    while True:
        events = PortalEvents(name, base_dir)
        talk(events)
        state = _portal_state(events)
        holders = [
            who for who, (kind, _) in state.items() if kind == "enter" and who != session
        ]
        queue = sorted(
            (ts, who) for who, (kind, ts) in state.items() if kind == "claim"
        )

        if not holders and queue and queue[0][1] == session:
            _portal_append(name, "enter", session=session, base_dir=base_dir)
            break

        blocker = holders[0] if holders else (queue[0][1] if queue else None)
        if _time.time() >= deadline:
            # Leave the queue so the next entrant is not kept waiting by us.
            _portal_append(name, "abort", session=session, base_dir=base_dir)
            if greeted_by and not answered_us:
                say("⚠️ I did not get a return greeting from the other portal")
            if holders:
                say(f"🚪 the portal is still held by {', '.join(holders)}; giving up")
                reason = "occupied"
            else:
                say(f"🚧 {blocker} is ahead of me in the queue; giving up")
                reason = "queued"
            return {
                "ok": False,
                "entered": False,
                "reason": reason,
                "peer": blocker,
                "greeted_by": sorted(greeted_by),
                "messages": messages,
            }
        _time.sleep(max(0.05, float(poll)))

    if greeted_by and not answered_us:
        say("⚠️ I did not get a return greeting from the other portal")
    elif not greeted_by:
        say("🔕 the portal never got a greeting - nobody else answered")
    say("🚪 entering the portal")

    return {
        "ok": True,
        "entered": True,
        "peer": blocker,
        "greeted_by": sorted(greeted_by),
        "messages": messages,
    }


def PortalLeave(name, session, announce=None, base_dir=None):
    """Release the portal (``exit``)."""
    name = _check_name(name)
    session = str(session or "anonymous").strip() or "anonymous"
    _portal_append(name, "exit", session=session, base_dir=base_dir)
    message = f"✅ {session} left the portal"
    if announce:
        announce(message)
    Log("gateway", f"{name}: {message}")
    return {"ok": True, "session": session, "messages": [message]}


def PortalRelease(name, session, announce=None, base_dir=None):
    """Operator rescue: force-release a portal held by a crashed session."""
    name = _check_name(name)
    session = str(session or "").strip()
    _portal_append(name, "release", session=session, base_dir=base_dir)
    message = f"🔓 portal released for {session or 'everyone'}"
    if announce:
        announce(message)
    Log("gateway", f"{name}: {message}")
    return {"ok": True, "session": session, "messages": [message]}
