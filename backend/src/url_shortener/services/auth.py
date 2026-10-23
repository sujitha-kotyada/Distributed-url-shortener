from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from url_shortener.core.security import hash_password, verify_password
from url_shortener.models.user import User


class UserAlreadyExistsError(RuntimeError):
    """Raised when an email is already registered."""


class AuthDatabaseError(RuntimeError):
    """Raised when a database error occurs during authentication."""


def get_user_by_email(session: Session, email: str) -> User | None:
    try:
        return session.scalar(select(User).where(User.email == email.strip().lower()))
    except SQLAlchemyError as exc:
        raise AuthDatabaseError("Failed to query user by email.") from exc


def get_user_by_id(session: Session, user_id: int) -> User | None:
    try:
        return session.scalar(select(User).where(User.id == user_id))
    except SQLAlchemyError as exc:
        raise AuthDatabaseError("Failed to query user by id.") from exc


def register_user(session: Session, *, email: str, password: str) -> User:
    normalized_email = email.strip().lower()
    existing = get_user_by_email(session, normalized_email)
    if existing is not None:
        raise UserAlreadyExistsError(f"A user with email {normalized_email!r} already exists.")

    hashed = hash_password(password)
    user = User(email=normalized_email, hashed_password=hashed)
    try:
        session.add(user)
        session.commit()
        session.refresh(user)
        return user
    except IntegrityError as exc:
        session.rollback()
        raise UserAlreadyExistsError(f"A user with email {normalized_email!r} already exists.") from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise AuthDatabaseError("Failed to save new user.") from exc


def authenticate_user(session: Session, *, email: str, password: str) -> User | None:
    user = get_user_by_email(session, email)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
