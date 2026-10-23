"""add redirect event ids

Revision ID: 202610110004
Revises: 202610110003
Create Date: 2026-10-11 00:04:00
"""

from collections.abc import Sequence
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "202610110004"
down_revision: str | None = "202610110003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "redirect_events",
        sa.Column("event_id", sa.String(length=36), nullable=True),
    )
    connection = op.get_bind()
    event_ids = connection.execute(
        sa.text("SELECT id FROM redirect_events ORDER BY id")
    ).scalars().all()
    for event_id in event_ids:
        connection.execute(
            sa.text(
                "UPDATE redirect_events SET event_id = :event_id "
                "WHERE id = :id"
            ),
            {"event_id": str(uuid4()), "id": event_id},
        )
    op.alter_column(
        "redirect_events",
        "event_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_redirect_events_event_id",
        "redirect_events",
        ["event_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_redirect_events_event_id",
        "redirect_events",
        type_="unique",
    )
    op.drop_column("redirect_events", "event_id")