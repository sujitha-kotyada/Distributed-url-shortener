"""create redirect events table

Revision ID: 202610110003
Revises: 202610110002
Create Date: 2026-10-11 00:03:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202610110003"
down_revision: str | None = "202610110002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "redirect_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("short_code", sa.String(length=32), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["short_code"],
            ["urls.short_code"],
            name="fk_redirect_events_short_code_urls",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_redirect_events")),
    )
    op.create_index(
        "ix_redirect_events_short_code_occurred_at",
        "redirect_events",
        ["short_code", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_redirect_events_short_code_occurred_at",
        table_name="redirect_events",
    )
    op.drop_table("redirect_events")
