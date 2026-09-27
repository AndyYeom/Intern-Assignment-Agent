"""Backend tests run against a real PostgreSQL database (default: the Compose
service on localhost:5433, database utechia_test). They apply the Alembic
migration, so the schema under test is the migrated one. Skipped when the
database is unreachable.

    docker compose up -d postgres
    docker compose exec postgres createdb -U utechia utechia_test
"""

import os
from pathlib import Path

import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://utechia:local-dev-only@localhost:5433/utechia_test"
)
REPO_ROOT = Path(__file__).resolve().parents[2]


def _reachable(url: str) -> bool:
    from sqlalchemy import create_engine, text

    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def database_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    if not _reachable(TEST_DATABASE_URL):
        pytest.skip(f"PostgreSQL not reachable at {TEST_DATABASE_URL}")
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["STORAGE_ROOT"] = str(tmp_path_factory.mktemp("storage"))

    from alembic import command
    from alembic.config import Config

    from backend.config import get_settings
    from backend.db.session import get_engine, get_session_factory

    for cached in (get_settings, get_engine, get_session_factory):
        cached.cache_clear()
    config = Config(str(REPO_ROOT / "alembic.ini"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return TEST_DATABASE_URL


@pytest.fixture
def db(database_url: str):
    """A clean database with the taxonomy loaded."""
    from sqlalchemy import text

    from backend.db import get_engine, session_scope
    from backend.db.models import Base
    from backend.services.persistence import upsert_taxonomy

    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    with session_scope() as session:
        upsert_taxonomy(session, REPO_ROOT / "resources" / "taxonomy.json")
    return get_engine()


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    from backend.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
