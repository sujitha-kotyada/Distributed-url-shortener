"""allow transient null short code

Revision ID: 202610110001
Revises: 202609220001
Create Date: 2026-10-11 00:00:01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202610110001"
down_revision: str | None = "202609220001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "urls",
        "short_code",
        existing_type=sa.String(length=32),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "urls",
        "short_code",
        existing_type=sa.String(length=32),
        nullable=False,
    )
