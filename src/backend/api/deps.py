"""Request-scoped dependencies."""

from collections.abc import Iterator

from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db import get_session_factory
from backend.storage import LocalStorage, Storage


def db_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def storage() -> Storage:
    return LocalStorage(get_settings().storage_root)
