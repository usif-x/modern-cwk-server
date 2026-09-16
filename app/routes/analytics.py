import json, os, time
from datetime import datetime
from urllib.parse import parse_qs
from flask import Blueprint, jsonify, make_response, request

from app import db
from app.models import Player, UpsightLogs
from app.utils import (
    DiscordWebhookMessage, GetPlayerWins, IPFromRequest, SystemBan,
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


@analytics_bp.route("/dw_leaderboard/fetchentries/", methods=["POST"])
def LeaderboardFetchEntries():
    clientData = parse_qs(request.get_data().decode("utf-8"))
    clientData = {k: v[0] if len(v) == 1 else v for k, v in clientData.items()}

    # go through each players save and sort by ammount of wins
    allplayers = Player.query.all()

    leaderboard = []

    for player in allplayers:
        if (
            player.multiplayer_name is None
            or player.multiplayer_name == b""
            or player.multiplayer_name == b" "
        ):
            continue
        if player.leader_level < 10:
            continue
        # check if player has been on in the past 31 days
        if time.time() - player.last_online > 60 * 60 * 24 * 31:
            continue

        playerwins = 0
        try:
            playerwins = GetPlayerWins(player.username)
        except Exception:
            continue

        if playerwins is None or playerwins == 0:
            continue
        leaderboard.append(
            {
                "playerid": player.username,
                "playername": player.multiplayer_name,
                "score": int(playerwins),
            }
        )

    # sort leaderboard by score
    leaderboard = sorted(leaderboard, key=lambda k: k["score"], reverse=True)

    leaderboard = leaderboard[:50]

    # set "ranking" based on position in leaderboard
    for i in range(len(leaderboard)):
        leaderboard[i]["ranking"] = int(i + 1)

    return jsonify({"success": True, "data": f"{json.dumps(leaderboard)}"})
