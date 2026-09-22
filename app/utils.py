import base64
import copy
import gzip
import hashlib
import hmac
import json
import os
import shutil
import time as _time
from datetime import datetime
from io import BytesIO

import bisect

import discord_webhook
from flask import Request

from app import db, badcharaters
from app.models import Admin, AdminActivity, Bans, Player

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_hash_string(source_value, key):
    hmac_sha256 = hmac.new(
        key.encode("utf-8"), source_value.encode("utf-8"), hashlib.sha256
    )
    return hmac_sha256.hexdigest()


def Log(category, message):
    os.makedirs(os.path.join(ROOT_DIR, "data/persist/logs"), exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    t = datetime.now().strftime("%H:%M:%S")
    with open(os.path.join(ROOT_DIR, "data/persist/logs/" + date + ".txt"), "a") as f:
        log = f"{t} - [{category.upper()}] - {message} \n"
        f.write(log)


def DiscordWebhookMessage(message):
    newActivity = AdminActivity(time=int(_time.time()), message=message)
    db.session.add(newActivity)
    db.session.commit()

    if not os.path.exists("discordwebhookurl"):
        return
    else:
        with open("discordwebhookurl", "r") as f:
            url = f.read()
    try:
        webhook = discord_webhook.DiscordWebhook(url=url, content=message)
        webhook.execute()
    except Exception:
        Log("admin", "Failed to send webhook message: " + message)


def DecryptGameData(game):
    if game is None or game == b"" or game == b" " or game == "":
        return None
    if isinstance(game, str):
        input_str = game
    else:
        input_str = game.decode("utf-8")
    index = input_str.find("&data=")
    if index == -1:
        try:
            return json.loads(input_str)
        except Exception:
            return None
    encoded_data = input_str[index + 6:]
    array = base64.b64decode(encoded_data)
    try:
        with gzip.GzipFile(fileobj=BytesIO(array), mode="rb") as gz:
            decoded_data = gz.read().decode("utf-8")
    except Exception:
        Log("admin", "Failed to decrypt game data")
        return None

    decoded_data = (
        decoded_data.replace(",}", "}")
        .replace(",],", "],")
        .replace(",]", "]")
        .replace(",,", ",")
    )

    json_start = decoded_data.find("{")
    if json_start > 0:
        decoded_data = decoded_data[json_start:]

    json_end = decoded_data.rfind("}")
    if json_end >= 0 and json_end < len(decoded_data) - 1:
        decoded_data = decoded_data[:json_end + 1]

    try:
        return json.loads(decoded_data)
    except Exception as e:
        Log("admin", "Failed to parse game data JSON: " + str(e))
        return None


def EncryptGameData(game, username=""):
    json_str = json.dumps(game, separators=(",", ":"))
    compressed = gzip.compress(json_str.encode("utf-8"))
    encoded = base64.b64encode(compressed).decode("utf-8")
    if username:
        prefix = "username=" + username + "&data="
    else:
        prefix = "&data="
    return (prefix + encoded).encode("utf-8")


def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


_RANK_XP_CACHE = None


def _LoadRankXPTable():
    global _RANK_XP_CACHE
    if _RANK_XP_CACHE is not None:
        return _RANK_XP_CACHE

    path = os.path.join(ROOT_DIR, "data/persist/Blueprints/db_XPTables.json")
    rank_to_xp = {}
    xp_thresholds = []
    ranks = []

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                tables = json.load(f)
            for r in tables:
                if "Level" in r and "PlayerRank" in r:
                    lvl = int(r["Level"])
                    xp = int(r["PlayerRank"])
                    rank_to_xp[lvl] = xp
                    xp_thresholds.append(xp)
                    ranks.append(lvl)
        except Exception as e:
            Log("admin", f"Failed to load db_XPTables.json: {e}")

    _RANK_XP_CACHE = (rank_to_xp, xp_thresholds, ranks)
    return _RANK_XP_CACHE


def GetRankXPTable():
    rank_to_xp, _, _ = _LoadRankXPTable()
    return rank_to_xp


def GetXPForRank(rank: int) -> int:
    try:
        rank = int(rank)
    except (ValueError, TypeError):
        return 0
    rank_to_xp, _, ranks = _LoadRankXPTable()
    if not rank_to_xp or rank <= 1:
        return 0
    max_rank = ranks[-1] if ranks else 999
    if rank >= max_rank:
        return rank_to_xp.get(max_rank, 496423604)
    return rank_to_xp.get(rank, 0)


_PVP_RANK_CACHE = None


def _LoadPvpRanks():
    global _PVP_RANK_CACHE
    if _PVP_RANK_CACHE is not None:
        return _PVP_RANK_CACHE

    path = os.path.join(ROOT_DIR, "data/persist/Blueprints/db_PVPRanks.json")
    mapping = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for row in json.load(f):
                    if "Rank" in row:
                        rank = int(row["Rank"])
                        mapping[rank] = (
                            row.get("ShortRankName")
                            or row.get("RankName")
                            or ("Rank " + str(rank))
                        )
        except Exception as e:
            Log("admin", f"Failed to load db_PVPRanks.json: {e}")

    _PVP_RANK_CACHE = mapping
    return mapping


def GetPvpRankName(level):
    """Return the PVP league name for a MultiplayerLevel (1 = Super Amadeus)."""
    try:
        level = int(level)
    except (ValueError, TypeError):
        return ""
    return _LoadPvpRanks().get(level, "")


_TUTORIAL_CREATURE_CACHE = None


def GetTutorialOnlyCreatureIds():
    """Return the set of creature IDs flagged TutorialOnly in the blueprints.

    These are non-collectible tutorial/opponent creatures. Granting them to a
    player makes the game client mark the save as tampered (Zxcvbnm = 1).
    """
    global _TUTORIAL_CREATURE_CACHE
    if _TUTORIAL_CREATURE_CACHE is not None:
        return _TUTORIAL_CREATURE_CACHE

    path = os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Creatures.json")
    ids = set()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for creature in json.load(f):
                    if (
                        str(creature.get("TutorialOnly", "")).lower() == "true"
                        and creature.get("ID")
                    ):
                        ids.add(creature["ID"])
        except Exception as e:
            Log("admin", f"Failed to load db_Creatures.json: {e}")

    _TUTORIAL_CREATURE_CACHE = ids
    return ids


def IsTutorialOnlyCreature(creature_id):
    return creature_id in GetTutorialOnlyCreatureIds()


_LEADER_BLUEPRINT_CACHE = None


def _LoadLeaderBlueprints():
    """Return (by_id, skin_to_base, base_to_skins) for db_Leaders.json."""
    global _LEADER_BLUEPRINT_CACHE
    if _LEADER_BLUEPRINT_CACHE is not None:
        return _LEADER_BLUEPRINT_CACHE

    path = os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Leaders.json")
    by_id = {}
    skin_to_base = {}
    base_to_skins = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for leader in json.load(f):
                    leader_id = leader.get("ID")
                    if not leader_id:
                        continue
                    by_id[leader_id] = leader
                    skin_of = leader.get("SkinOf")
                    if skin_of:
                        skin_to_base[leader_id] = skin_of
                        base_to_skins.setdefault(skin_of, []).append(leader_id)
        except Exception as e:
            Log("admin", f"Failed to load db_Leaders.json: {e}")

    _LEADER_BLUEPRINT_CACHE = (by_id, skin_to_base, base_to_skins)
    return _LEADER_BLUEPRINT_CACHE


def GetLeaderSkinBase(leader_id):
    """Return the base hero ID if this ID is a skin, else None."""
    _, skin_to_base, _ = _LoadLeaderBlueprints()
    return skin_to_base.get(leader_id)


def GetLeaderSkins(base_leader_id):
    """Return the list of skin IDs belonging to a base hero."""
    _, _, base_to_skins = _LoadLeaderBlueprints()
    return base_to_skins.get(base_leader_id, [])


def NormalizeLeaders(leaders):
    """Fold skin entries into their base hero's OwnedSkins.

    Skins must not be stored as independent leaders. Returns
    (normalized_leaders, list_of_repairs). Existing data is preserved.
    """
    repairs = []
    if not isinstance(leaders, list):
        return [], ["Reset invalid 'Leaders' to an empty list."]

    _, skin_to_base, _ = _LoadLeaderBlueprints()

    by_id = {}
    order = []
    for entry in leaders:
        if not isinstance(entry, dict):
            continue
        leader_id = entry.get("ID")
        if not leader_id:
            continue
        if leader_id not in by_id:
            by_id[leader_id] = entry
            order.append(leader_id)

    for leader_id in order:
        entry = by_id[leader_id]
        if not isinstance(entry.get("OwnedSkins"), list):
            entry["OwnedSkins"] = []
        if not entry.get("Skin"):
            entry["Skin"] = leader_id

    # Make sure every referenced base hero entry exists.
    for leader_id in list(order):
        base = skin_to_base.get(leader_id)
        if base and base not in by_id:
            by_id[base] = {"ID": base, "Skin": base, "OwnedSkins": []}
            order.append(base)
            repairs.append(
                "Added missing base hero '" + base + "' for skin '" + leader_id + "'."
            )

    # Merge skins into their base hero.
    handled = set()
    for leader_id in order:
        base = skin_to_base.get(leader_id)
        if base and base in by_id and base != leader_id:
            base_entry = by_id[base]
            if leader_id not in base_entry["OwnedSkins"]:
                base_entry["OwnedSkins"].append(leader_id)
                repairs.append(
                    "Moved skin '" + leader_id + "' into '" + base + "'.OwnedSkins."
                )
            handled.add(leader_id)

    result = [by_id[leader_id] for leader_id in order if leader_id not in handled]
    return result, repairs


def GetRankForXP(xp: int) -> int:
    try:
        xp = int(xp)
    except (ValueError, TypeError):
        return 1
    _, xp_thresholds, ranks = _LoadRankXPTable()
    if not xp_thresholds or not ranks or xp <= 0:
        return 1
    idx = bisect.bisect_right(xp_thresholds, xp) - 1
    if idx < 0:
        return 1
    return ranks[idx]



def GetNameFromSave(save):
    try:
        game = DecryptGameData(save)
    except Exception:
        return None
    if game is None:
        return None
    return game.get("MultiplayerPlayerName")


# --- Game save validation & repair -----------------------------------------
# Known top-level fields a healthy Card Wars Kingdom save should contain, with
# safe defaults. Used by Fix Save to fill in anything a broken save is missing.
SAVE_FIELD_DEFAULTS = {
    "ActiveCalendar": "A",
    "ActivePvpSeason": "",
    "AddedStones": "0",
    "AdminLeaderLevel": 1,
    "AdminPlayerLevel": 1,
    "AllyBoxSpace": 30,
    "Badges": [],
    "BattleHistory": [],
    "BestMultiplayerLevel": 25,
    "CDExpeditionSlots": 0,
    "CDExpeditions": [],
    "CardBacks": ["Default"],
    "CardCollection": [],
    "Collection": [],
    "ConfirmedTOSVersion": 0,
    "CreatureSort": [],
    "CustomizationCurrency": 0,
    "DailyMissionTimestamp": "0",
    "DateOfBirth": 0,
    "DeletedMail": [],
    "DungeonMaps": {},
    "DungeonStars": {},
    "EvoMatCollection": [],
    "EvolutionShards": 0,
    "ExCardSort": [],
    "ExpeditionRefreshTime": 0,
    "ExtraPvpStamina": 0,
    "ExtraQuestStamina": 0,
    "FBInviteRewards": [],
    "FreeHardCurrency": 0,
    "FriendInvites": 0,
    "GachaCooldowns": [],
    "GachaKeys": [],
    "HasAuthenticated": 1,
    "HelperSort": [],
    "IgnoredPlayers": [],
    "InstalledDate": 0,
    "Inventory": [],
    "InventorySpace": 30,
    "InviteCodeRedeemed": 0,
    "InviteGroup": 0,
    "LastAccessUTC": 0,
    "LastDailySpinTime": "0",
    "LastKnownLocation": "US",
    "LastOneTimeCalendarDateClaimed": "0",
    "Leaders": [],
    "Loadouts": [],
    "Mails": [],
    "MapClickInterval": 0,
    "MissionProgress": {
        "DailyMissions": [],
        "DailyProgress": {},
        "GlobalMissions": [],
        "GlobalProgress": {},
    },
    "MultiplayerLevel": 25,
    "MultiplayerPlayerName": "",
    "MultiplayerWinStreak": 0,
    "MyHelperCreatureID": 0,
    "OneTimeCalendarDaysClaimed": 0,
    "PaidHardCurrency": 0,
    "PlayerName": "",
    "PlayersLastSavedLevel": 1,
    "PointsInMultiplayerLevel": 0,
    "Portraits": [],
    "PvpBattles": 0,
    "PvpCurrency": 0,
    "PvpExtremeMatchStarted": 0,
    "PvpMatchStarted": 0,
    "PvpPlayed": 0,
    "PvpRankRewardsGranted": -1,
    "PvpStaminaTime": 0,
    "QuestSelectScrollPos": 0,
    "QuestStars": [],
    "RandomDungeonLevel": 1,
    "RankUpInventoryGiven": "False",
    "RankXP": 0,
    "ReadWriteParam": 0,
    "SaleEndTime": 0,
    "SaleRestartCooldown": 0,
    "SaleShowCooldown": 0,
    "Sales": [],
    "SecurityKeyValue": "0000",
    "SelectedCardBack": "Default",
    "SelectedLoadout": 0,
    "SelectedPortrait": "Default",
    "SoftCurrency": 0,
    "SpecialQuests": {},
    "SpeedUps": [],
    "StaminaTime": 0,
    "TitleDisplayTime": 0,
    "Titles": [],
    "TopCompletedQuestId": 0,
    "TopShownCompletedQuestId": 0,
    "TownTiltCam": 0,
    "TutorialsDone": [],
    "UIDFixApplied": 0,
    "Unlocks": [],
    "UsedRedeemCodes": [],
    "XPMatCollection": [],
    "Zxcvbnm": 0,
    "selectedLang": "N",
}

# Subset that the game client relies on to boot correctly. Used for detection
# so normal saves missing optional newer fields are not flagged as broken.
CRITICAL_SAVE_FIELDS = [
    "PlayerName",
    "MultiplayerPlayerName",
    "SoftCurrency",
    "PaidHardCurrency",
    "FreeHardCurrency",
    "PvpCurrency",
    "EvolutionShards",
    "InventorySpace",
    "MultiplayerLevel",
    "RankXP",
    "PlayersLastSavedLevel",
    "AdminLeaderLevel",
    "AdminPlayerLevel",
    "Inventory",
    "CardCollection",
    "Collection",
    "Leaders",
    "Loadouts",
    "Mails",
    "Unlocks",
    "TutorialsDone",
    "MissionProgress",
    "XPMatCollection",
    "EvoMatCollection",
    "QuestStars",
    "Zxcvbnm",
    "StaminaTime",
    "PvpStaminaTime",
    "InstalledDate",
    "HasAuthenticated",
    "selectedLang",
]

_CONTAINER_FIELDS = {
    key for key, value in SAVE_FIELD_DEFAULTS.items() if isinstance(value, (list, dict))
}

# Valid inventory item discriminators: creature, action card, XP material and
# evolution material.
INVENTORY_ITEM_TYPES = ("CR", "CA", "XP", "EV")


def _CopyDefault(value):
    if isinstance(value, (list, dict)):
        return json.loads(json.dumps(value))
    return value


def FindBrokenSaveIssues(game):
    """Inspect a decrypted save and return a list of human-readable problems."""
    if not isinstance(game, dict):
        return ["Game save is not a valid object."]

    issues = []
    for key in CRITICAL_SAVE_FIELDS:
        if key not in game:
            issues.append("Missing field: " + key)

    for key in _CONTAINER_FIELDS:
        if key not in game:
            continue
        default = SAVE_FIELD_DEFAULTS[key]
        value = game[key]
        if isinstance(default, list) and not isinstance(value, list):
            issues.append("Field '" + key + "' should be a list.")
        elif isinstance(default, dict) and not isinstance(value, dict):
            issues.append("Field '" + key + "' should be an object.")

    inventory = game.get("Inventory")
    if isinstance(inventory, list):
        seen_uids = set()
        for index, item in enumerate(inventory):
            if not isinstance(item, dict):
                issues.append("Inventory item #" + str(index) + " is not an object.")
                continue
            item_type = item.get("_T")
            if item_type not in INVENTORY_ITEM_TYPES:
                issues.append(
                    "Inventory item #" + str(index) + " has an invalid or missing type (_T)."
                )
            if not item.get("ID"):
                issues.append("Inventory item #" + str(index) + " is missing its ID.")
            if item_type == "CR":
                if "UniqueID" not in item:
                    issues.append(
                        "Creature '" + str(item.get("ID")) + "' is missing its UniqueID."
                    )
                else:
                    uid = item.get("UniqueID")
                    if uid in seen_uids:
                        issues.append(
                            "Duplicate creature UniqueID "
                            + str(uid)
                            + " ('"
                            + str(item.get("ID"))
                            + "')."
                        )
                    seen_uids.add(uid)
                for field in ("Xp", "StarRating"):
                    if field not in item:
                        issues.append(
                            "Creature '" + str(item.get("ID")) + "' is missing " + field + "."
                        )
            elif item_type == "CA":
                if "UniqueID" not in item:
                    issues.append(
                        "Action card '" + str(item.get("ID")) + "' is missing its UniqueID."
                    )

    leaders = game.get("Leaders")
    if isinstance(leaders, list):
        _, skin_to_base, _ = _LoadLeaderBlueprints()
        seen_leaders = set()
        for index, entry in enumerate(leaders):
            if not isinstance(entry, dict):
                issues.append("Leader item #" + str(index) + " is not an object.")
                continue
            leader_id = entry.get("ID")
            if not leader_id:
                issues.append("Leader item #" + str(index) + " is missing its ID.")
                continue
            if leader_id in seen_leaders:
                issues.append("Duplicate leader '" + str(leader_id) + "'.")
            seen_leaders.add(leader_id)
            if leader_id in skin_to_base:
                issues.append(
                    "Skin '"
                    + str(leader_id)
                    + "' is stored as an independent leader (should be inside '"
                    + str(skin_to_base[leader_id])
                    + "'.OwnedSkins)."
                )
            if "OwnedSkins" in entry and not isinstance(entry["OwnedSkins"], list):
                issues.append("Leader '" + str(leader_id) + "' has an invalid OwnedSkins value.")
    elif leaders is not None:
        issues.append("Field 'Leaders' should be a list.")

    if not game.get("MultiplayerPlayerName"):
        issues.append("Missing player display name (MultiplayerPlayerName).")
    if not game.get("PlayerName"):
        issues.append("Missing PlayerName (account UUID).")

    return issues


def RepairGameData(game, username="", fallback_name=""):
    """Fill in missing/broken fields without deleting existing data.

    Returns a tuple of (repaired_game, list_of_repair_descriptions).
    """
    repairs = []
    if not isinstance(game, dict):
        game = {}
        repairs.append("Reinitialized an invalid save as an object.")

    effective_rank = max(
        safe_int(game.get("PlayersLastSavedLevel", 0)),
        GetRankForXP(safe_int(game.get("RankXP", 0))),
        1,
    )

    special_defaults = {
        "AdminLeaderLevel": effective_rank,
        "AdminPlayerLevel": effective_rank,
        "PlayersLastSavedLevel": effective_rank,
    }

    for key, default in SAVE_FIELD_DEFAULTS.items():
        default = special_defaults.get(key, default)
        if key == "PlayerName" and username:
            default = username
        elif key == "MultiplayerPlayerName":
            default = fallback_name or username or "Player"
        elif key == "InstalledDate":
            default = int(_time.time())

        if key not in game:
            game[key] = _CopyDefault(default)
            repairs.append("Added missing field: " + key)
            continue

        value = game[key]
        if isinstance(default, list) and not isinstance(value, list):
            game[key] = []
            repairs.append("Reset invalid field '" + key + "' to an empty list.")
        elif isinstance(default, dict) and not isinstance(value, dict):
            game[key] = _CopyDefault(default)
            repairs.append("Reset invalid field '" + key + "' to a default object.")

    if not game.get("MultiplayerPlayerName"):
        game["MultiplayerPlayerName"] = fallback_name or username or "Player"
        repairs.append("Restored the missing player display name.")
    if not game.get("PlayerName") and username:
        game["PlayerName"] = username
        repairs.append("Restored the missing PlayerName (UUID).")

    inventory = game.get("Inventory")
    if not isinstance(inventory, list):
        inventory = []
        game["Inventory"] = inventory

    max_uid = 0
    for item in inventory:
        if isinstance(item, dict) and "UniqueID" in item:
            max_uid = max(max_uid, safe_int(item.get("UniqueID", 0)))

    seen_uids = set()
    for index, item in enumerate(inventory):
        if not isinstance(item, dict):
            continue

        item_type = item.get("_T")
        if item_type not in INVENTORY_ITEM_TYPES:
            if "CreatureUID" in item or "CreatureSlot" in item:
                item_type = "CA"
            elif "Xp" in item or "StarRating" in item or "Passive" in item:
                item_type = "CR"
            elif item.get("ID", "").startswith("AWK_MAT_") or item.get("ID", "").startswith("EVMAT_"):
                item_type = "EV"
            else:
                item_type = "CR"
            item["_T"] = item_type
            repairs.append(
                "Recovered the missing type for inventory item #" + str(index) + "."
            )

        if item_type in ("CR", "CA"):
            uid = item.get("UniqueID")
            if uid is None or uid in seen_uids:
                max_uid += 1
                item["UniqueID"] = max_uid
                seen_uids.add(max_uid)
                repairs.append(
                    "Assigned new UniqueID "
                    + str(max_uid)
                    + " to '"
                    + str(item.get("ID"))
                    + "'."
                )
            else:
                seen_uids.add(uid)

        if item_type == "CR":
            if "Xp" not in item:
                item["Xp"] = 0
                repairs.append("Added missing Xp for creature '" + str(item.get("ID")) + "'.")
            if "StarRating" not in item:
                item["StarRating"] = 1
                repairs.append(
                    "Added missing StarRating for creature '" + str(item.get("ID")) + "'."
                )
            item.setdefault("Favorite", 0)
            item.setdefault("Passive", 1)
            item.setdefault("PassiveFeeds", 0)

    # Fold any skins stored as independent leaders into their base hero.
    if isinstance(game.get("Leaders"), list):
        game["Leaders"], leader_repairs = NormalizeLeaders(game["Leaders"])
        repairs.extend(leader_repairs)

    return game, repairs


# During a progress transfer these fields stay with the target account instead
# of being copied from the source (identity, currencies and PVP ban flag).
TRANSFER_CURRENCY_FIELDS = [
    "SoftCurrency",
    "PaidHardCurrency",
    "FreeHardCurrency",
    "PvpCurrency",
    "EvolutionShards",
    "CustomizationCurrency",
]
TRANSFER_PRESERVE_FIELDS = [
    "PlayerName",
    "MultiplayerPlayerName",
    "Zxcvbnm",
] + TRANSFER_CURRENCY_FIELDS


def BuildTransferredGame(source_game, target_game, target_username, target_name=""):
    """Copy all progress from a source save onto a target save.

    The target keeps its own identity (UUID/display name), currencies and PVP
    ban flag. Returns the repaired target game dict.
    """
    if not isinstance(source_game, dict):
        source_game = {}
    if not isinstance(target_game, dict):
        target_game = {}

    new_game = copy.deepcopy(source_game)
    for field in TRANSFER_PRESERVE_FIELDS:
        if field in TRANSFER_CURRENCY_FIELDS:
            new_game[field] = target_game.get(field, 0)
        elif target_game.get(field) not in (None, ""):
            new_game[field] = target_game[field]

    new_game["PlayerName"] = target_username
    new_game["MultiplayerPlayerName"] = (
        target_name
        or target_game.get("MultiplayerPlayerName")
        or target_username
    )

    new_game, _ = RepairGameData(
        new_game,
        username=target_username,
        fallback_name=new_game["MultiplayerPlayerName"],
    )
    return new_game


def IPFromRequest(request: Request):
    ip = request.remote_addr
    if request.headers.getlist("X-Forwarded-For"):
        ip = request.headers.getlist("X-Forwarded-For")[0]
    return ip


def PlayerLog(ip, player, message):
    from app.models import Logs
    db_log = Logs(
        date=datetime.now().strftime("%Y-%m-%d"),
        time=datetime.now().strftime("%H:%M:%S"),
        player=player,
        ip=ip,
        message=message,
    )
    db.session.add(db_log)
    db.session.commit()


def InvalidUsername(username):
    username = username.lower()
    for char in badcharaters:
        if char in username:
            return True
    if username == "ua" or username == "guest":
        return True
    return False


def _BanActive(ban):
    if ban is None:
        return False
    expires = getattr(ban, "expires", None)
    if expires is None or int(expires) == 0:
        return True
    return int(expires) > int(_time.time())


def IsUserBanned(username, ip=None):
    db_user = Bans.query.filter_by(username=username).first()
    if _BanActive(db_user):
        return True
    if ip is None:
        return False
    db_ip = Bans.query.filter_by(username=ip).first()
    if _BanActive(db_ip):
        return True
    return False


BAN_DURATION_PRESETS = {
    "1h": 3600,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
    "3d": 259200,
    "1w": 604800,
    "2w": 1209600,
    "1m": 2592000,
}

BAN_DURATION_UNITS = {
    "hours": 3600,
    "days": 86400,
    "weeks": 604800,
    "months": 2592000,
}


def GetBanExpiry(duration, amount=0, unit="hours"):
    """Return a unix expiry timestamp for a ban duration. 0 means permanent."""
    if not duration or duration == "perm":
        return 0
    now = int(_time.time())
    if duration in BAN_DURATION_PRESETS:
        return now + BAN_DURATION_PRESETS[duration]
    if duration == "custom":
        multiplier = BAN_DURATION_UNITS.get(unit, 3600)
        try:
            amount = int(amount)
        except (ValueError, TypeError):
            amount = 1
        if amount < 1:
            amount = 1
        return now + amount * multiplier
    return 0


def FormatBanExpiry(expires):
    if expires is None or int(expires) == 0:
        return "Permanent"
    try:
        return datetime.utcfromtimestamp(int(expires)).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, TypeError, OSError):
        return "Permanent"


def SystemBan(username):
    Log("admin", "SYSTEM BANNED " + username)
    if not IsUserBanned(username):
        newban = Bans(
            username=username,
            bantype="userid",
            author="SYSTEM",
            time=int(_time.time()),
            expires=0,
        )
        db.session.add(newban)
        db.session.commit()
        DiscordWebhookMessage("SYSTEM performed ban on ID: " + username)


def UpdateLastOnline(player_id):
    user = Player.query.filter_by(username=player_id).first()
    if user is None:
        return None
    user.last_online = int(_time.time())
    db.session.commit()


def AllyBoxSpaceNotExceeded(player_id):
    user = Player.query.filter_by(username=player_id).first()
    if user is None:
        return None
    friends = json.loads(user.friends)
    friends_count = 0
    for friend in friends:
        if IsUserBanned(friend):
            continue
        friend_user = Player.query.filter_by(username=friend).first()
        if friend_user is None:
            continue
        friends_count += 1
    return friends_count < user.allyboxspace


def GetAllyInfo(player_id, isally):
    db_user = Player.query.filter_by(username=player_id).first()
    if db_user is None:
        return None
    if db_user.multiplayer_name is None:
        return None
    data = {
        "fields": {
            "user_id": db_user.username,
            "name": db_user.multiplayer_name,
            "icon": db_user.icon,
            "rankxp": db_user.leader_level,
            "helpcount": db_user.helpcount if db_user.helpcount is not None else "0",
            "anonymoushelpcount": (
                db_user.anonymoushelpcount
                if db_user.anonymoushelpcount is not None
                else "0"
            ),
            "helpercreatureid": db_user.leader,
            "helpercreature": db_user.helper_creature,
            "landscapes": db_user.landscapes,
            "ally": "1" if isally else "0",
            "sincelastactivedate": str(int(_time.time()) - db_user.last_online),
        }
    }
    return data


def Backup():
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    os.makedirs(os.path.join(ROOT_DIR, "backup/" + now), exist_ok=True)
    shutil.copy(os.path.join(ROOT_DIR, "instance/cardwarskingdom.db"), os.path.join(ROOT_DIR, f"backup/{now}/cardwarskingdom.db"))
    shutil.copytree(os.path.join(ROOT_DIR, "data/persist"), os.path.join(ROOT_DIR, f"backup/{now}/persist"))
    shutil.make_archive(os.path.join(ROOT_DIR, "backup/" + now), "zip", os.path.join(ROOT_DIR, "backup/" + now))
    shutil.rmtree(os.path.join(ROOT_DIR, "backup/" + now))
    Log("admin", "Backed up")
    return True


def time_ago_string(date_time):
    now = datetime.now()
    time_difference = now - date_time
    hours = time_difference.seconds // 3600
    minutes = (time_difference.seconds // 60) % 60
    if time_difference.days > 0:
        return f"{time_difference.days} days ago"
    elif hours > 0:
        return f"{hours} {'hour' if hours == 1 else 'hours'} ago"
    elif minutes > 0:
        return f"{minutes} {'minute' if minutes == 1 else 'minutes'} ago"
    else:
        return f"{time_difference.seconds} seconds ago"


def isAdmin(user):
    if not user.is_authenticated:
        return False
    db_user = Admin.query.filter_by(username=user.username).first()
    return db_user is not None


def GetPlayerWins(player_id):
    db_user = Player.query.filter_by(username=player_id).first()
    if db_user is None:
        return None
    if db_user.game is None or db_user.game == b"" or db_user.game == b" ":
        return None
    if IsUserBanned(player_id):
        return None
    try:
        game = DecryptGameData(db_user.game)
    except Exception:
        return None
    if game["Zxcvbnm"]:
        return None
    currentSeason = ""
    with open(os.path.join(ROOT_DIR, "data/persist/Blueprints/db_PVPSeasons.json")) as f:
        seasons = json.load(f)
        seasons = list(filter(lambda x: "EndDate" in x, seasons))
        for season in seasons:
            if (
                int(_time.time())
                < datetime.strptime(season["EndDate"], "%m/%d/%Y").timestamp()
            ):
                currentSeason = season["Season"]
                break
        if currentSeason == "":
            currentSeason = seasons[-1]["Season"]
    if game["ActivePvpSeason"] != currentSeason:
        return None
    if int(game["PvpPlayed"]) == 0:
        return None
    wins = 0
    for battle in game["BattleHistory"]:
        if battle["youWon"] == True and battle["season"] == currentSeason:
            wins += 1
    return wins


def GetPvpBanlist():
    filepath = os.path.join(ROOT_DIR, "data/persist/pvp_banlist.json")
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            Log("persist", f"Error reading pvp_banlist.json: {e}")
    return {
        "active_bans": [
            {
                "expires": "2099-12-31T23:59:59Z",
                "id": "global_permanent_bans",
                "name": "Permanent Bans (All Seasons)",
                "starts": "2020-01-01T00:00:00Z",
            }
        ],
        "banned_creatures": [],
        "banned_leaders": [],
    }


def SavePvpBanlist(data):
    filepath = os.path.join(ROOT_DIR, "data/persist/pvp_banlist.json")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return True

