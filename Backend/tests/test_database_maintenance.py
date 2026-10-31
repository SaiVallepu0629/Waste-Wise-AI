import sqlite3
import tempfile
import unittest
from pathlib import Path

from Backend.database_maintenance import create_backup, restore_to_new_file


class DatabaseMaintenanceTests(unittest.TestCase):
    def test_backup_and_restore_preserve_rows_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "inventory.sqlite3"
            connection = sqlite3.connect(source_path)
            connection.execute(
                "CREATE TABLE inventory_items (id INTEGER PRIMARY KEY, name TEXT)"
            )
            connection.execute(
                "INSERT INTO inventory_items (id, name) VALUES (1, 'Preserved item')"
            )
            connection.commit()
            connection.close()

            backup_path = create_backup(source_path, root / "backups")
            restored_path = root / "restored.sqlite3"
            self.assertEqual(
                restore_to_new_file(backup_path, restored_path), restored_path
            )

            restored = sqlite3.connect(restored_path)
            try:
                self.assertEqual(
                    restored.execute(
                        "SELECT id, name FROM inventory_items"
                    ).fetchall(),
                    [(1, "Preserved item")],
                )
                self.assertEqual(
                    restored.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )
            finally:
                restored.close()

            with self.assertRaises(FileExistsError):
                restore_to_new_file(backup_path, restored_path)
