import hashlib
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REMOTE_URL = "https://cardwarskingdom.pythonanywhere.com/persist/static/Blueprints/"
LOCAL_DIR = Path("data/persist/Blueprints")


def fetch(url: str) -> bytes:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
        },
    )

    with urlopen(req, timeout=30) as response:
        return response.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sync():
    if not LOCAL_DIR.exists():
        print(f"Local directory does not exist:")
        print(f"  {LOCAL_DIR}")
        return

    local_files = sorted(
        file
        for file in LOCAL_DIR.iterdir()
        if file.is_file() and file.suffix.lower() == ".json"
    )

    print(f"Remote: {REMOTE_URL}")
    print(f"Local : {LOCAL_DIR.resolve()}")
    print()
    print(f"Found {len(local_files)} local JSON files.")
    print()

    updated = 0
    unchanged = 0
    missing = 0
    failed = 0

    for local_file in local_files:
        filename = local_file.name
        remote_file_url = REMOTE_URL + filename

        print(f"Checking {filename}...", end=" ")

        try:
            remote_data = fetch(remote_file_url)
            local_data = local_file.read_bytes()

            if sha256(local_data) == sha256(remote_data):
                print("UNCHANGED")
                unchanged += 1
                continue

            local_file.write_bytes(remote_data)

            print("UPDATED")
            updated += 1

        except HTTPError as e:
            if e.code == 404:
                print("NOT FOUND ON SERVER")
                missing += 1
            else:
                print(f"HTTP ERROR {e.code}")
                failed += 1

        except URLError as e:
            print(f"NETWORK ERROR: {e.reason}")
            failed += 1

        except Exception as e:
            print(f"ERROR: {e}")
            failed += 1

    print()
    print("=" * 50)
    print("Sync complete")
    print("=" * 50)
    print(f"Updated   : {updated}")
    print(f"Unchanged : {unchanged}")
    print(f"Not found : {missing}")
    print(f"Failed    : {failed}")
    print(f"Total     : {len(local_files)}")


if __name__ == "__main__":
    sync()
