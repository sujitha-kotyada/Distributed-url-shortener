"""add users and url ownership

Revision ID: 202610110005
Revises: 202610110004
Create Date: 2026-10-11 00:05:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202610110005"
down_revision: str | None = "202610110004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.add_column("urls", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_urls_user_id_users",
        "urls",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_urls_user_id", "urls", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_urls_user_id", table_name="urls")
    op.drop_constraint("fk_urls_user_id_users", "urls", type_="foreignkey")
    op.drop_column("urls", "user_id")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
