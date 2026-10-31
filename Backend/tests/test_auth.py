import os
import unittest
from datetime import date, timedelta, timezone, datetime

os.environ["WASTEWISE_DATABASE_URL"] = "sqlite://"
os.environ.setdefault(
    "WASTEWISE_JWT_SECRET",
    "test-only-secret-that-is-never-used-outside-tests-123456",
)

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from Backend.database import Base, get_db
from Backend.main import app
from Backend.models import User
from Backend.security import validate_auth_configuration

TEST_SECRET = os.environ["WASTEWISE_JWT_SECRET"]


class AuthenticationApiTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def register(self, email: str, password: str = "correct-horse-battery") -> dict:
        response = self.client.post(
            "/auth/register", json={"email": email, "password": password}
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    @staticmethod
    def auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_registration_login_and_profile(self) -> None:
        registered = self.register("Owner@Example.com")
        self.assertIn("access_token", registered)
        self.assertEqual(registered["token_type"], "bearer")

        profile = self.client.get(
            "/auth/me", headers=self.auth(registered["access_token"])
        )
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json()["email"], "owner@example.com")
        with self.session_factory() as session:
            user = session.scalar(select(User).where(User.email == "owner@example.com"))
            self.assertIsNotNone(user)
            self.assertNotEqual(user.password_hash, "correct-horse-battery")
            self.assertTrue(user.password_hash.startswith("$argon2id$"))

        login = self.client.post(
            "/auth/login",
            json={
                "email": "OWNER@example.com",
                "password": "correct-horse-battery",
            },
        )
        self.assertEqual(login.status_code, 200)
        self.assertNotEqual(login.json()["access_token"], registered["access_token"])

    def test_authentication_requires_a_long_external_secret(self) -> None:
        original_secret = os.environ.get("WASTEWISE_JWT_SECRET")
        try:
            os.environ.pop("WASTEWISE_JWT_SECRET", None)
            with self.assertRaisesRegex(RuntimeError, "at least 32 bytes"):
                validate_auth_configuration()
            os.environ["WASTEWISE_JWT_SECRET"] = "too-short"
            with self.assertRaisesRegex(RuntimeError, "at least 32 bytes"):
                validate_auth_configuration()
        finally:
            if original_secret is not None:
                os.environ["WASTEWISE_JWT_SECRET"] = original_secret

    def test_duplicate_email_is_rejected_case_insensitively(self) -> None:
        self.register("same@example.com")
        duplicate = self.client.post(
            "/auth/register",
            json={
                "email": "SAME@example.com",
                "password": "another-correct-passphrase",
            },
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_incorrect_password_is_rejected(self) -> None:
        self.register("login@example.com")
        response = self.client.post(
            "/auth/login",
            json={"email": "login@example.com", "password": "incorrect-password"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("WWW-Authenticate", response.headers)

    def test_login_is_rate_limited_after_repeated_failures(self) -> None:
        self.register("limited@example.com")
        payload = {
            "email": "limited@example.com",
            "password": "incorrect-password",
        }
        for _ in range(5):
            self.assertEqual(self.client.post("/auth/login", json=payload).status_code, 401)

        limited = self.client.post("/auth/login", json=payload)
        self.assertEqual(limited.status_code, 429)
        self.assertGreater(int(limited.headers["Retry-After"]), 0)
        self.assertEqual(
            limited.json()["detail"],
            "Too many sign-in attempts. Try again later.",
        )

    def test_protected_endpoints_reject_missing_invalid_and_expired_tokens(self) -> None:
        protected_paths = (
            "/auth/me",
            "/inventory/items",
            "/inventory",
            "/expiry-risk",
            "/discount-recommendations",
            "/forecast/summary",
            "/forecast/products",
            "/forecast/product/1001",
        )
        for path in protected_paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)

        self.assertEqual(
            self.client.get(
                "/auth/me", headers=self.auth("not-a-signed-token")
            ).status_code,
            401,
        )
        expired = jwt.encode(
            {
                "sub": "1",
                "jti": "expired-token",
                "iat": datetime.now(timezone.utc) - timedelta(hours=2),
                "exp": datetime.now(timezone.utc) - timedelta(hours=1),
                "iss": "wastewise-ai",
            },
            TEST_SECRET,
            algorithm="HS256",
        )
        self.assertEqual(
            self.client.get("/auth/me", headers=self.auth(expired)).status_code,
            401,
        )
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_cors_preflight_rejects_unconfigured_origins(self) -> None:
        headers = {
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        }
        allowed = self.client.options("/auth/login", headers=headers)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(
            allowed.headers["access-control-allow-origin"],
            "http://localhost:5173",
        )

        headers["Origin"] = "https://untrusted.example"
        rejected = self.client.options("/auth/login", headers=headers)
        self.assertNotIn("access-control-allow-origin", rejected.headers)

    def test_logout_revokes_token(self) -> None:
        session = self.register("logout@example.com")
        headers = self.auth(session["access_token"])
        self.assertEqual(self.client.post("/auth/logout", headers=headers).status_code, 204)
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 401)

    def test_users_cannot_read_or_change_each_others_manual_inventory(self) -> None:
        first = self.register("first@example.com")
        item = self.client.post(
            "/inventory/items",
            headers=self.auth(first["access_token"]),
            json={
                "product_name": "Private stock",
                "category": "Produce",
                "quantity": 10,
                "price": 2.5,
                "stock_date": date.today().isoformat(),
                "expiry_date": (date.today() + timedelta(days=5)).isoformat(),
                "estimated_daily_demand": 1,
            },
        )
        self.assertEqual(item.status_code, 201)
        item_id = item.json()["id"]

        second = self.register("second@example.com")
        second_headers = self.auth(second["access_token"])
        self.assertEqual(
            self.client.get("/inventory/items", headers=second_headers).json()["total"],
            0,
        )
        self.assertEqual(
            self.client.get(
                f"/inventory/items/{item_id}", headers=second_headers
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.put(
                f"/inventory/items/{item_id}",
                headers=second_headers,
                json={
                    "product_name": "Changed stock",
                    "category": "Produce",
                    "quantity": 1,
                    "price": 2,
                    "stock_date": date.today().isoformat(),
                    "expiry_date": (date.today() + timedelta(days=5)).isoformat(),
                },
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(
                f"/inventory/items/{item_id}", headers=second_headers
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                f"/inventory/items/{item_id}",
                headers=self.auth(first["access_token"]),
            ).status_code,
            200,
        )
