import json
import os
import random
import re
import secrets
import shutil
import string
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime, timezone

from flask import (
    Blueprint,
    Response,
    abort,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
)
from flask_login import current_user, login_required, login_user, logout_user

from app import app as flask_app
from app import badcharaters, bcrypt, db, maintenance
from app.models import Admin, AdminActivity, Bans, Logs, Player, RedeemCode, UpsightLogs
from app.utils import (
    DATABASE_DUMP_NAME,
    DEFAULT_LOADOUT_COUNT,
    DEFAULT_TEAM_CREATURES,
    MAX_LOADOUTS,
    MAX_TEAM_CREATURES,
    SQLITE_DUMP_NAME,
    Backup,
    BuildTransferredGame,
    DecryptGameData,
    DescribeBattleRecord,
    DiscordWebhookMessage,
    EncryptGameData,
    FindBrokenSaveIssues,
    FormatActionCardName,
    FormatActionCardType,
    FormatBanExpiry,
    FormatBlueprintName,
    FormatCreatureName,
    FormatLeaderName,
    GetActionCardNameMap,
    GetBackupIntervalHours,
    GetBanExpiry,
    GetCreatureNameMap,
    GetLeaderNameMap,
    GetLeaderSkinBase,
    GetLeaderSkins,
    GetNameFromSave,
    GetPlayerWins,
    GetPvpBanlist,
    GetPvpRankName,
    GetRankForXP,
    GetRankXPTable,
    GetTutorialOnlyCreatureIds,
    GetXPForRank,
    InvalidUsername,
    IPFromRequest,
    IsPostgres,
    IsTutorialOnlyCreature,
    IsUserBanned,
    LoadoutCreatureCount,
    LoadSettings,
    Log,
    MigrateSqliteDatabase,
    PlayerLog,
    ReadMiscParam,
    ReadPersistText,
    RepairGameData,
    RestoreDatabaseSql,
    SafeLoginNext,
    SavePvpBanlist,
    SaveSettings,
    SendBackupToTelegram,
    SetLoadoutCount,
    SetTeamCreatureCount,
    UpdateLastOnline,
    WriteMiscParam,
    isAdmin,
    safe_int,
    time_ago_string,
)

admin_bp = Blueprint("admin_bp", __name__)

ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
