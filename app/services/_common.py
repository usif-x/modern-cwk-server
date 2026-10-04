import base64
import bisect
import copy
import gzip
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import threading
import time as _time
from datetime import datetime, timezone
from io import BytesIO

import discord_webhook
from flask import Request

from app import badcharaters, db
from app.models import Admin, AdminActivity, Bans, Player

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Names of the database file stored inside a backup archive.
DATABASE_DUMP_NAME = "cardwarskingdom.sql"
SQLITE_DUMP_NAME = "cardwarskingdom.db"
