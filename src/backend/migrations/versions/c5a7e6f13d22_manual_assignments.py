"""manual assignments: manager can place an applicant directly

Revision ID: c5a7e6f13d22
Revises: b41f2c7d9e10
Create Date: 2026-09-27 22:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5a7e6f13d22"
down_revision: str | Sequence[str] | None = "b41f2c7d9e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assignments",
        sa.Column("manual", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("assignments", "manual")
