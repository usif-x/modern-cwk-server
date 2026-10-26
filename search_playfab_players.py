#!/usr/bin/env python3
"""Interactive lookup for the PlayFab veterans dump.

Searches `instance/veterans_playfab_20261010.db` (read-only) by display name,
login, in-game name or playfab id, decodes the player's save
(`username=<uuid>&data=<base64(gzip(json))>`) and asks whether to save that
decoded save as a JSON file. Saves that still carry server-side artefacts
(JSON booleans, a foreign PlayerName, SAVE_FIELD_DEFAULTS placeholders,
ClaimSeq/CraftCurrency never written by a client) are listed as fixes and,
on approval, repaired before they are written.

    python3 search_playfab_players.py
    python3 search_playfab_players.py --db instance/veterans_playfab_20261010.db
    python3 search_playfab_players.py --out /tmp/players
    python3 search_playfab_players.py --fix                 # repair without asking
    python3 search_playfab_players.py --player <uuid>       # PlayerName target
"""

import argparse
import base64
import gzip
import io
import json
import os
import re
import sqlite3
import sys
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(ROOT_DIR, "instance", "veterans_playfab_20261010.db")
DEFAULT_OUT = os.path.join(ROOT_DIR, "instance", "veterans_decoded")

SAVE_COUNTERS = (
    "Inventory",
    "CardCollection",
    "Leaders",
    "Loadouts",
    "Collection",
    "EvoMatCollection",
)
SAVE_CURRENCIES = (
    "SoftCurrency",
    "FreeHardCurrency",
    "PaidHardCurrency",
    "PvpCurrency",
    "EvolutionShards",
    "CraftCurrency",
)
MAX_HITS = 20

# Placeholders written by the server's SAVE_FIELD_DEFAULTS (or simply never
# written by a client): a real client save holds these values instead.
# See app/services/game_data.py::SAVE_FIELD_DEFAULTS.
CLIENT_DEFAULTS = (
    ("ConfirmedTOSVersion", 0, 1),
    ("UIDFixApplied", 0, 1),
    ("SecurityKeyValue", "0000", "175D"),
)
# Fields the client keeps in every save but SAVE_FIELD_DEFAULTS does not know,
# so RepairGameData cannot add them (usif.json good save: 12 / 0).
CLIENT_ONLY_FIELDS = (
    ("ClaimSeq", 0),
    ("CraftCurrency", 0),
)
# Top-level keys that are integers in every real client save. Booleans are
# only legitimate in BattleHistory[].youWon (true in usif.json and in 7,705
# local battle rows), so nothing else is touched.
BOOL_AS_INT_KEYS = ("HasAuthenticated", "PvpPlayed", "Zxcvbnm")
LIST_FIELDS = (
    "Inventory",
    "CardCollection",
    "Collection",
    "Leaders",
    "Loadouts",
    "Unlocks",
    "TutorialsDone",
    "Mails",
    "QuestStars",
    "XPMatCollection",
    "EvoMatCollection",
    "CardBacks",
)
DICT_FIELDS = ("MissionProgress",)
INVENTORY_TYPES = ("CR", "CA", "XP", "EV")


def Connect(db_path):
    """Open the dump read-only (never writes, never touches the app database)."""
    return sqlite3.connect("file:%s?mode=ro" % os.path.abspath(db_path), uri=True)


def DecodeSave(game):
    """Same rules as app/services/game_data.py::DecryptGameData.

    Returns `(save_dict_or_None, error_message_or_None)`.
    """
    if game is None or game == b"" or game == b" " or game == "":
        return None, "no game save on this row"
    text = game if isinstance(game, str) else game.decode("utf-8", "replace")
    index = text.find("&data=")
    if index == -1:
        try:
            return json.loads(text), None
        except Exception as e:
            return None, "not a username/data save and not JSON: %s" % e
    try:
        raw = base64.b64decode(text[index + 6 :])
        with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as gz:
            decoded = gz.read().decode("utf-8")
    except Exception as e:
        return None, "gzip/base64 decode failed: %s" % e
    decoded = (
        decoded.replace(",}", "}")
        .replace(",],", "],")
        .replace(",]", "]")
        .replace(",,", ",")
    )
    start = decoded.find("{")
    if start > 0:
        decoded = decoded[start:]
    end = decoded.rfind("}")
    if end >= 0 and end < len(decoded) - 1:
        decoded = decoded[: end + 1]
    try:
        return json.loads(decoded), None
    except Exception as e:
        return None, "JSON parse failed: %s" % e


def CountPlayers(db_path):
    con = Connect(db_path)
    try:
        return con.execute(
            "SELECT COUNT(*) FROM player p"
            " JOIN playfab_account a ON a.playfab_id = p.username"
        ).fetchone()[0]
    finally:
        con.close()


def SearchPlayers(db_path, query):
    """Light scan: every row, only the searchable/readable columns."""
    con = Connect(db_path)
    try:
        rows = con.execute(
            "SELECT p.username, p.multiplayer_name, a.login, a.display_name,"
            " a.gems, a.coins, a.rank_xp"
            " FROM player p JOIN playfab_account a ON a.playfab_id = p.username"
        ).fetchall()
    finally:
        con.close()
    needle = query.casefold().strip()
    hits = []
    for username, multiplayer_name, login, display_name, gems, coins, rank_xp in rows:
        fields = {
            "username": username or "",
            "display_name": display_name or "",
            "login": login or "",
            "multiplayer_name": multiplayer_name or "",
        }
        matched = next(
            (name for name, value in fields.items() if needle in value.casefold()),
            None,
        )
        if matched is None:
            continue
        hits.append(
            {
                "username": username,
                "display_name": display_name,
                "login": login,
                "multiplayer_name": multiplayer_name,
                "gems": gems,
                "coins": coins,
                "rank_xp": rank_xp,
                "matched": matched,
            }
        )
    return hits


def FetchPlayer(db_path, username):
    con = Connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT p.*, a.display_name, a.login, a.created, a.last_login,"
            " a.banned, a.gems, a.coins, a.quests, a.rank_xp"
            " FROM player p JOIN playfab_account a ON a.playfab_id = p.username"
            " WHERE p.username = ?",
            (username,),
        ).fetchone()
    finally:
        con.close()
    return dict(row) if row else None


def _CoerceBooleans(save, changes):
    """HasAuthenticated / PvpPlayed / Zxcvbnm become the 1/0 clients write."""
    for key in BOOL_AS_INT_KEYS:
        value = save.get(key)
        if isinstance(value, bool):
            replacement = 1 if value else 0
            changes.append("%s: %s -> %d" % (key, "true" if value else "false", replacement))
            save[key] = replacement
    return save


def _CountUnexpectedBooleans(value):
    """Booleans outside BattleHistory (where `youWon` really is a boolean)."""
    if isinstance(value, dict):
        total = 0
        for key, item in value.items():
            if key == "BattleHistory":
                continue
            total += _CountUnexpectedBooleans(item)
        return total
    if isinstance(value, list):
        return sum(_CountUnexpectedBooleans(item) for item in value)
    return 1 if isinstance(value, bool) else 0


def RepairSave(save, username="", keep_defaults=False):
    """Return `(repaired_copy, changes)`; the input save is never mutated.

    - HasAuthenticated / PvpPlayed / Zxcvbnm booleans become the 1/0 the
      client writes (BattleHistory[].youWon is left alone: it is a boolean
      in every real save)
    - PlayerName is set to `username` (the row's own id) when it differs
    - SAVE_FIELD_DEFAULTS placeholders get the values a real client stores
    - ClaimSeq / CraftCurrency are added when absent (SAVE_FIELD_DEFAULTS
      does not know them, so RepairGameData cannot add them)
    - QuestSelectScrollPos is emitted as a float
    """
    fixed = json.loads(json.dumps(save))
    changes = []

    if username and fixed.get("PlayerName") != username:
        changes.append("PlayerName: %r -> %r" % (fixed.get("PlayerName"), username))
        fixed["PlayerName"] = username

    _CoerceBooleans(fixed, changes)

    if not keep_defaults:
        for key, placeholder, client_value in CLIENT_DEFAULTS:
            if key not in fixed:
                changes.append("+ %s: %r (added)" % (key, client_value))
                fixed[key] = client_value
            elif fixed[key] == placeholder:
                changes.append("%s: %r -> %r" % (key, placeholder, client_value))
                fixed[key] = client_value

    for key, value in CLIENT_ONLY_FIELDS:
        if key not in fixed:
            changes.append("+ %s: %r (added)" % (key, value))
            fixed[key] = value

    scroll = fixed.get("QuestSelectScrollPos")
    if isinstance(scroll, int) and not isinstance(scroll, bool):
        changes.append("QuestSelectScrollPos: %r -> %r" % (scroll, float(scroll)))
        fixed["QuestSelectScrollPos"] = float(scroll)

    return fixed, changes


def SanityCheck(save):
    """Structural problems worth knowing about before the file is written."""
    warnings = []
    if not save.get("PlayerName"):
        warnings.append("PlayerName is missing or empty")
    if not save.get("MultiplayerPlayerName"):
        warnings.append("MultiplayerPlayerName is missing or empty")
    for key in LIST_FIELDS:
        if key in save and not isinstance(save[key], list):
            warnings.append("%s should be a list (is %s)" % (key, type(save[key]).__name__))
    for key in DICT_FIELDS:
        if key in save and not isinstance(save[key], dict):
            warnings.append("%s should be an object (is %s)" % (key, type(save[key]).__name__))

    uids = set()
    leaders = set()
    inventory = save.get("Inventory")
    if isinstance(inventory, list):
        for index, item in enumerate(inventory):
            if not isinstance(item, dict):
                warnings.append("Inventory[%d] is not an object" % index)
                continue
            if item.get("_T") not in INVENTORY_TYPES:
                warnings.append("Inventory[%d] (%r) has an invalid _T: %r"
                                % (index, item.get("ID"), item.get("_T")))
            if not item.get("ID"):
                warnings.append("Inventory[%d] has no ID" % index)
            if item.get("_T") == "CR":
                uid = item.get("UniqueID")
                if uid in uids:
                    warnings.append("duplicate creature UniqueID %r ('%s')" % (uid, item.get("ID")))
                uids.add(uid)
                if "Xp" not in item or "StarRating" not in item:
                    warnings.append("creature '%s' is missing Xp/StarRating" % item.get("ID"))
    if isinstance(save.get("Leaders"), list):
        leaders = {
            entry.get("ID")
            for entry in save["Leaders"]
            if isinstance(entry, dict) and entry.get("ID")
        }
    if isinstance(save.get("Loadouts"), list):
        for index, loadout in enumerate(save["Loadouts"]):
            if not isinstance(loadout, dict):
                warnings.append("Loadouts[%d] is not an object" % index)
                continue
            for slot, uid in loadout.items():
                if slot.startswith("CreatureID") and isinstance(uid, int) and uid not in (0, -1) and uid not in uids:
                    warnings.append("Loadouts[%d].%s -> unknown creature UniqueID %r" % (index, slot, uid))
            leader_id = loadout.get("LeaderID")
            if leader_id and leader_id not in leaders:
                warnings.append("Loadouts[%d].LeaderID %r is not owned" % (index, leader_id))

    booleans = _CountUnexpectedBooleans(save)
    if booleans:
        warnings.append(
            "%d unexpected JSON boolean(s) outside BattleHistory "
            "(the client writes 1/0)" % booleans
        )
    return warnings


def SanitizeName(name, fallback="player"):
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", (name or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = re.sub(r"_{2,}", "_", cleaned)[:60].strip(" .")
    return cleaned or fallback


def ExistingOwner(path):
    """The PlayerName inside an existing file, or None when unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data.get("PlayerName")
    except Exception:
        return None
    return None


def DefaultPath(out_dir, row, save):
    """`<display name>.json`; a file owned by another player gets the uuid."""
    label = SanitizeName(
        row.get("display_name") or row.get("login") or row.get("multiplayer_name") or "",
        "",
    )
    if not label:
        label = SanitizeName(row.get("multiplayer_name") or "", "player")
    path = os.path.join(out_dir, label + ".json")
    if os.path.exists(path) and ExistingOwner(path) != save.get("PlayerName"):
        path = os.path.join(
            out_dir, "%s__%s.json" % (label, row.get("username") or "player")
        )
    return path


def Stamp(value):
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return str(value or "")


def FormatSize(byte_count):
    if byte_count < 1024 * 1024:
        return "%.1f KB" % (byte_count / 1024.0)
    return "%.1f MB" % (byte_count / 1024.0 / 1024.0)


def Ask(prompt):
    """Prompt for a line; None means end of input (quit)."""
    try:
        return input(prompt).strip()
    except EOFError:
        print()
        return None


def PromptPick(hits):
    while True:
        answer = Ask("Pick [1-%d, Enter=1]: " % len(hits))
        if answer is None:
            return None
        if answer == "":
            return hits[0]
        if answer.isdigit() and 1 <= int(answer) <= len(hits):
            return hits[int(answer) - 1]
        print("  Pick a number between 1 and %d." % len(hits))


def PromptYesNo(question):
    answer = Ask(question)
    if answer is None:
        return False
    return answer.casefold() in ("y", "yes")


def PrintChanges(changes, limit=12):
    for line in changes[:limit]:
        print("   - " + line)
    if len(changes) > limit:
        print("   - ... %d more" % (len(changes) - limit))


def PrintHits(hits, query):
    shown = hits[:MAX_HITS]
    for number, hit in enumerate(shown, 1):
        print(
            "  %2d) %-24s login=%-16s uuid=%s  gems=%s  rank_xp=%s  [%s]"
            % (
                number,
                hit["display_name"] or "?",
                hit["login"] or "?",
                hit["username"],
                hit["gems"],
                hit["rank_xp"],
                hit["matched"],
            )
        )
    if len(hits) > MAX_HITS:
        print("  ... %d more matches (narrow the query)." % (len(hits) - MAX_HITS))


def PrintRecord(row, save, error):
    print("-" * 72)
    print(
        "  playfab id : %-18s login : %s"
        % (row.get("username"), row.get("login") or "")
    )
    print(
        "  created    : %-19s last login : %s   banned: %s"
        % (
            row.get("created") or "",
            row.get("last_login") or "",
            "yes" if row.get("banned") else "no",
        )
    )
    print(
        '  in-game    : %-19s last online : %s'
        % ('"%s"' % (row.get("multiplayer_name") or ""), Stamp(row.get("last_online")))
    )
    print(
        "  level      : %-19s leader : %s (rank %s)"
        % (row.get("level"), row.get("leader") or "-", row.get("leader_level"))
    )
    print(
        "  playfab    : gems %s · coins %s · quests %s · rank_xp %s"
        % (
            row.get("gems"),
            row.get("coins"),
            row.get("quests"),
            row.get("rank_xp"),
        )
    )
    if save is None:
        print("  save       : <none — %s>" % (error or "no save"))
    else:
        print(
            "  save       : %s"
            % "  ".join(
                "%s=%s" % (key, save.get(key))
                for key in SAVE_CURRENCIES
                if save.get(key) is not None
            )
        )
        print(
            "             : PlayerName=%s  MultiplayerPlayerName=%s  MultiplayerLevel=%s  RankXP=%s%s"
            % (
                save.get("PlayerName"),
                save.get("MultiplayerPlayerName"),
                save.get("MultiplayerLevel"),
                save.get("RankXP"),
                "  BANNED" if save.get("Zxcvbnm") else "",
            )
        )
        print(
            "             : %s"
            % "  ".join(
                "%s %d"
                % (key.lower(), len(save.get(key) or []))
                for key in SAVE_COUNTERS
                if isinstance(save.get(key), list)
            )
        )
    print("-" * 72)


def PromptSave(out_dir, save, row, error):
    if save is None:
        print("  nothing to save — %s" % (error or "no game save"))
        return
    if not PromptYesNo("Save this data to a JSON file? [y/N]: "):
        return
    default_path = DefaultPath(out_dir, row, save)
    answer = Ask("Path [%s]: " % default_path)
    if answer is None:
        return
    path = os.path.expanduser(answer) if answer else default_path
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    existed = os.path.exists(path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(save, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(
        "Saved %s (%s)%s"
        % (
            path,
            FormatSize(os.path.getsize(path)),
            ", overwrote existing file" if existed else "",
        )
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Search the PlayFab veterans dump and export a player save as JSON."
    )
    parser.add_argument("--db", default=DEFAULT_DB, help="path to the playfab sqlite dump")
    parser.add_argument("--out", default=DEFAULT_OUT, help="default folder for saved JSON")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="apply the repair fixes without asking",
    )
    parser.add_argument(
        "--player",
        default="",
        help="value for PlayerName (default: the row's own username)",
    )
    parser.add_argument(
        "--keep-defaults",
        action="store_true",
        help="leave server-side placeholder values (ConfirmedTOSVersion etc.) untouched",
    )
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        print("Dump not found: %s" % args.db)
        return 1
    try:
        total = CountPlayers(args.db)
    except sqlite3.Error as e:
        print("Could not open %s: %s" % (args.db, e))
        return 1

    print("PlayFab veterans dump: %s — %d players" % (args.db, total))
    print("Search by display name, login, in-game name or playfab id.")
    while True:
        print()
        try:
            query = Ask("Search (empty to quit): ")
        except KeyboardInterrupt:
            print()
            return 0
        if query is None or query == "" or query.casefold() in ("q", "quit", "exit"):
            return 0
        hits = SearchPlayers(args.db, query)
        if not hits:
            print("No players matched %r." % query)
            continue
        print("%d match(es):" % len(hits))
        PrintHits(hits, query)
        try:
            picked = PromptPick(hits)
        except KeyboardInterrupt:
            print()
            return 0
        if picked is None:
            return 0
        row = FetchPlayer(args.db, picked["username"])
        if row is None:
            print("Row vanished for %s." % picked["username"])
            continue
        save, error = DecodeSave(row.get("game"))
        PrintRecord(row, save, error)
        try:
            if save is None:
                PromptSave(args.out, None, row, error)
                continue
            fixed, changes = RepairSave(
                save,
                username=args.player or row.get("username") or "",
                keep_defaults=args.keep_defaults,
            )
            if changes:
                print("  %d fix(es) available:" % len(changes))
                PrintChanges(changes)
                if args.fix:
                    save = fixed
                    print("  repaired (%d change(s))" % len(changes))
                elif PromptYesNo("Repair before saving? [y/N]: "):
                    save = fixed
                    print("  repaired (%d change(s))" % len(changes))
                else:
                    print("  keeping the raw decode")
            for warning in SanityCheck(save):
                print("  warning: " + warning)
            PromptSave(args.out, save, row, error)
        except KeyboardInterrupt:
            print()
            return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(0)
