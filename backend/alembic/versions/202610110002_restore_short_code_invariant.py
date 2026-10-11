"""restore non-null short codes

Revision ID: 202610110002
Revises: 202610110001
Create Date: 2026-10-11 00:02:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

from url_shortener.utils.base62 import encode_base62


revision: str = "202610110002"
down_revision: str | None = "202610110001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    null_rows = connection.execute(
        sa.text("SELECT id FROM urls WHERE short_code IS NULL ORDER BY id")
    ).scalars().all()

    for url_id in null_rows:
        short_code = encode_base62(url_id)
        collision = connection.execute(
            sa.text(
                """
                SELECT 1
                FROM urls
                WHERE short_code = :short_code AND id <> :url_id
                """
            ),
            {"short_code": short_code, "url_id": url_id},
        ).scalar_one_or_none()
        if collision is not None:
            raise RuntimeError(
                f"Cannot safely backfill urls.id={url_id}: "
                f"short_code {short_code!r} already exists."
            )

        connection.execute(
            sa.text(
                "UPDATE urls SET short_code = :short_code WHERE id = :url_id"
            ),
            {"short_code": short_code, "url_id": url_id},
        )

    max_id = connection.execute(sa.text("SELECT MAX(id) FROM urls")).scalar_one()
    if max_id is not None:
        connection.execute(
            sa.text(
                """
                SELECT setval(
                    pg_get_serial_sequence(:table_name, :column_name),
                    :max_id,
                    true
                )
                """
            ),
            {
                "table_name": "public.urls",
                "column_name": "id",
                "max_id": max_id,
            },
        )

    op.alter_column(
        "urls",
        "short_code",
        existing_type=sa.String(length=32),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "urls",
        "short_code",
        existing_type=sa.String(length=32),
        nullable=True,
    )
