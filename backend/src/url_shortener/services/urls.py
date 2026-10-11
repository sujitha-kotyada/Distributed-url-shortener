from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from url_shortener.models.url import Url
from url_shortener.utils.base62 import encode_base62


class UrlCreationError(RuntimeError):
    """Raised when a shortened URL cannot be created safely."""


def allocate_url_id(session: Session) -> int:
    """Allocate an ID from PostgreSQL; sequence values are not rolled back."""
    if session.get_bind().dialect.name != "postgresql":
        raise UrlCreationError("URL ID allocation requires PostgreSQL.")

    try:
        allocated_id = session.execute(
            text(
                """
                SELECT nextval(
                    pg_get_serial_sequence(:table_name, :column_name)
                )
                """
            ),
            {"table_name": "public.urls", "column_name": "id"},
        ).scalar_one()
    except SQLAlchemyError as exc:
        raise UrlCreationError("Database error while allocating URL ID.") from exc

    if not isinstance(allocated_id, int):
        raise UrlCreationError("Database returned an invalid URL ID.")
    return allocated_id


def create_short_url(
    *,
    session: Session,
    original_url: str,
) -> Url:
    try:
        allocated_id = allocate_url_id(session)
        url = Url(
            id=allocated_id,
            short_code=encode_base62(allocated_id),
            original_url=original_url,
        )
        session.add(url)
        session.commit()
        session.refresh(url)
    except SQLAlchemyError as exc:
        session.rollback()
        raise UrlCreationError("Database error while creating URL.") from exc
    except UrlCreationError:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise

    return url
