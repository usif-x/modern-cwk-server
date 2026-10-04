#!/usr/bin/env python3
"""
POST usif.json data to the CardWarsKingdom admin save endpoint.
The server expects {"json": "<stringified JSON>"} as the body.
"""

import json
import sys
from pathlib import Path

import requests

# ---------------- Configuration ----------------
URL = (
    "https://cardwarskingdom.pythonanywhere.com/admin/api/player/"
    "4211c5b4-2a23-4720-9f54-5dd208d3a3d8/save"
)

INPUT_FILE = "usif.json"  # <-- your local json file

COOKIES = {
    "remember_token": (
        "Usif|9c3c4f17b3bf539fbb5a70781fedb6a0f850ebdba7d399f745fbaaab98953ed3"
        "44a8549c7e78276f12f42c5007f82d1217bb587e10921cb027744aafe3d2db5c"
    ),
    "session": (
        ".eJwljs1qAzEMhF_F6ByKLa9_tE_RS08hBK0lZRe2TYk3p5B3r6GnYZiP4XvB1Xbuq3aY"
        "zy9wxwj41t75pnCCz125q9vvN7f9uOPuuLUxumPduvsdzAdc3pfTOHloX2E23ruOugnMo"
        "EiSYi4kgdQnNKw5V0-1VRHmWLAu5JspGttkXiWjpgkjsV8MI3rLXiwIVqomLesU1EeZoq"
        "XIUiiUiVNKlEurhKGGvGCwHCoppRKH__XZ9fFv89U3g_cf7RxHCQ.arUKbg.uSs_1Hp2u"
        "sp24g7D1wBdss306-g"
    ),
}

HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://cardwarskingdom.pythonanywhere.com",
    "Referer": "https://cardwarskingdom.pythonanywhere.com/neo-admin/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Google Chrome";v="153", "Not_A Brand";v="8", "Chromium";v="153"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}
# ------------------------------------------------


def load_payload(path: str) -> str:
    """Read usif.json and return it as a compact JSON string."""
    p = Path(path)
    if not p.is_file():
        sys.exit(f"[!] File not found: {p.resolve()}")

    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Compact stringified JSON (what the server expects inside "json")
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def main() -> None:
    payload_str = load_payload(INPUT_FILE)

    body = {"json": payload_str}

    print(f"[*] POST -> {URL}")
    print(f"[*] Payload size: {len(payload_str):,} bytes")

    resp = requests.post(
        URL,
        headers=HEADERS,
        cookies=COOKIES,
        json=body,
        timeout=30,
    )

    print(f"[*] Status : {resp.status_code}")
    print(f"[*] Response:\n{resp.text}")

    try:
        print("[*] Parsed :", resp.json())
    except ValueError:
        pass

    resp.raise_for_status()


if __name__ == "__main__":
    main()
