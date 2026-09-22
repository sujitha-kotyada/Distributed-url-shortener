from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from url_shortener.core.config import get_settings


class DatabaseUnavailableError(RuntimeError):
    """Raised when the database cannot be reached or is not configured."""


@lru_cache
def get_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def create_database_engine() -> Engine:
    settings = get_settings()
    if settings.database_url is None:
        raise DatabaseUnavailableError("Database is not configured.")
    return get_engine(str(settings.database_url))


def create_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    bind = engine if engine is not None else create_database_engine()
    return sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    session_factory = create_session_factory()
    with session_factory() as session:
        yield session


def check_database_health() -> None:
    try:
        session_factory = create_session_factory()
        with session_factory() as session:
            session.execute(text("SELECT 1"))
    except DatabaseUnavailableError:
        raise
    except SQLAlchemyError as exc:
        raise DatabaseUnavailableError("Database health check failed.") from exc
