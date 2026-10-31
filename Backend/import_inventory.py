import csv
import hashlib
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from Backend.database import PROJECT_DIR, SessionLocal, initialize_database
from Backend.models import InventoryItem
from Backend.services.inventory_service import inventory_status_for

BATCHES_PATH = PROJECT_DIR / "ml" / "data" / "raw" / "inventory_batches.csv"
PRODUCTS_PATH = PROJECT_DIR / "ml" / "data" / "raw" / "products.csv"


def _read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"Required CSV file was not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"{path.name} is missing required columns: {', '.join(sorted(missing))}"
            )
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path.name} contains no data rows.")
    return rows


def import_inventory_csv(
    db: Session, batches_path: Path = BATCHES_PATH, products_path: Path = PRODUCTS_PATH
) -> tuple[int, int]:
    products = _read_csv(products_path, {"product_id", "product_name"})
    product_names: dict[int, str] = {}
    for row_number, row in enumerate(products, start=2):
        try:
            product_id = int(row["product_id"])
            product_name = row["product_name"].strip()
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid product row {row_number} in {products_path.name}."
            ) from exc
        if not product_name:
            raise ValueError(
                f"Product name is blank on row {row_number} in {products_path.name}."
            )
        if product_id in product_names:
            raise ValueError(
                f"Duplicate product ID {product_id} in {products_path.name}."
            )
        product_names[product_id] = product_name

    rows = _read_csv(
        batches_path,
        {
            "batch_id",
            "product_id",
            "category",
            "received_at",
            "snapshot_date",
            "expiry_date",
            "quantity_remaining",
            "unit_price",
        },
    )
    existing_keys = set(
        db.scalars(
            select(InventoryItem.source_key).where(
                InventoryItem.source_key.is_not(None)
            )
        )
    )
    imported = 0
    skipped = 0
    today = date.today()
    duplicate_occurrences: dict[str, int] = {}

    for row_number, row in enumerate(rows, start=2):
        serialized_row = json.dumps(row, sort_keys=True, separators=(",", ":"))
        row_hash = hashlib.sha256(serialized_row.encode("utf-8")).hexdigest()
        occurrence = duplicate_occurrences.get(row_hash, 0)
        duplicate_occurrences[row_hash] = occurrence + 1
        source_key = f"{batches_path.name}:{row_hash}:{occurrence}"
        if source_key in existing_keys:
            skipped += 1
            continue
        try:
            product_id = int(row["product_id"])
            product_name = product_names[product_id]
            stock_date = date.fromisoformat(row["received_at"])
            snapshot_date = date.fromisoformat(row["snapshot_date"])
            expiry_date = date.fromisoformat(row["expiry_date"])
            quantity_value = float(row["quantity_remaining"])
            price = float(row["unit_price"])
            batch_id = int(row["batch_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid inventory data on row {row_number} in {batches_path.name}."
            ) from exc
        if not math.isfinite(quantity_value) or not quantity_value.is_integer():
            raise ValueError(
                f"Invalid quantity on row {row_number} in {batches_path.name}."
            )
        quantity = int(quantity_value)
        if (
            not row["category"].strip()
            or quantity < 0
            or not math.isfinite(price)
            or price < 0
            or expiry_date < stock_date
        ):
            raise ValueError(
                f"Invalid inventory values on row {row_number} in {batches_path.name}."
            )

        item = InventoryItem(
            product_name=product_name,
            category=row["category"].strip(),
            quantity=quantity,
            price=price,
            stock_date=stock_date,
            expiry_date=expiry_date,
            estimated_daily_demand=None,
            inventory_status="in_stock",
            source_type="csv_snapshot",
            source_key=source_key,
            source_batch_id=batch_id,
            source_product_id=product_id,
            snapshot_date=snapshot_date,
            source_data=dict(row),
        )
        item.inventory_status = inventory_status_for(item, today)
        db.add(item)
        existing_keys.add(source_key)
        imported += 1

    return imported, skipped


def main() -> None:
    initialize_database()
    with SessionLocal() as db:
        with db.begin():
            imported, skipped = import_inventory_csv(db)
    print(
        "CSV inventory import complete: "
        f"{imported} imported, {skipped} already present, "
        f"{imported + skipped} source rows accounted for."
    )


if __name__ == "__main__":
    main()
