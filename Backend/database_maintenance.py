from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from Backend.database import engine


def _configured_database_path() -> Path:
    database_path = engine.url.database
    if not database_path or database_path == ":memory:" or database_path.startswith("file:"):
        raise RuntimeError("A persistent SQLite database file is required.")
    return Path(database_path).resolve()


def _default_backup_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "WasteWise" / "database-backups"


def _open_readonly(database_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True)


def _verify_database(connection: sqlite3.Connection) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if integrity is None or integrity[0] != "ok":
        raise RuntimeError("SQLite integrity_check failed.")
    foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise RuntimeError("SQLite foreign_key_check found invalid references.")


def create_backup(
    source_path: Path | None = None,
    output_directory: Path | None = None,
) -> Path:
    source_path = (source_path or _configured_database_path()).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Database file does not exist: {source_path}")

    backup_directory = output_directory or _default_backup_directory()
    backup_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_directory / (
        f"inventory-backup-{timestamp}-{uuid4().hex[:8]}.sqlite3"
    )
    with closing(_open_readonly(source_path)) as source:
        with backup_path.open("xb"):
            pass
        try:
            with closing(sqlite3.connect(backup_path)) as destination:
                source.backup(destination)
                _verify_database(destination)
        except Exception:
            backup_path.unlink(missing_ok=True)
            raise
    return backup_path


def restore_to_new_file(backup_path: Path, target_path: Path) -> Path:
    backup_path = backup_path.resolve()
    target_path = target_path.resolve()
    if not backup_path.is_file():
        raise FileNotFoundError(f"Backup file does not exist: {backup_path}")
    if backup_path == target_path:
        raise ValueError("The restore target must be different from the backup file.")
    if target_path.exists():
        raise FileExistsError(f"Restore target already exists: {target_path}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(_open_readonly(backup_path)) as source:
        _verify_database(source)
        with target_path.open("xb"):
            pass
        try:
            with closing(sqlite3.connect(target_path)) as destination:
                source.backup(destination)
                _verify_database(destination)
        except Exception:
            target_path.unlink(missing_ok=True)
            raise
    return target_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create or restore verified WasteWise SQLite database copies."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument(
        "--source",
        type=Path,
        default=_configured_database_path(),
        help="SQLite database to copy (defaults to WASTEWISE_DATABASE_URL).",
    )
    backup_parser.add_argument(
        "--output-directory",
        type=Path,
        default=_default_backup_directory(),
    )
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("backup", type=Path)
    restore_parser.add_argument(
        "--target",
        type=Path,
        required=True,
        help="New database path; existing files are never overwritten.",
    )
    arguments = parser.parse_args()

    if arguments.action == "backup":
        print(create_backup(arguments.source, arguments.output_directory))
    else:
        print(restore_to_new_file(arguments.backup, arguments.target))


if __name__ == "__main__":
    main()
