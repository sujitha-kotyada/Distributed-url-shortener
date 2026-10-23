from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from url_shortener.core.cache import RedirectCache, RedisCacheError
from url_shortener.models.url import Url
from url_shortener.utils.base62 import encode_base62


class UrlCreationError(RuntimeError):
    """Raised when a shortened URL cannot be created safely."""


class UrlLookupError(RuntimeError):
    """Raised when a shortened URL cannot be looked up safely."""


def get_url_by_short_code(
    *,
    session: Session,
    short_code: str,
) -> Url | None:
    try:
        return session.scalar(select(Url).where(Url.short_code == short_code))
    except SQLAlchemyError as exc:
        session.rollback()
        raise UrlLookupError("Database error while looking up URL.") from exc


def resolve_redirect_target(
    *,
    session: Session,
    short_code: str,
    cache: RedirectCache | None,
) -> str | None:
    if cache is not None:
        try:
            cached_url = cache.get(short_code)
        except RedisCacheError:
            cached_url = None
        if cached_url is not None:
            return cached_url

    url = get_url_by_short_code(session=session, short_code=short_code)
    if url is None:
        return None

    # Enforce active invariant and expiration check
    now = datetime.now(UTC)
    if getattr(url, "is_active", True) is False:
        return None
    if url.expires_at is not None:
        expires = url.expires_at if url.expires_at.tzinfo is not None else url.expires_at.replace(tzinfo=UTC)
        if expires < now:
            if cache is not None:
                try:
                    cache.delete(short_code)
                except RedisCacheError:
                    pass
            return None

    if cache is not None:
        try:
            cache.set(short_code, url.original_url)
        except RedisCacheError:
            pass

    return url.original_url


def deactivate_url(
    *,
    session: Session,
    short_code: str,
    cache: RedirectCache | None = None,
) -> bool:
    """Deactivate a URL and invalidate any cached redirect entry."""
    url = get_url_by_short_code(session=session, short_code=short_code)
    if url is None:
        return False
    url.is_active = False
    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise UrlLookupError("Database error while deactivating URL.") from exc

    if cache is not None:
        try:
            cache.delete(short_code)
        except RedisCacheError:
            pass
    return True


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
    user_id: int | None = None,
) -> Url:
    try:
        allocated_id = allocate_url_id(session)
        url = Url(
            id=allocated_id,
            short_code=encode_base62(allocated_id),
            original_url=original_url,
            user_id=user_id,
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


def get_user_urls(
    *,
    session: Session,
    user_id: int,
    limit: int = 50,
    offset: int = 0,
) -> list[Url]:
    """Retrieve all URLs owned by a specific user with pagination."""
    try:
        return list(
            session.scalars(
                select(Url)
                .where(Url.user_id == user_id)
                .order_by(Url.created_at.desc())
                .limit(limit)
                .offset(offset)
            ).all()
        )
    except SQLAlchemyError as exc:
        raise UrlLookupError("Database error while querying user URLs.") from exc
