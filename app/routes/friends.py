import json, random, time
from urllib.parse import parse_qs
from flask import Blueprint, jsonify, make_response, request
from flask_login import current_user
from sqlalchemy import func

from app import db
from app.models import Player
from app.utils import (
    AllyBoxSpaceNotExceeded, GetAllyInfo, IPFromRequest, IsUserBanned,
    UpdateLastOnline,
)

friends_bp = Blueprint('friends_bp', __name__)


@friends_bp.route("/persist/friends/<string:player_id>")
def PersistFriends(player_id):
    UpdateLastOnline(player_id)
    db_user = Player.query.filter_by(username=player_id).first()

    if db_user is None:
        return make_response("No player found!", 404)

    data = []

    player_friends = json.loads(db_user.friends)

    for friend in player_friends:
        # check if user is banned
        if IsUserBanned(friend):
            continue
        friend_user = Player.query.filter_by(username=friend).first()
        allyinfo = GetAllyInfo(friend, True)
        if allyinfo is not None:
            data.append(allyinfo)

    return jsonify(data)


@friends_bp.route("/persist/friends_find_candidatesDW/", methods=["POST"])
def PersistFriendsFindCandidates():
    clientData = parse_qs(request.get_data().decode("utf-8"))
    clientData = {k: v[0] if len(v) == 1 else v for k, v in clientData.items()}

    db_user = Player.query.filter_by(username=clientData["player_id"]).first()

    if db_user is None:
        return make_response("No player found!", 404)

    data = []

    player_friends = json.loads(db_user.friends)

    for friend in player_friends:
        # check if user is banned
        if IsUserBanned(friend):
            continue
        friend_user = Player.query.filter_by(username=friend).first()
        # add ally if the level is withen clientData["level"]
        allyinfo = GetAllyInfo(friend, True)
        if allyinfo is not None:
            data.append(allyinfo)

    # Add explorers
    strangers = (
        Player.query.filter(
            Player.username != clientData["player_id"],  # not the player
            Player.username.notin_(player_friends),  # not a friend
            Player.helper_creature != None,  # has a helper creature
            Player.leader_level.between(
                db_user.leader_level - int(clientData["level"]),
                db_user.leader_level + int(clientData["level"]),
            ),  # level is within clientData["level"]
        )
        .order_by(func.random())
        .limit(3)
        .all()
    )

    for stranger in strangers:
        if IsUserBanned(stranger.username):
            continue

        allyinfo = GetAllyInfo(stranger.username, False)
        if allyinfo is not None:
            data.append(allyinfo)

    # randomize list
    data = random.sample(data, len(data))

    data2 = {"success": True, "data": json.dumps(data)}
    return jsonify(data2)


@friends_bp.route("/persist/friends_use_friendDW/", methods=["POST"])
def PersistFriendsUseFriend():
    clientData = parse_qs(request.get_data().decode("utf-8"))
    clientData = {k: v[0] if len(v) == 1 else v for k, v in clientData.items()}

    db_ally = Player.query.filter_by(username=clientData["friendid"]).first()

    if db_ally is None:
        return make_response("No player found!", 500)

    db_ally.helpcount = int(db_ally.helpcount) + 1
    db.session.commit()

    data = {
        "success": True,
    }
    return jsonify(data)


@friends_bp.route("/persist/friends_use_playerDW/", methods=["POST"])
def PersistFriendsUsePlayer():
    clientData = parse_qs(request.get_data().decode("utf-8"))
    clientData = {k: v[0] if len(v) == 1 else v for k, v in clientData.items()}

    db_stranger = Player.query.filter_by(username=clientData["userid"]).first()
    if db_stranger is None:
        return make_response("No player found!", 404)

    db_stranger.anonymoushelpcount = int(db_stranger.anonymoushelpcount) + 1
    db.session.commit()

    data = {
        "success": True,
    }
    return jsonify(data)


@friends_bp.route("/persist/friends_request_withmyinfoDW/", methods=["POST"])
def PersistFriendsRequestWithMyInfo():
    clientData = parse_qs(request.get_data().decode("utf-8"))
    clientData = {k: v[0] if len(v) == 1 else v for k, v in clientData.items()}

    UpdateLastOnline(clientData["player_id"])

    try:
        invite_user = Player.query.filter_by(
            username=clientData["invite_id"].replace("_", "-")
        ).first()
    except:
        return make_response("No player found!", 400)
    if invite_user is None:
        return make_response("No player found!", 400)

    db_user = Player.query.filter_by(username=clientData["player_id"]).first()
    if db_user is None:
        return make_response("No player found!", 400)

    inviteuserfr = json.loads(invite_user.friend_requests)

    # Player ally check
    allycheck = AllyBoxSpaceNotExceeded(clientData["player_id"])
    if allycheck == False:
        return jsonify({"success": True, "info": "exceed me"})

    # friend ally check
    friendallycheck = AllyBoxSpaceNotExceeded(clientData["invite_id"].replace("_", "-"))
    if friendallycheck == False:
        return jsonify({"success": True, "info": "exceed"})

    # check if player already sent a request
    if clientData["player_id"] not in invite_user.friend_requests:
        inviteuserfr.append(clientData["player_id"])
        invite_user.friend_requests = json.dumps(inviteuserfr)
        db.session.commit()
        return jsonify({"success": True})
    else:
        return jsonify({"success": True, "info": "duplicate"})


@friends_bp.route("/persist/friends_all_requests_received/<string:player_id>", methods=["GET"])
def PersistFriendsAllRequestsReceived(player_id):
    db_user = Player.query.filter_by(username=player_id).first()
    if db_user is None:
        return make_response("No player found!", 400)

    data = []

    playerfriendrequests = json.loads(db_user.friend_requests)

    for friendrequest in playerfriendrequests:
        allyinfo = GetAllyInfo(friendrequest, False)
        if allyinfo is not None:
            data.append(allyinfo)

    return jsonify(data)


@friends_bp.route(
    "/persist/friends_deny_request/<string:player_id>/<string:invite_id>",
    methods=["GET"],
)
def PersistFriendsDenyRequest(player_id, invite_id):
    db_user = Player.query.filter_by(username=player_id).first()
    if db_user is None:
        return make_response("No player found!", 400)

    UpdateLastOnline(player_id)

    # remove friend request
    player_requests = json.loads(db_user.friend_requests)
    player_requests.remove(invite_id)
    db_user.friend_requests = json.dumps(player_requests)

    db.session.commit()
    return jsonify({"success": True})


@friends_bp.route("/persist/friends_confirm_request_withmyinfoDW/", methods=["POST"])
def PersistFriendsConfirmRequestWithMyInfo():
    clientData = parse_qs(request.get_data().decode("utf-8"))
    clientData = {k: v[0] if len(v) == 1 else v for k, v in clientData.items()}

    UpdateLastOnline(clientData["player_id"])

    db_user = Player.query.filter_by(username=clientData["player_id"]).first()
    if db_user is None:
        return make_response("No player found!", 400)

    # Player ally check
    allycheck = AllyBoxSpaceNotExceeded(clientData["player_id"])
    if allycheck == False:
        return jsonify({"success": True, "info": "exceed me"})

    # friend ally check
    friendallycheck = AllyBoxSpaceNotExceeded(clientData["invite_id"])
    if friendallycheck == False:
        return jsonify({"success": True, "info": "exceed"})

    # remove friend request
    player_requests = json.loads(db_user.friend_requests)
    player_requests.remove(clientData["invite_id"])
    db_user.friend_requests = json.dumps(player_requests)

    # add friend
    player_friends = json.loads(db_user.friends)
    player_friends.append(clientData["invite_id"])
    db_user.friends = json.dumps(player_friends)

    # add self to friend's friend list
    friend_user = Player.query.filter_by(username=clientData["invite_id"]).first()

    if friend_user is None:
        return make_response("No player found!", 400)

    friend_friends = json.loads(friend_user.friends)
    friend_friends.append(clientData["player_id"])
    friend_user.friends = json.dumps(friend_friends)

    db.session.commit()

    return jsonify({"success": True})


@friends_bp.route(
    "/persist/friends_remove/<string:player_id>/<string:invite_id>", methods=["GET"]
)
def PersistFriendsRemove(player_id, invite_id):
    db_user = Player.query.filter_by(username=player_id).first()
    if db_user is None:
        return make_response("No player found!", 400)

    # remove friend
    player_friends = json.loads(db_user.friends)
    player_friends.remove(invite_id)
    db_user.friends = json.dumps(player_friends)

    # remove self from friend
    friend_user = Player.query.filter_by(username=invite_id).first()

    if friend_user is None:
        return make_response("No player found!", 400)

    friend_friends = json.loads(friend_user.friends)
    friend_friends.remove(player_id)
    friend_user.friends = json.dumps(friend_friends)

    db.session.commit()

    return jsonify({"success": True})


@friends_bp.route("/persist/friends_informationDW/", methods=["POST"])
def PersistFriendsInformationDW():
    content_type = request.content_type or ""
    if "json" in content_type:
        clientData = request.get_json(silent=True) or {}
    else:
        clientData = parse_qs(request.get_data().decode("utf-8"))
        clientData = {k: v[0] if len(v) == 1 else v for k, v in clientData.items()}

    player_id = clientData.get("player_id") or clientData.get("user_id") or clientData.get("userId")
    if not player_id:
        return make_response("Missing player_id", 400)

    db_user = Player.query.filter_by(username=player_id).first()
    if db_user is None:
        return make_response("No player found!", 400)

    UpdateLastOnline(player_id)

    data = []

    player_friends = json.loads(db_user.friends)
    for friend in player_friends:
        if IsUserBanned(friend):
            continue
        allyinfo = GetAllyInfo(friend, True)
        if allyinfo is not None:
            data.append(allyinfo)

    return jsonify(data)


@friends_bp.route("/persist/friends_update_myinfoDW/", methods=["POST"])
def PersistFriendsUpdateMyInfo():
    """Reset the caller's accumulated help counts after they collect the assist
    (Wishbone) reward. The client reads helpcount/anonymoushelpcount fresh from
    the server, shows the reward, then calls this to clear them (resethelp /
    resetahelp). Without it the reward re-fired on every login."""
    clientData = parse_qs(request.get_data().decode("utf-8"))
    clientData = {k: v[0] if len(v) == 1 else v for k, v in clientData.items()}

    player_id = (
        clientData.get("player_id")
        or clientData.get("userid")
        or clientData.get("user_id")
        or clientData.get("id")
    )
    if not player_id:
        return jsonify({"success": True})

    db_user = Player.query.filter_by(username=player_id).first()
    if db_user is None:
        return make_response("No player found!", 404)

    def _truthy(v):
        return str(v).strip().lower() in ("1", "true", "yes", "on")

    changed = False
    if _truthy(clientData.get("resethelp")):
        db_user.helpcount = 0
        changed = True
    if _truthy(clientData.get("resetahelp")):
        db_user.anonymoushelpcount = 0
        changed = True
    if changed:
        db.session.commit()

    return jsonify({"success": True})
