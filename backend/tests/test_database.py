from sqlalchemy import Boolean, DateTime, Integer, String, Text

from url_shortener.models.base import Base
from url_shortener.models.redirect_event import RedirectEvent
from url_shortener.models.url import Url


def test_url_model_is_registered_in_metadata() -> None:
    assert "urls" in Base.metadata.tables
    assert Url.__table__ is Base.metadata.tables["urls"]


def test_url_model_columns_are_configured() -> None:
    columns = Url.__table__.columns

    assert isinstance(columns["id"].type, Integer)
    assert columns["id"].primary_key is True
    assert columns["id"].nullable is False

    assert isinstance(columns["short_code"].type, String)
    assert columns["short_code"].type.length == 32
    assert columns["short_code"].nullable is False

    assert isinstance(columns["original_url"].type, Text)
    assert columns["original_url"].nullable is False

    assert isinstance(columns["created_at"].type, DateTime)
    assert columns["created_at"].type.timezone is True
    assert columns["created_at"].nullable is False

    assert isinstance(columns["expires_at"].type, DateTime)
    assert columns["expires_at"].type.timezone is True
    assert columns["expires_at"].nullable is True

    assert isinstance(columns["is_active"].type, Boolean)
    assert columns["is_active"].nullable is False


def test_url_model_has_unique_short_code_constraint() -> None:
    constraints = {
        constraint.name: constraint
        for constraint in Url.__table__.constraints
    }

    unique_constraint = constraints["uq_urls_short_code"]
    assert [column.name for column in unique_constraint.columns] == ["short_code"]


def test_redirect_event_model_has_url_foreign_key() -> None:
    assert RedirectEvent.__table__.columns["short_code"].nullable is False
    foreign_keys = RedirectEvent.__table__.columns["short_code"].foreign_keys

    assert len(foreign_keys) == 1
    assert next(iter(foreign_keys)).target_fullname == "urls.short_code"
