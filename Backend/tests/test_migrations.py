import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text

from Backend.database import Base
from Backend.migrations import (
    LOGIN_RATE_LIMIT_MIGRATION,
    OWNER_MIGRATION,
    apply_migrations,
)


class DatabaseMigrationTests(unittest.TestCase):
    def test_owner_migration_preserves_existing_rows_and_creates_verified_backup(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "legacy.sqlite3"
            backup_directory = root / "backups"
            connection = sqlite3.connect(database_path)
            connection.execute(
                "CREATE TABLE inventory_items ("
                "id INTEGER PRIMARY KEY, product_name TEXT NOT NULL, "
                "source_type TEXT NOT NULL, source_key TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO inventory_items "
                "(id, product_name, source_type, source_key) VALUES (?, ?, ?, ?)",
                [
                    (1, "Historical apple", "csv_snapshot", "batch:1"),
                    (2, "Historical milk", "csv_snapshot", "batch:2"),
                ],
            )
            connection.commit()
            original_rows = connection.execute(
                "SELECT id, product_name, source_type, source_key "
                "FROM inventory_items ORDER BY id"
            ).fetchall()
            connection.close()

            engine = create_engine(f"sqlite:///{database_path}")
            try:
                Base.metadata.create_all(engine)
                backup_path = apply_migrations(engine, backup_directory)

                with engine.connect() as migrated:
                    rows = migrated.execute(
                        text(
                            "SELECT id, product_name, source_type, source_key, owner_id "
                            "FROM inventory_items ORDER BY id"
                        )
                    ).fetchall()
                    versions = set(
                        migrated.execute(
                            text("SELECT version FROM schema_migrations")
                        ).scalars()
                    )

                self.assertEqual(
                    [tuple(row[:4]) for row in rows], original_rows
                )
                self.assertTrue(all(row[4] is None for row in rows))
                self.assertEqual(
                    versions, {OWNER_MIGRATION, LOGIN_RATE_LIMIT_MIGRATION}
                )
                self.assertIsNotNone(backup_path)
                self.assertTrue(backup_path.is_file())
                backup = sqlite3.connect(backup_path)
                try:
                    self.assertEqual(
                        backup.execute(
                            "SELECT id, product_name, source_type, source_key "
                            "FROM inventory_items ORDER BY id"
                        ).fetchall(),
                        original_rows,
                    )
                    self.assertEqual(
                        backup.execute("PRAGMA integrity_check").fetchone()[0],
                        "ok",
                    )
                finally:
                    backup.close()

                self.assertIsNone(apply_migrations(engine, backup_directory))
            finally:
                engine.dispose()
