import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


def GetEnv(key, default=""):
    value = os.getenv(key, default)
    if value is None:
        return default
    return value.strip()


def TelegramBotToken():
    return GetEnv("TELEGRAM_BOT_TOKEN")


def TelegramAdminId():
    return GetEnv("TELEGRAM_ADMIN_ID")


def EnvBackupIntervalHours():
    try:
        return float(GetEnv("BACKUP_INTERVAL_HOURS", "4"))
    except (ValueError, TypeError):
        return 4.0


def TelegramConfigured():
    return bool(TelegramBotToken() and TelegramAdminId())
