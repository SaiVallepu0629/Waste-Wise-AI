import csv
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

os.environ["WASTEWISE_DATABASE_URL"] = "sqlite://"
os.environ.setdefault(
    "WASTEWISE_JWT_SECRET",
    "test-only-secret-that-is-never-used-outside-tests-123456",
)

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from Backend.database import Base, get_db
from Backend.import_inventory import import_inventory_csv
from Backend.main import app
from Backend.models import InventoryItem
from Backend.services.inventory_service import recommendation_for


class InventoryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )

        def override_get_db():
            with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        registration = self.client.post(
            "/auth/register",
            json={"email": "inventory-tests@example.com", "password": "valid-test-passphrase"},
        )
        self.assertEqual(registration.status_code, 201)
        self.client.headers.update(
            {"Authorization": f"Bearer {registration.json()['access_token']}"}
        )

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_inventory_crud_and_validation(self) -> None:
        payload = {
            "product_name": "  Fresh apples ",
            "category": " Produce ",
            "quantity": 20,
            "price": 4.5,
            "stock_date": date.today().isoformat(),
            "expiry_date": (date.today() + timedelta(days=4)).isoformat(),
            "estimated_daily_demand": 3,
        }
        created = self.client.post("/inventory/items", json=payload)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["product_name"], "Fresh apples")
        item_id = created.json()["id"]

        listed = self.client.get("/inventory/items")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["total"], 1)

        payload["quantity"] = 8
        updated = self.client.put(f"/inventory/items/{item_id}", json=payload)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["quantity"], 8)

        invalid = dict(payload, expiry_date=(date.today() - timedelta(days=1)).isoformat())
        self.assertEqual(
            self.client.post("/inventory/items", json=invalid).status_code, 422
        )

        self.assertEqual(
            self.client.delete(f"/inventory/items/{item_id}").status_code, 204
        )
        self.assertEqual(self.client.get(f"/inventory/items/{item_id}").status_code, 404)

    def test_inventory_search_and_pagination(self) -> None:
        for product_name, category in (
            ("Fresh apples", "Produce"),
            ("Whole milk", "Dairy"),
            ("Oat milk", "Pantry"),
        ):
            response = self.client.post(
                "/inventory/items",
                json={
                    "product_name": product_name,
                    "category": category,
                    "quantity": 10,
                    "price": 2.5,
                    "stock_date": date.today().isoformat(),
                    "expiry_date": (date.today() + timedelta(days=5)).isoformat(),
                },
            )
            self.assertEqual(response.status_code, 201)

        first_page = self.client.get("/inventory/items?limit=2&offset=0").json()
        second_page = self.client.get("/inventory/items?limit=2&offset=2").json()
        milk_search = self.client.get(
            "/inventory/items?search=milk&limit=10"
        ).json()

        self.assertEqual(first_page["total"], 3)
        self.assertEqual(len(first_page["items"]), 2)
        self.assertEqual(len(second_page["items"]), 1)
        self.assertEqual(milk_search["total"], 2)
        self.assertEqual(
            {item["product_name"] for item in milk_search["items"]},
            {"Whole milk", "Oat milk"},
        )

    def test_rule_based_recommendation_requires_user_demand(self) -> None:
        response = self.client.post(
            "/inventory/items",
            json={
                "product_name": "Yogurt",
                "category": "Dairy",
                "quantity": 30,
                "price": 2.5,
                "stock_date": date.today().isoformat(),
                "expiry_date": (date.today() + timedelta(days=2)).isoformat(),
            },
        )
        recommendation = self.client.get("/inventory/recommendations")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(recommendation.status_code, 200)
        self.assertIsNone(recommendation.json()[0]["recommended_discount_pct"])
        self.assertIsNone(recommendation.json()[0]["quantity_at_risk"])
        self.assertIsNone(recommendation.json()[0]["likely_to_expire_unsold"])
        self.assertIn("Enter expected daily demand", recommendation.json()[0]["basis"])

    def test_rule_based_recommendation_estimates_surplus_and_discount_basis(self) -> None:
        response = self.client.post(
            "/inventory/items",
            json={
                "product_name": "Apples",
                "category": "Produce",
                "quantity": 30,
                "price": 2.5,
                "stock_date": date.today().isoformat(),
                "expiry_date": (date.today() + timedelta(days=2)).isoformat(),
                "estimated_daily_demand": 2,
            },
        )
        self.assertEqual(response.status_code, 201)
        item_id = response.json()["id"]

        recommendation = self.client.get("/inventory/recommendations").json()[0]

        self.assertEqual(recommendation["item_id"], item_id)
        self.assertEqual(recommendation["risk_level"], "High")
        self.assertEqual(recommendation["quantity_at_risk"], 26)
        self.assertTrue(recommendation["likely_to_expire_unsold"])
        self.assertEqual(recommendation["recommended_discount_pct"], 30)
        self.assertIn("not measured price elasticity", recommendation["basis"])

    def test_expiry_risk_api_labels_snapshot_estimates(self) -> None:
        response = self.client.get("/expiry-risk")
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertIn("not a trained model prediction", result["note"])

        batches = {row["batch_id"]: row for row in result["records"]}
        no_surplus = batches[5001]
        self.assertEqual(no_surplus["quantity_at_risk_estimate"], 0)
        self.assertFalse(no_surplus["likely_to_expire_unsold_estimate"])
        self.assertEqual(no_surplus["rule_based_risk_level_at_snapshot"], "Low")

        surplus = batches[5002]
        self.assertEqual(surplus["quantity_at_risk_estimate"], 86)
        self.assertTrue(surplus["likely_to_expire_unsold_estimate"])
        self.assertEqual(surplus["rule_based_risk_level_at_snapshot"], "High")

        expired = batches[5004]
        self.assertEqual(expired["quantity_at_risk_estimate"], 141)
        self.assertEqual(expired["rule_based_risk_level_at_snapshot"], "High")

    def test_existing_csv_rows_import_once_without_loss(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            batches = Path(directory) / "inventory_batches.csv"
            products = Path(directory) / "products.csv"
            with batches.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=[
                        "batch_id",
                        "product_id",
                        "category",
                        "received_at",
                        "snapshot_date",
                        "expiry_date",
                        "quantity_remaining",
                        "unit_price",
                        "extra_source_value",
                    ],
                )
                writer.writeheader()
                row = {
                    "batch_id": 1,
                    "product_id": 10,
                    "category": "Produce",
                    "received_at": "2026-01-01",
                    "snapshot_date": "2026-01-02",
                    "expiry_date": "2026-01-05",
                    "quantity_remaining": 12,
                    "unit_price": 3.25,
                    "extra_source_value": "preserved",
                }
                writer.writerow(row)
                writer.writerow(row)
            with products.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=["product_id", "product_name"]
                )
                writer.writeheader()
                writer.writerow({"product_id": 10, "product_name": "Tomato"})

            with self.session_factory() as session:
                first = import_inventory_csv(session, batches, products)
                session.commit()
                second = import_inventory_csv(session, batches, products)
                session.commit()
                total = session.scalar(
                    select(func.count()).select_from(InventoryItem)
                )
                records = list(session.scalars(select(InventoryItem)))

            self.assertEqual(first, (2, 0))
            self.assertEqual(second, (0, 2))
            self.assertEqual(total, 2)
            self.assertEqual(records[0].source_data["extra_source_value"], "preserved")
            self.assertEqual(records[0].source_type, "csv_snapshot")
            response = self.client.delete(f"/inventory/items/{records[0].id}")
            self.assertEqual(response.status_code, 409)

    def test_expired_item_is_never_given_a_discount(self) -> None:
        item = InventoryItem(
            id=1,
            product_name="Expired milk",
            category="Dairy",
            quantity=10,
            price=2,
            stock_date=date.today() - timedelta(days=10),
            expiry_date=date.today() - timedelta(days=1),
            estimated_daily_demand=2,
        )
        recommendation = recommendation_for(item)
        self.assertEqual(recommendation.rule_based_risk_score, 100)
        self.assertIsNone(recommendation.recommended_discount_pct)


if __name__ == "__main__":
    unittest.main()
