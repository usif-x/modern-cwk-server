import os

from app import app, args
from app.utils import Log

if __name__ == "__main__":
    Log("server", "Starting server...")

    if not os.path.exists("data/persist/version.txt"):
        with open("data/persist/version.txt", "w") as f:
            f.write("1.0.0")
    if not os.path.exists("data/persist/android_version.txt"):
        with open("data/persist/android_version.txt", "w") as f:
            f.write("1.0.0")

    app.run(debug=args.debug, port=args.port)
