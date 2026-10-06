import re
import time as _time

from ._common import *


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


def FormatTimestamp(value, utc=False):
    """Render a stored unix timestamp for display without mutating the row."""
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return str(value)
    try:
        if utc:
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return str(value)


def PersistPath(*parts):
    """Path inside the `data/persist` folder."""
    return os.path.join(ROOT_DIR, "data/persist", *parts)


def ReadPersistText(name, default=""):
    """Read a small text file from `data/persist`, `default` when missing."""
    try:
        with open(PersistPath(name), "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default


def EnsurePersistLayout():
    """Repair the `data/persist` layout expected by the code.

    The blueprint folder is referenced as `Blueprints/` while older checkouts
    tracked it as `blueprints/`; on a case-sensitive filesystem (Heroku) that
    mismatch makes every blueprint read fail.
    """
    persist_dir = os.path.join(ROOT_DIR, "data/persist")
    if not os.path.isdir(persist_dir):
        os.makedirs(persist_dir, exist_ok=True)
        return
    canonical = os.path.join(persist_dir, "Blueprints")
    if os.path.isdir(canonical):
        return
    try:
        for entry in os.listdir(persist_dir):
            if entry.lower() != "blueprints":
                continue
            source = os.path.join(persist_dir, entry)
            if not os.path.isdir(source):
                continue
            os.rename(source, canonical)
            Log("server", f"Renamed data/persist/{entry} -> Blueprints/")
            return
    except OSError as e:
        Log("server", f"Could not normalise data/persist/Blueprints: {e}")


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
    encoded_data = input_str[index + 6 :]
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
        decoded_data = decoded_data[: json_end + 1]

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
    # Return str: PostgreSQL text columns reject bytes (psycopg2 turns them
    # into a bytea hex literal and the save silently corrupts).
    return prefix + encoded


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
                    if str(
                        creature.get("TutorialOnly", "")
                    ).lower() == "true" and creature.get("ID"):
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


def FormatBlueprintName(name):
    """Convert a localization token into a readable blueprint name."""
    if not isinstance(name, str):
        return name

    name = name.strip()
    if name.startswith("!!"):
        name = name[2:]
    name = name.replace("_", " ")
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    if name.endswith(" NAME"):
        name = name[:-5].strip()
    return name


def FormatCreatureName(creature):
    """Readable creature name with its Evolve variant stripped.

    Blueprint names such as ``!!CornBall_Awaken_NAME`` become ``Corn Ball``;
    the variant (``Awaken``/``Base``) is returned separately so the UI can
    render it as a badge instead of inline text.
    """
    if not isinstance(creature, dict):
        return creature, ""
    creature_id = creature.get("ID", "")
    variant = ""
    if "_Awaken" in creature_id:
        variant = "Awaken"
    elif "_Base" in creature_id:
        variant = "Base"
    name = FormatBlueprintName(creature.get("Name", creature_id))
    if variant:
        name = re.sub(rf"\b{re.escape(variant)}\b", "", name)
        name = re.sub(r"\s+", " ", name).strip()
    return name, variant


_ACTION_CARD_TYPE_ALIASES = {
    "KEYWORD_MAGICATTACK": "Magic Attack",
}


def FormatLeaderName(leader):
    """Readable hero/leader name derived from the ID (``Leader_Finn`` -> ``Finn``).

    Real names (e.g. ``Summer Style Finn``) are kept; placeholder tokens that
    merely mirror the ID fall back to the ID with the ``Leader_`` prefix removed.
    """
    if not isinstance(leader, dict):
        return leader
    name = leader.get("Name", "")
    if name and not (name.startswith("!!") and name.endswith("_NAME")):
        return FormatBlueprintName(name)
    identifier = leader.get("ID", "")
    if identifier.startswith("Leader_"):
        identifier = identifier[len("Leader_"):]
    return FormatBlueprintName(identifier)


def FormatActionCardName(card):
    """Readable name for an action card.

    Most localization names merely mirror the card ID (``!!CORN_0022_NAME``), so
    the display name falls back to the ``UITexture`` when no real name exists
    (e.g. ``Spell_Corn_ThirdWind`` -> ``Corn Third Wind``).
    """
    if not isinstance(card, dict):
        return card
    name = card.get("Name", "")
    if name and not (name.startswith("!!") and name.endswith("_NAME")):
        return FormatBlueprintName(name)
    texture = card.get("UITexture", "") or ""
    for prefix in ("Spell_", "Spel_", "Leader_"):
        if texture.startswith(prefix):
            texture = texture[len(prefix):]
            break
    return FormatBlueprintName(texture)


def FormatActionCardType(card):
    """Readable card type derived from the card frame, falling back to TypeText."""
    if not isinstance(card, dict):
        return ""
    frame = card.get("CardFrame", "") or ""
    prefix = "UI_ActionCard_Frame_"
    if frame.startswith(prefix):
        return FormatBlueprintName(frame[len(prefix):])
    typetext = card.get("TypeText", "") or ""
    if typetext.startswith("!!"):
        typetext = typetext[2:]
    return _ACTION_CARD_TYPE_ALIASES.get(typetext, FormatBlueprintName(typetext))


_CREATURE_NAME_CACHE = None
_ACTION_CARD_NAME_CACHE = None


def GetCreatureNameMap():
    """Return ``{creature_id: display_name}`` for db_Creatures.json."""
    global _CREATURE_NAME_CACHE
    if _CREATURE_NAME_CACHE is not None:
        return _CREATURE_NAME_CACHE
    mapping = {}
    path = os.path.join(ROOT_DIR, "data/persist/Blueprints/db_Creatures.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for creature in json.load(f):
                    creature_id = creature.get("ID")
                    if creature_id:
                        mapping[creature_id] = FormatCreatureName(creature)[0]
        except Exception as e:
            Log("admin", f"Failed to load db_Creatures.json: {e}")
    _CREATURE_NAME_CACHE = mapping
    return mapping


def GetActionCardNameMap():
    """Return ``{card_id: display_name}`` for db_ActionCards.json."""
    global _ACTION_CARD_NAME_CACHE
    if _ACTION_CARD_NAME_CACHE is not None:
        return _ACTION_CARD_NAME_CACHE
    mapping = {}
    path = os.path.join(ROOT_DIR, "data/persist/Blueprints/db_ActionCards.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for card in json.load(f):
                    card_id = card.get("ID")
                    if card_id:
                        mapping[card_id] = FormatActionCardName(card)
        except Exception as e:
            Log("admin", f"Failed to load db_ActionCards.json: {e}")
    _ACTION_CARD_NAME_CACHE = mapping
    return mapping


def GetLeaderNameMap():
    """Return ``{leader_id: display_name}`` for db_Leaders.json."""
    by_id, _, _ = _LoadLeaderBlueprints()
    return {leader_id: FormatLeaderName(l) for leader_id, l in by_id.items()}


# --- Redeem code rewards ----------------------------------------------------
def ParseRedeemRewards(code_row):
    """Return a normalized list of reward dicts for a RedeemCode row.

    New codes store a JSON array in the ``rewards`` column; older codes keep a
    single reward in the ``reward_type``/``reward_amount``/``reward_item``
    columns, which are still honoured as a fallback.
    """
    rewards = []
    raw = getattr(code_row, "rewards", None)
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                rewards = [r for r in parsed if isinstance(r, dict)]
        except (ValueError, TypeError):
            rewards = []

    if not rewards:
        reward_type = getattr(code_row, "reward_type", "") or ""
        reward_item = (getattr(code_row, "reward_item", None) or "").strip()
        reward_amount = getattr(code_row, "reward_amount", 0) or 0
        if not reward_item and ":" in reward_type:
            reward_type, reward_item = reward_type.split(":", 1)
        if reward_type:
            rewards = [
                {
                    "type": reward_type,
                    "amount": reward_amount,
                    "item": reward_item,
                }
            ]

    normalized = []
    for reward in rewards:
        try:
            amount = int(reward.get("amount", 0))
        except (TypeError, ValueError):
            amount = 0
        normalized.append(
            {
                "type": (reward.get("type") or "").strip(),
                "amount": amount,
                "item": (reward.get("item") or "").strip(),
            }
        )
    return normalized


def ApplyRedeemReward(game, reward_type, reward_amount, reward_item):
    """Apply a single reward to a decrypted game dict (mutates in place).

    Returns ``(True, description)`` on success or ``(False, message)``.
    """
    reward_item = (reward_item or "").strip()
    try:
        reward_amount = int(reward_amount)
    except (TypeError, ValueError):
        reward_amount = 0

    if reward_type in ("HardCurrency", "PaidHardCurrency"):
        game["HardCurrency"] = game.get("HardCurrency", 0) + reward_amount
        game["PaidHardCurrency"] = game.get("PaidHardCurrency", 0) + reward_amount
        return True, f"{reward_amount} Gems"
    if reward_type == "FreeHardCurrency":
        game["FreeHardCurrency"] = game.get("FreeHardCurrency", 0) + reward_amount
        game["HardCurrency"] = game.get("HardCurrency", 0) + reward_amount
        return True, f"{reward_amount} Free Gems"
    if reward_type == "SoftCurrency":
        game["SoftCurrency"] = game.get("SoftCurrency", 0) + reward_amount
        return True, f"{reward_amount} Coins"
    if reward_type == "PvpCurrency":
        game["PvpCurrency"] = game.get("PvpCurrency", 0) + reward_amount
        return True, f"{reward_amount} Wishbones"
    if reward_type == "EvolutionShards":
        game["EvolutionShards"] = game.get("EvolutionShards", 0) + reward_amount
        return True, f"{reward_amount} Evolution Shards"
    if reward_type == "Creature":
        if not reward_item:
            return False, "No creature specified for this code"
        if game.get("Inventory") is None:
            game["Inventory"] = []
        next_uid = (
            max(
                [
                    item.get("UniqueID", 0)
                    for item in game["Inventory"]
                    if item.get("_T") == "CR"
                ],
                default=0,
            )
            + 1
        )
        stars = min(max(reward_amount, 1), 5) if reward_amount else 1
        game["Inventory"].append(
            {
                "_T": "CR",
                "ID": reward_item,
                "UniqueID": next_uid,
                "Xp": 0,
                "StarRating": stars,
                "Favorite": 0,
                "Passive": 1,
                "PassiveFeeds": 0,
            }
        )
        return True, f"{stars}★ {reward_item} Creature"
    if reward_type in ("ActionCard", "Card"):
        if not reward_item:
            return False, "No Auguments specified for this code"
        if game.get("CardCollection") is None:
            game["CardCollection"] = []
        if not any(c.get("ID") == reward_item for c in game["CardCollection"]):
            game["CardCollection"].append({"ID": reward_item, "Stat": 1})
        if game.get("Inventory") is None:
            game["Inventory"] = []
        count = max(1, reward_amount)
        for _ in range(count):
            next_uid = (
                max([item.get("UniqueID", 0) for item in game["Inventory"]], default=0)
                + 1
            )
            game["Inventory"].append(
                {
                    "_T": "CA",
                    "ID": reward_item,
                    "UniqueID": next_uid,
                    "Favorite": 0,
                    "CreatureUID": -1,
                    "CreatureSlot": 0,
                }
            )
        return True, f"{count}x {reward_item} Auguments"
    if reward_type in ("Leader", "Hero"):
        if not reward_item:
            return False, "No leader specified for this code"
        leaders = game.get("Leaders", [])
        if not any(l.get("ID") == reward_item for l in leaders):
            leaders.append({"ID": reward_item, "Skin": reward_item, "OwnedSkins": []})
            game["Leaders"] = leaders
        return True, f"Leader {reward_item}"
    return False, f"Unsupported reward type: {reward_type}"


# --- Admin mailbox gifts (Gift / Reward) ------------------------------------
# The client builds its mailbox from data/persist/Blueprints/db_NewsMail.json,
# NOT from the save's "Mails" array. An entry may carry a "PlayerID"; the client
# only applies entries whose PlayerID matches the player (empty = everyone).
# The client's MailItem only understands a subset of rewards (currencies, XP
# materials and creatures). Other item types cannot travel through the post
# office and are granted directly to the save instead.
NEWS_MAIL_PATH = os.path.join(ROOT_DIR, "data/persist/Blueprints/db_NewsMail.json")

NEWS_MAIL_LOCK = threading.Lock()

# Composer reward type -> client GiftType (db_NewsMail "GiftType").
GIFT_MAIL_TYPES = {
    "SoftCurrency": "SoftCurrency",
    "HardCurrency": "HardCurrency",
    "FreeHardCurrency": "HardCurrency",
    "PvpCurrency": "PvPCurrency",
    "Creature": "Creature",
    "XPMaterials": "XPMaterials",
}

# Reward types the post office cannot carry; granted straight to the save.
GIFT_DIRECT_TYPES = ("EvolutionShards", "ActionCard", "Leader")

# Mail types that need a GiftID.
GIFT_MAIL_ITEM_TYPES = ("Creature", "XPMaterials")

GIFT_REWARD_TYPES = tuple(GIFT_MAIL_TYPES) + GIFT_DIRECT_TYPES


def LoadNewsMail():
    """Return the db_NewsMail.json list (empty on failure)."""
    try:
        with open(NEWS_MAIL_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (OSError, ValueError) as e:
        Log("admin", f"Failed to load db_NewsMail.json: {e}")
    return []


def _NextAdminMailId(mails):
    # Timestamp-based so IDs are never reused after a delivered entry is pruned
    # (the client dedupes mails by ID, so a reused ID would hide a new gift).
    used = {
        str(m.get("ID", ""))
        for m in mails
        if isinstance(m, dict)
    }
    base = f"ADMIN_{int(_time.time())}"
    seq = 1
    while f"{base}_{seq}" in used:
        seq += 1
    return f"{base}_{seq}"


def AddNewsMailGift(player_id, gift_type, gift_id, amount, title, body, show_date=None):
    """Append a per-player gift entry to db_NewsMail.json.

    The client generates a mailbox item for it and grants the reward on claim.
    Returns ``(True, mail_id)`` or ``(False, error_message)``.
    """
    gift_type = (gift_type or "").strip()
    gift_id = (gift_id or "").strip()
    client_type = GIFT_MAIL_TYPES.get(gift_type)
    if client_type is None:
        return False, (
            f"{gift_type or 'This reward type'} cannot be delivered "
            "through the post office"
        )

    try:
        amount = int(amount)
    except (TypeError, ValueError):
        amount = 0

    if client_type in GIFT_MAIL_ITEM_TYPES:
        if not gift_id:
            return False, "An item ID is required for this gift type"
        amount = max(1, amount)
    elif amount < 1:
        return False, "Amount must be at least 1"

    if not player_id:
        return False, "A player ID is required"

    if show_date is None:
        show_date = datetime.now().strftime("%d/%m/%Y")

    entry = {
        "ID": "",
        "Name": (title or "A Gift For You").strip(),
        "BodyText": (
            body or "You have received a gift. Tap to claim your reward!"
        ).strip(),
        "GiftType": client_type,
        "Quantity": str(amount),
        "showDate": show_date,
        "PlayerID": player_id,
    }
    if client_type in GIFT_MAIL_ITEM_TYPES:
        entry["GiftID"] = gift_id

    with NEWS_MAIL_LOCK:
        mails = LoadNewsMail()
        entry["ID"] = _NextAdminMailId(mails)
        mails.append(entry)
        try:
            with open(NEWS_MAIL_PATH, "w", encoding="utf-8") as f:
                json.dump(mails, f, ensure_ascii=False, separators=(",", ":"))
        except OSError as e:
            return False, f"Could not write the mail blueprint: {e}"

    return True, entry["ID"]


def AddNewsMailNotice(player_id, title, body, show_date=None):
    """Append a reward-less announcement mail (used for direct-granted items)."""
    if show_date is None:
        show_date = datetime.now().strftime("%d/%m/%Y")
    entry = {
        "ID": "",
        "Name": (title or "A Gift For You").strip(),
        "BodyText": (body or "An admin gift has been added to your account.").strip(),
        "GiftType": "",
        "Quantity": "0",
        "showDate": show_date,
        "PlayerID": player_id,
    }
    with NEWS_MAIL_LOCK:
        mails = LoadNewsMail()
        entry["ID"] = _NextAdminMailId(mails)
        mails.append(entry)
        try:
            with open(NEWS_MAIL_PATH, "w", encoding="utf-8") as f:
                json.dump(mails, f, ensure_ascii=False, separators=(",", ":"))
        except OSError as e:
            return False, f"Could not write the mail blueprint: {e}"
    return True, entry["ID"]


def StripLegacyAdminMails(game):
    """Remove mails written by the old direct-to-save gift format.

    The old format is the only one that stores a ``GiftType`` key in the save;
    the client's own mails never do, so this keeps genuine mailbox items.
    """
    mails = game.get("Mails")
    if isinstance(mails, list):
        game["Mails"] = [
            m
            for m in mails
            if not (isinstance(m, dict) and "GiftType" in m)
        ]


def PruneDeliveredNewsMail(game):
    """Delete db_NewsMail gift entries once they have reached the player's save.

    The client only creates a mail once and keeps it in the save (or marks its
    ID in ``DeletedMail``), so as soon as an ``ADMIN_*`` entry is referenced by
    the save the blueprint copy can go. This stops a claimed gift from being
    re-created (and re-claimed) on the next login.
    """
    if not isinstance(game, dict):
        return

    delivered = set()
    mails = game.get("Mails")
    if isinstance(mails, list):
        for m in mails:
            if isinstance(m, dict):
                mid = m.get("ID")
                if isinstance(mid, str) and mid.startswith("ADMIN_"):
                    delivered.add(mid)
    deleted = game.get("DeletedMail")
    if isinstance(deleted, list):
        for d in deleted:
            if isinstance(d, str) and d.startswith("ADMIN_"):
                delivered.add(d)
    if not delivered:
        return

    with NEWS_MAIL_LOCK:
        mails = LoadNewsMail()
        remaining = [
            m
            for m in mails
            if not (isinstance(m, dict) and m.get("ID") in delivered)
        ]
        if len(remaining) != len(mails):
            try:
                with open(NEWS_MAIL_PATH, "w", encoding="utf-8") as f:
                    json.dump(remaining, f, ensure_ascii=False, separators=(",", ":"))
            except OSError as e:
                Log("admin", f"Failed to prune db_NewsMail.json: {e}")


def GetGiftCatalog():
    """Return the item choices for the admin Gift / Reward composer."""
    catalog = {"creatures": [], "cards": [], "leaders": [], "xpmaterials": []}

    for cid, name in GetCreatureNameMap().items():
        if not cid or IsTutorialOnlyCreature(cid):
            continue
        catalog["creatures"].append({"id": cid, "name": name or cid})

    for cid, name in GetActionCardNameMap().items():
        if cid:
            catalog["cards"].append({"id": cid, "name": name or cid})

    for lid, name in GetLeaderNameMap().items():
        if lid:
            catalog["leaders"].append({"id": lid, "name": name or lid})

    try:
        with open(
            os.path.join(ROOT_DIR, "data/persist/Blueprints/db_XPMaterials.json"), "r"
        ) as f:
            for material in json.load(f):
                mid = material.get("ID")
                if mid:
                    catalog["xpmaterials"].append(
                        {
                            "id": mid,
                            "name": FormatBlueprintName(material.get("Name", mid)),
                        }
                    )
    except Exception as e:
        Log("admin", f"Failed to load db_XPMaterials.json: {e}")

    for key in catalog:
        catalog[key].sort(key=lambda item: item["name"].lower())
    return catalog


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
    # AdminLeaderLevel / AdminPlayerLevel are admin-set overrides: a save
    # without them is normal, so the detector no longer flags them as issues.
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

# Valid inventory item discriminators: creature, Auguments, XP material and
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
                    "Inventory item #"
                    + str(index)
                    + " has an invalid or missing type (_T)."
                )
            if not item.get("ID"):
                issues.append("Inventory item #" + str(index) + " is missing its ID.")
            if item_type == "CR":
                if "UniqueID" not in item:
                    issues.append(
                        "Creature '"
                        + str(item.get("ID"))
                        + "' is missing its UniqueID."
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
                            "Creature '"
                            + str(item.get("ID"))
                            + "' is missing "
                            + field
                            + "."
                        )
            elif item_type == "CA":
                if "UniqueID" not in item:
                    issues.append(
                        "Auguments '"
                        + str(item.get("ID"))
                        + "' is missing its UniqueID."
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
                issues.append(
                    "Leader '" + str(leader_id) + "' has an invalid OwnedSkins value."
                )
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
            elif item.get("ID", "").startswith("AWK_MAT_") or item.get(
                "ID", ""
            ).startswith("EVMAT_"):
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
                repairs.append(
                    "Added missing Xp for creature '" + str(item.get("ID")) + "'."
                )
            if "StarRating" not in item:
                item["StarRating"] = 1
                repairs.append(
                    "Added missing StarRating for creature '"
                    + str(item.get("ID"))
                    + "'."
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
        target_name or target_game.get("MultiplayerPlayerName") or target_username
    )

    new_game, _ = RepairGameData(
        new_game,
        username=target_username,
        fallback_name=new_game["MultiplayerPlayerName"],
    )
    return new_game


# Team (loadout) lines. The client ships with StartingLoadoutCount = 5 rows on
# the deck screen; the save simply stores one entry per row in game["Loadouts"].
DEFAULT_LOADOUT_COUNT = 5
MAX_LOADOUTS = 50

# Creatures inside a single team: `CreaturesOnTeam` in db_MiscParams.json (5 in
# the shipped blueprint) plus one `CreatureID<n>` slot per creature in each
# loadout entry.
DEFAULT_TEAM_CREATURES = 5
MAX_TEAM_CREATURES = 10


def DefaultLoadoutLeader(game):
    """Leader a brand new blank team line should use."""
    loadouts = game.get("Loadouts")
    if isinstance(loadouts, list):
        for loadout in loadouts:
            if isinstance(loadout, dict) and loadout.get("LeaderID"):
                return loadout["LeaderID"]

    leaders = game.get("Leaders")
    if isinstance(leaders, list):
        for leader in leaders:
            if isinstance(leader, dict) and leader.get("ID"):
                return leader.get("Skin") or leader.get("ID")

    # Last resort: the blueprint hero every new account is given
    fallback = ReadMiscParam("TutorialBuyHero")
    if isinstance(fallback, str) and fallback:
        return fallback

    return ""


def LoadoutCreatureCount(loadout):
    """How many `CreatureID<n>` slots a team dict currently exposes."""
    if not isinstance(loadout, dict):
        return 0
    highest = -1
    for key in loadout:
        if not key.startswith("CreatureID"):
            continue
        suffix = key[len("CreatureID") :]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return highest + 1


def SetTeamCreatureCount(game, count):
    """Resize every team's `CreatureID<n>` slots to `count`.

    Growing pads with empty (`0`) slots, shrinking drops the extra ones.
    Returns the clamped count actually applied.
    """
    if not isinstance(game, dict):
        return 0

    try:
        count = int(count)
    except (TypeError, ValueError):
        count = DEFAULT_TEAM_CREATURES

    count = max(1, min(MAX_TEAM_CREATURES, count))

    loadouts = game.get("Loadouts")
    if not isinstance(loadouts, list):
        return count

    for loadout in loadouts:
        if not isinstance(loadout, dict):
            continue
        for index in range(count):
            loadout.setdefault("CreatureID" + str(index), 0)
        for key in [
            key
            for key in list(loadout)
            if key.startswith("CreatureID")
            and key[len("CreatureID") :].isdigit()
            and int(key[len("CreatureID") :]) >= count
        ]:
            del loadout[key]

    return count


def SetLoadoutCount(game, count):
    """Resize game["Loadouts"] to `count` team lines.

    Existing teams are kept when growing; new lines are blank (leader only,
    padded with empty creature slots matching the save's existing teams).
    Returns the clamped count actually applied.
    """
    if not isinstance(game, dict):
        return 0

    try:
        count = int(count)
    except (TypeError, ValueError):
        count = DEFAULT_LOADOUT_COUNT

    count = max(1, min(MAX_LOADOUTS, count))

    loadouts = game.get("Loadouts")
    if not isinstance(loadouts, list):
        loadouts = []
    loadouts = [lo if isinstance(lo, dict) else {"LeaderID": ""} for lo in loadouts]

    # New teams should look like the ones already in this save.
    slot_count = max((LoadoutCreatureCount(lo) for lo in loadouts), default=0)

    leader = DefaultLoadoutLeader(game)
    while len(loadouts) < count:
        new_team = {"LeaderID": leader}
        for index in range(slot_count):
            new_team["CreatureID" + str(index)] = 0
        loadouts.append(new_team)
    if len(loadouts) > count:
        loadouts = loadouts[:count]

    game["Loadouts"] = loadouts

    try:
        selected = int(game.get("SelectedLoadout", 0) or 0)
    except (TypeError, ValueError):
        selected = 0
    if selected < 0 or selected >= count:
        game["SelectedLoadout"] = 0

    return count


MISC_PARAMS_PATH = os.path.join(
    ROOT_DIR, "data", "persist", "Blueprints", "db_MiscParams.json"
)
