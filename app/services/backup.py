import threading
import time as _time

from ._common import *
from .database import *
from .game_data import Log

_BACKUP_LOCK = threading.Lock()


def Backup():
    """Create `backup/<timestamp>.zip` (database dump + `data/persist`).

    Serialized with a lock: the scheduler thread and the admin button can fire
    at the same time, and two runs in the same second used to collide on the
    working directory.
    """
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    work_dir = os.path.join(ROOT_DIR, "backup", now)
    zip_path = work_dir + ".zip"

    with _BACKUP_LOCK:
        try:
            if os.path.isdir(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)
            os.makedirs(work_dir, exist_ok=True)

            dumped = DumpDatabase(work_dir)

            shutil.copytree(
                os.path.join(ROOT_DIR, "data/persist"),
                os.path.join(work_dir, "persist"),
            )
            shutil.make_archive(work_dir, "zip", work_dir)
            Log("admin", f"Backed up (database: {dumped or 'SKIPPED'})")
            return zip_path
        except Exception as e:
            message = f"Backup failed: {e}"
            Log("admin", message)
            print(message.splitlines()[0], flush=True)
            return None
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


# --- Settings -------------------------------------------------------------
SETTINGS_PATH = os.path.join(ROOT_DIR, "data/persist/settings.json")

DEFAULT_SETTINGS = {
    "backup_interval_hours": 4,
    "backup_to_telegram": True,
    "last_backup": 0,
}


def LoadSettings():
    settings = dict(DEFAULT_SETTINGS)
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                settings.update(stored)
        except Exception as e:
            Log("admin", f"Failed to read settings.json: {e}")
    return settings


def SaveSettings(settings):
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    return settings


def GetSetting(key, default=None):
    value = LoadSettings().get(key, default)
    return value


def SetSetting(key, value):
    settings = LoadSettings()
    settings[key] = value
    SaveSettings(settings)
    return value


def GetBackupIntervalHours():
    from app.config import EnvBackupIntervalHours

    settings = LoadSettings()
    hours = settings.get("backup_interval_hours")
    if hours is None:
        hours = EnvBackupIntervalHours()
    try:
        return float(hours)
    except (ValueError, TypeError):
        return 4.0


# --- Telegram -------------------------------------------------------------
def SendTelegramMessage(text):
    from app.config import TelegramAdminId, TelegramBotToken

    token = TelegramBotToken()
    chat_id = TelegramAdminId()
    if not token or not chat_id:
        return False
    try:
        import requests

        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text},
            timeout=30,
        )
        return resp.ok
    except Exception as e:
        Log("admin", f"Failed to send Telegram message: {e}")
        return False


def SendTelegramDocument(file_path, caption=""):
    from app.config import TelegramAdminId, TelegramBotToken

    token = TelegramBotToken()
    chat_id = TelegramAdminId()
    if not token or not chat_id:
        return False
    if not file_path or not os.path.exists(file_path):
        return False
    try:
        import requests

        with open(file_path, "rb") as f:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendDocument",
                data={"chat_id": chat_id, "caption": caption},
                files={"document": (os.path.basename(file_path), f)},
                timeout=300,
            )
        if not resp.ok:
            Log(
                "admin",
                f"Telegram sendDocument failed: {resp.status_code} {resp.text[:200]}",
            )
        return resp.ok
    except Exception as e:
        Log("admin", f"Failed to send Telegram document: {e}")
        return False


def SendBackupToTelegram(zip_path=None):
    if zip_path is None:
        zip_path = LatestBackupPath()
    if not zip_path:
        return False
    caption = "CWK backup - " + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return SendTelegramDocument(zip_path, caption=caption)


def LatestBackupPath():
    backup_dir = os.path.join(ROOT_DIR, "backup")
    if not os.path.isdir(backup_dir):
        return None
    latest = None
    latest_time = -1
    for name in os.listdir(backup_dir):
        if not name.endswith(".zip"):
            continue
        path = os.path.join(backup_dir, name)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime > latest_time:
            latest_time = mtime
            latest = path
    return latest


def RunScheduledBackup():
    """Trigger a backup when the configured interval has elapsed."""
    interval_hours = GetBackupIntervalHours()
    if interval_hours <= 0:
        return False

    settings = LoadSettings()
    last_backup = float(settings.get("last_backup") or 0)
    if _time.time() - last_backup < interval_hours * 3600:
        return False

    zip_path = Backup()
    if not zip_path:
        # Nothing was produced (concurrent run or dump failure) - retry later
        # without pushing the next attempt further into the future.
        return False
    settings["last_backup"] = int(_time.time())
    SaveSettings(settings)

    if settings.get("backup_to_telegram", True):
        SendBackupToTelegram(zip_path)
    return True
