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
    "https://live.54-39-230-220.sslip.io/admin/api/player/"
    "4211c5b4-2a23-4720-9f54-5dd208d3a3d8/save"
)

INPUT_FILE = "instance/veterans_decoded/yousseif1234.json"  # <-- your local json file

COOKIES = {
    "remember_token": (
        "Usif|762d77b77dab0812fc2cbc7994bb3f71de8e443048dda48bb5f513a504051ac8ab9bfee6e87d79b5eddf2fbcb3dc5b4089c0d5f1e2759d180639462a963889c4"
    ),
    "session": ".eJztUctqAzEQ-xUz56X4veP9il56CiGMPTPZhW1T4s0p5N9r6C_0WBAIIQkEesJFd-qrdFhOTzDHIPiU3ukqMMH7LtTF7Ler2b7McTPU2jDNsW7dfI_MG5xf03_vT3vnaZxyl77CorR3GXJjWMCxrZZi5CRVmw2ss0fXGG0W3zQ0yja3NsBFq_pAVq3MMbZYvQ84oyVXsNbilEJyhUvzEkNxhJJ9zowlh6TWlYCFs86pzkSYYhRmxLH_8uhy_13z0TeF1w9iCrfT.asUzsA.9jxJqBbyIHTrNJ5uKnjKsnMBKos",
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
        timeout=60,
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
