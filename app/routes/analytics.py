import json, os, threading, time
from datetime import datetime
from urllib.parse import parse_qs
from flask import Blueprint, jsonify, make_response, request

from app import db
from app.models import Player, UpsightLogs
from app.services.trade_market import PublicId
from app.utils import (
    CurrentPvpSeason, DecryptGameData, DiscordWebhookMessage, GetPlayerWins,
    GetPvpRankDetails, IPFromRequest, SystemBan, safe_int,
)

analytics_bp = Blueprint('analytics_bp', __name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@analytics_bp.route("/analytics/upsight", methods=["POST"])
def AnalyticsUpsight():
    headers = request.headers

    if (
        headers.get("Player-Id") is None
        or headers.get("Event-Type") is None
        or headers.get("Event-Action") is None
    ):
        return make_response("Bad request!", 400)

    message = request.get_data().decode("utf-8")
    if message == "null":
        message = None

    newAnalytics = UpsightLogs(
        player_id=headers.get("Player-Id"),
        time=int(time.time()),
        event=headers.get("Event-Type"),
        action=headers.get("Event-Action"),
        message=message,
    )
    db.session.add(newAnalytics)
    db.session.commit()

    if headers.get("Event-Action") == "detector":
        DiscordWebhookMessage(
            headers.get("Player-Id") + " triggered ACTk Anti-Cheat. Data:" + message
        )
        SystemBan(headers.get("Player-Id"))

    return make_response("OK", 200)


@analytics_bp.route("/analytics/pvpmatch", methods=["POST"])
def AnalyticsPVPMatch():
    headers = request.headers

    if headers.get("Player-Id") is None:
        return make_response("Bad request!", 400)

    message = request.get_data().decode("utf-8")
    if message == "null":
        message = None

    # write to file
    pvpmatches_dir = os.path.join(ROOT_DIR, "data/persist/pvpmatches")
    os.makedirs(pvpmatches_dir, exist_ok=True)

    with open(
        os.path.join(pvpmatches_dir, headers.get("Player-Id", "unknown") + "_" + headers.get("Match-Id", "unknown") + ".json"),
        "w",
    ) as outfile:
        message = json.loads(message)
        json.dump(message, outfile, indent=4)

    return make_response("OK", 200)


_leaderboard_cache = {"built": 0.0, "list": None}
_leaderboard_lock = threading.Lock()
LEADERBOARD_TTL = 300  # seconds; the board is a slow-moving list


def _BuildLeaderboard():
    """Ranked players this PvP season, in the production entry shape.

    Only players who actually played a PvP match this season are ranked (a save
    keeps last season's rank until its owner opens the app again).
    """
    season = CurrentPvpSeason()
    out = []
    q = db.session.query(Player.username, Player.game).filter(Player.game.isnot(None))
    for username, blob in q.yield_per(200):
        try:
            game = DecryptGameData(blob)
            if not isinstance(game, dict):
                continue
            if season and (game.get("ActivePvpSeason") != season or not game.get("PvpPlayed")):
                continue
            level = safe_int(game.get("MultiplayerLevel", 999), 999)
            points = safe_int(game.get("PointsInMultiplayerLevel", 0))
            rank_name, sprite_name, rank_id = GetPvpRankDetails(level)
            out.append(
                {
                    "playerid": username,
                    "playername": game.get("MultiplayerPlayerName") or "Unknown",
                    "multiplayer_level": level,
                    "score": points,
                    "rank_name": rank_name,
                    "sprite_name": sprite_name,
                    "rank_id": rank_id,
                }
            )
        except Exception:
            continue
    out.sort(key=lambda x: (x["multiplayer_level"] == -1, x["multiplayer_level"], -x["score"]))
    for index, item in enumerate(out, start=1):
        item["ranking"] = index
    return out


def _CachedLeaderboard():
    with _leaderboard_lock:
        now = time.time()
        if _leaderboard_cache["list"] is None or now - _leaderboard_cache["built"] > LEADERBOARD_TTL:
            _leaderboard_cache["list"] = _BuildLeaderboard()
            _leaderboard_cache["built"] = now
        return list(_leaderboard_cache["list"])


@analytics_bp.route("/dw_leaderboard/fetchentries/", methods=["POST"])
def LeaderboardFetchEntries():
    """PVP leaderboard entries, in the production response shape:
    {"success": true, "data": [ {ranking, playerid, playername, multiplayer_level,
    score, rank_name, sprite_name, rank_id}, ... ]}."""
    try:
        payload = request.get_json(silent=True) or request.form
        start_pos = safe_int(payload.get("startpos", 1), 1)
        end_pos = safe_int(payload.get("endpos", 30), 30)

        board = _CachedLeaderboard()

        # Pad with bots to the requested window (production does the same).
        minimum = max(30, end_pos)
        while len(board) < minimum:
            index = len(board) + 1
            fake_points = max(100, 22000 - index * 650)
            rank_name, sprite_name, rank_id = GetPvpRankDetails(None)
            board.append(
                {
                    "ranking": index,
                    "playerid": "bot_" + str(index),
                    "playername": "Bot_" + str(index),
                    "multiplayer_level": 999,
                    "score": fake_points,
                    "rank_name": rank_name,
                    "sprite_name": sprite_name,
                    "rank_id": rank_id,
                }
            )

        viewer = request.headers.get("Player-Id")
        data = [
            dict(e, playerid=PublicId(e.get("playerid"), viewer))
            for e in board[start_pos - 1 : end_pos]
        ]
        return jsonify({"success": True, "data": data})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@analytics_bp.route("/dw_leaderboard/placeme/", methods=["POST"])
def LeaderboardPlaceMe():
    return jsonify({"success": True}), 200


@analytics_bp.route("/dw_leaderboard/registerresult/", methods=["POST"])
def LeaderboardRegisterResult():
    return jsonify({"success": True, "data": 1500}), 200


@analytics_bp.route("/dw_leaderboard/hasended/", methods=["POST"])
def LeaderboardHasEnded():
    return jsonify({"success": True, "data": 0}), 200


@analytics_bp.route("/multiplayer/active_leaderboard/rank/<player_id>", methods=["GET"])
def MultiplayerActiveLeaderboardRank(player_id):
    try:
        rank = "0"
        for row in _CachedLeaderboard():
            if row.get("playerid") == player_id:
                rank = str(row.get("ranking", 0))
                break
        return jsonify({"success": True, "data": {"rank": rank}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
