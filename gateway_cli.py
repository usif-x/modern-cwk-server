#!/usr/bin/env python3
"""Gateway runtime CLI - status, heartbeats and the portal handshake.

The gateway files live in ``data/gateways/<name>/`` (see
``app/services/gateway.py`` for the format). Typical session:

    python gateway_cli.py init mimo-v2.6-flash-free
    python gateway_cli.py set-status mimo-v2.6-flash-free busy --by opencode \\
        --task "editing app/services/gateway.py"
    python gateway_cli.py heartbeat mimo-v2.6-flash-free \\
        --session opencode-4242 --task "writing tests" --interval 30
    python gateway_cli.py status mimo-v2.6-flash-free
    python gateway_cli.py scan
    python gateway_cli.py portal enter mimo-v2.6-flash-free opencode-4242 \\
        --enter-cmd "python -i my_session.py"
    python gateway_cli.py portal log mimo-v2.6-flash-free

``portal enter`` greets every other session first, returns their greeting,
only steps in once the portal is free and announces it; ``--enter-cmd`` is
what runs while holding the portal (the portal is released afterwards, even
if the command fails).
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

from app.services.gateway import (
    GATEWAY_DATA_DIR,
    GATEWAY_STALE_SECONDS,
    GATEWAY_STATUSES,
    GatewayDir,
    GatewayHeartbeat,
    GatewayScan,
    GatewayStatus,
    PortalEnter,
    PortalEvents,
    PortalLeave,
    PortalRelease,
    SetGatewayStatus,
)


def _default_session():
    user = os.environ.get("LOGNAME") or os.environ.get("USER") or "session"
    return f"{user}-{os.getpid()}"


def _fmt_when(ts):
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _fmt_age(age):
    if age is None:
        return "-"
    if age < 90:
        return f"{age}s"
    if age < 5400:
        return f"{age // 60}m"
    if age < 172800:
        return f"{age // 3600}h"
    return f"{age // 86400}d"


def _print_status(row):
    print(f"gateway      {row['gateway']}")
    print(f"status       {row['status']}" + (" (stale)" if row["stale"] else ""))
    print(f"last seen    {_fmt_age(row['age'])} ago ({_fmt_when(row['last_seen'])})")
    print(f"session      {row['session'] or '-'}")
    print(f"task         {row['current_task'] or '-'}")
    print(f"busy         {'yes' if row['busy'] else 'no'}")
    print(f"set by       {row['set_by'] or '-'} at {_fmt_when(row['set_at'])}")
    if row["expires_at"]:
        state = "expired" if time.time() > row["expires_at"] else "active"
        print(f"expires      {_fmt_when(row['expires_at'])} ({state})")
    if row["note"]:
        print(f"note         {row['note']}")


def _print_scan(rows):
    if not rows:
        print(f"no gateways in {GATEWAY_DATA_DIR}")
        return
    name_w = max(14, max(len(r["gateway"]) for r in rows))
    print(
        f"{'GATEWAY'.ljust(name_w)}  {'STATUS'.ljust(11)}  {'AGE'.ljust(6)}  "
        f"{'SESSION'.ljust(18)}  TASK"
    )
    for row in rows:
        print(
            f"{row['gateway'].ljust(name_w)}  {row['status'].ljust(11)}  "
            f"{_fmt_age(row['age']).ljust(6)}  "
            f"{(row['session'] or '-').ljust(18)}  {row['current_task'] or '-'}"
        )
    silent = [r["gateway"] for r in rows if r["stale"]]
    if silent:
        print(
            f"\n💤 {', '.join(silent)} silent for more than "
            f"{GATEWAY_STALE_SECONDS}s -> offline"
        )


def _parse_expiry(value):
    """``3600``/``90s``/``30m``/``2h``/``1d`` from now, or an ISO-8601 time."""
    if not value:
        return 0
    text = str(value).strip()
    try:
        if text.isdigit():
            return int(time.time()) + int(text)
        unit = text[-1].lower()
        if unit in "smhd" and text[:-1].isdigit():
            seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
            return int(time.time()) + int(text[:-1]) * seconds
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return int(when.timestamp())
    except ValueError:
        raise SystemExit(f"cannot read --expires {value!r} (try 90s, 30m, 2h, 1d or ISO)")


def cmd_init(args):
    existing = GatewayStatus(args.gateway, base_dir=args.base_dir)
    if existing["raw_status"] != "unknown" or existing["last_seen"]:
        print(f"⚙️  {args.gateway} already exists in {GatewayDir(args.gateway, args.base_dir)}")
    else:
        SetGatewayStatus(
            args.gateway,
            args.status,
            set_by=args.by,
            note=args.note,
            base_dir=args.base_dir,
        )
        print(f"⚙️  created {GatewayDir(args.gateway, args.base_dir)}")
    _print_status(GatewayStatus(args.gateway, base_dir=args.base_dir))
    return 0


def cmd_set_status(args):
    payload = SetGatewayStatus(
        args.gateway,
        args.status,
        set_by=args.by,
        note=args.note,
        expires_at=_parse_expiry(args.expires),
        session=args.session,
        current_task=args.task,
        base_dir=args.base_dir,
    )
    print(
        f"🚦 {args.gateway} -> {payload['status']} (by {payload['set_by']}"
        + (f", expires {_fmt_when(payload['expires_at'])}" if payload["expires_at"] else "")
        + ")"
    )
    return 0


def cmd_status(args):
    row = GatewayStatus(args.gateway, base_dir=args.base_dir)
    if args.json:
        print(json.dumps(row, ensure_ascii=False, indent=2))
    else:
        _print_status(row)
    return 0 if row["status"] != "unknown" else 1


def cmd_scan(args):
    rows = GatewayScan(base_dir=args.base_dir)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        _print_scan(rows)
    return 0


def cmd_heartbeat(args):
    session = args.session or _default_session()
    tick = 0
    try:
        while True:
            tick += 1
            state = GatewayHeartbeat(
                args.gateway,
                session=session,
                current_task=args.task,
                busy=True if args.busy else None,
                base_dir=args.base_dir,
            )
            print(
                f"💓 {args.gateway} alive "
                f"(session {state['session']}, task {state['current_task'] or '-'}, "
                f"busy {'yes' if state['busy'] else 'no'})"
            )
            if args.interval <= 0 or (args.count and tick >= args.count):
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n💤 heartbeat stopped")
    return 0


def cmd_portal_enter(args):
    session = args.session or _default_session()
    result = PortalEnter(
        args.gateway,
        session,
        timeout=args.timeout,
        poll=args.poll,
        announce=print,
        base_dir=args.base_dir,
    )
    if not result["ok"]:
        print(f"🛑 {result.get('reason', 'refused')}")
        return 1

    code = 0
    if args.enter_cmd:
        print(f"▶️  running: {args.enter_cmd}")
        try:
            code = subprocess.run(args.enter_cmd, shell=True).returncode
        finally:
            PortalLeave(args.gateway, session, announce=print, base_dir=args.base_dir)
        if code:
            print(f"⚠️  the command exited with {code}")
        return code
    print("ℹ️  holding the portal; run `portal leave` when you are done")
    return 0


def cmd_portal_leave(args):
    PortalLeave(args.gateway, args.session, announce=print, base_dir=args.base_dir)
    return 0


def cmd_portal_release(args):
    PortalRelease(
        args.gateway, args.session or "", announce=print, base_dir=args.base_dir
    )
    return 0


def cmd_portal_log(args):
    events = PortalEvents(args.gateway, base_dir=args.base_dir)
    if not events:
        print(f"📭 no portal activity in {GatewayDir(args.gateway, args.base_dir)}")
        return 0
    for record in events[-args.limit:]:
        peer = f" -> {record['peer']}" if record.get("peer") else ""
        print(
            f"{_fmt_when(record.get('ts'))}  {str(record.get('event', '')).ljust(7)} "
            f"{record.get('session', '')}{peer}"
        )
    return 0


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--base-dir",
        default=None,
        help=f"gateway root directory (default: {GATEWAY_DATA_DIR})",
    )

    parser = argparse.ArgumentParser(
        description="Gateway status, heartbeats and portal handshake.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", parents=[common], help="create a gateway directory")
    p.add_argument("gateway")
    p.add_argument("--status", default="online", choices=GATEWAY_STATUSES)
    p.add_argument("--by", default="cli")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser(
        "set-status", parents=[common], help="set online/offline/busy/maintenance"
    )
    p.add_argument("gateway")
    p.add_argument("status", choices=GATEWAY_STATUSES)
    p.add_argument("--by", default="cli")
    p.add_argument("--note", default="")
    p.add_argument("--expires", default="", help="90s, 30m, 2h, 1d or ISO-8601")
    p.add_argument("--session", default="")
    p.add_argument("--task", default="")
    p.set_defaults(func=cmd_set_status)

    p = sub.add_parser("status", parents=[common], help="show one gateway")
    p.add_argument("gateway")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("scan", parents=[common], help="list every gateway")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("heartbeat", parents=[common], help="record that a session is alive")
    p.add_argument("gateway")
    p.add_argument("--session", default="")
    p.add_argument("--task", default="")
    p.add_argument("--busy", action="store_true")
    p.add_argument(
        "--interval",
        type=float,
        default=0,
        help="keep beating every N seconds (0 = once)",
    )
    p.add_argument(
        "--count", type=int, default=0, help="stop after N beats (0 = no limit)"
    )
    p.set_defaults(func=cmd_heartbeat)

    portal = sub.add_parser("portal", help="portal handshake")
    psub = portal.add_subparsers(dest="portal_command", required=True)

    p = psub.add_parser("enter", parents=[common], help="greet, then step in")
    p.add_argument("gateway")
    p.add_argument("--session", default="")
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--poll", type=float, default=0.25)
    p.add_argument(
        "--enter-cmd",
        default="",
        help="command to run while holding the portal (released afterwards)",
    )
    p.set_defaults(func=cmd_portal_enter)

    p = psub.add_parser("leave", parents=[common], help="release the portal")
    p.add_argument("gateway")
    p.add_argument("--session", default="")
    p.set_defaults(func=cmd_portal_leave)

    p = psub.add_parser("release", parents=[common], help="force-free a stuck portal")
    p.add_argument("gateway")
    p.add_argument(
        "--session",
        default="",
        help="holder to release; omit to release everybody",
    )
    p.set_defaults(func=cmd_portal_release)

    p = psub.add_parser("log", parents=[common], help="show portal.log")
    p.add_argument("gateway")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_portal_log)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "base_dir", None):
        args.base_dir = GATEWAY_DATA_DIR
    try:
        return args.func(args)
    except ValueError as e:
        print(f"🛑 {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
