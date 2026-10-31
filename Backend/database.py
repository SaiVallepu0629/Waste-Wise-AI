import os
from functools import lru_cache
from pathlib import Path

from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_DIR / "data" / "inventory.sqlite3"
DATABASE_URL = os.environ.get("WASTEWISE_DATABASE_URL")

if DATABASE_URL and not DATABASE_URL.startswith("sqlite"):
    raise ValueError("WASTEWISE_DATABASE_URL must use SQLite.")

engine = create_engine(
    DATABASE_URL or URL.create("sqlite", database=str(DATABASE_PATH)),
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(connection, _record) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


@lru_cache(maxsize=1)
def initialize_database() -> None:
    if not DATABASE_URL:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    from Backend import models  # noqa: F401
    from Backend.migrations import apply_migrations

    Base.metadata.create_all(bind=engine)
    apply_migrations(engine)


def get_db():
    initialize_database()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
