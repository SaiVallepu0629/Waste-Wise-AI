from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine, inspect, text

OWNER_MIGRATION = "0001_inventory_owner"
LOGIN_RATE_LIMIT_MIGRATION = "0002_login_rate_limits"


def _backup_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "WasteWise" / "database-backups"


def _backup_sqlite_database(engine: Engine, backup_directory: Path | None) -> Path:
    database_path = engine.url.database
    if not database_path or database_path == ":memory:" or database_path.startswith("file:"):
        raise RuntimeError(
            "The existing SQLite database needs an additive migration, but a "
            "persistent database file could not be identified for backup."
        )

    source_path = Path(database_path).resolve()
    target_directory = backup_directory or _backup_directory()
    target_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = target_directory / (
        f"inventory-before-owner-migration-{timestamp}-{uuid4().hex[:8]}.sqlite3"
    )

    source = sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True)
    try:
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
            integrity = destination.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise RuntimeError(
                    "The pre-migration SQLite backup failed integrity_check."
                )
        finally:
            destination.close()
    except Exception:
        source.close()
        backup_path.unlink(missing_ok=True)
        raise
    else:
        source.close()
    return backup_path


def apply_migrations(
    engine: Engine, backup_directory: Path | None = None
) -> Path | None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    inventory_exists = "inventory_items" in tables
    owner_column_exists = (
        inventory_exists
        and "owner_id"
        in {column["name"] for column in inspector.get_columns("inventory_items")}
    )
    backup_path = None
    if inventory_exists and not owner_column_exists:
        backup_path = _backup_sqlite_database(engine, backup_directory)

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version VARCHAR(64) PRIMARY KEY NOT NULL, "
                "applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        current_columns = {
            column["name"]
            for column in inspect(connection).get_columns("inventory_items")
        }
        if "owner_id" not in current_columns:
            connection.execute(
                text(
                    "ALTER TABLE inventory_items ADD COLUMN owner_id INTEGER "
                    "REFERENCES users(id)"
                )
            )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_inventory_items_owner_id "
                "ON inventory_items (owner_id)"
            )
        )
        connection.execute(
            text(
                "INSERT OR IGNORE INTO schema_migrations (version) "
                "VALUES (:version)"
            ),
            {"version": OWNER_MIGRATION},
        )
        connection.execute(
            text(
                "INSERT OR IGNORE INTO schema_migrations (version) "
                "VALUES (:version)"
            ),
            {"version": LOGIN_RATE_LIMIT_MIGRATION},
        )
    return backup_path
