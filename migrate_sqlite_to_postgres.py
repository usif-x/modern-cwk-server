#!/usr/bin/env python3
"""Migrate the legacy SQLite database into the active database (PostgreSQL).

The source is the old single-file database at `instance/cardwarskingdom.db`;
the target is whatever `DATABASE_URL` points at.

    python migrate_sqlite_to_postgres.py
    python migrate_sqlite_to_postgres.py --sqlite /path/to/old.db
    python migrate_sqlite_to_postgres.py --dry-run
"""

import argparse
import os
import sys

from app import app, db
from app import models  # noqa: F401  - registers db.metadata
from app.utils import IsPostgres, MigrateSqliteDatabase, ROOT_DIR

DEFAULT_SQLITE = os.path.join(ROOT_DIR, "instance", "cardwarskingdom.db")


def CountSourceRows(sqlite_path):
    from sqlalchemy import MetaData, Table, create_engine, func, inspect, select

    engine = create_engine(f"sqlite:///{sqlite_path}")
    inspector = inspect(engine)
    counts = {}
    with engine.connect() as conn:
        for name in inspector.get_table_names():
            if name.startswith("sqlite_"):
                continue
            table = Table(name, MetaData(), autoload_with=engine)
            counts[name] = conn.execute(select(func.count()).select_from(table)).scalar()
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", default=DEFAULT_SQLITE, help="source SQLite file")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="append instead of replacing rows already in the target",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list the source row counts without touching the target",
    )
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args()

    if not os.path.exists(args.sqlite):
        print(f"Source database not found: {args.sqlite}")
        return 1

    with app.app_context():
        target = db.engine.url.render_as_string(hide_password=True)
        backend = "PostgreSQL" if IsPostgres() else "SQLite"
        print(f"Source : {args.sqlite}")
        print(f"Target : {target} ({backend})")

        if args.dry_run:
            counts = CountSourceRows(args.sqlite)
            for table, count in sorted(counts.items()):
                print(f"  {table:<24} {count:>8}")
            print(f"Source rows: {sum(counts.values())}")
            return 0

        if not args.keep:
            from sqlalchemy import func, select

            existing = sum(
                db.session.execute(
                    select(func.count()).select_from(table)
                ).scalar()
                or 0
                for table in db.metadata.tables.values()
            )
            if existing and not args.yes:
                if not sys.stdin.isatty():
                    print(
                        "Target database already has data. Re-run with --yes to "
                        "replace it."
                    )
                    return 1
                answer = input(
                    "This replaces every row in the target database. Continue? [y/N] "
                )
                if answer.strip().lower() not in ("y", "yes"):
                    print("Aborted.")
                    return 1

        try:
            counts = MigrateSqliteDatabase(args.sqlite, replace=not args.keep)
        except Exception as e:
            print(f"Migration failed: {e}")
            return 1

        total = 0
        for table, count in sorted(counts.items()):
            print(f"  {table:<24} {count:>8}")
            total += count
        print(f"Migrated rows: {total}")
        db.session.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
