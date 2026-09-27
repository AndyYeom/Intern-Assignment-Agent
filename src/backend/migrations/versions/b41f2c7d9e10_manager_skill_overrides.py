"""manager skill overrides: soft delete, edit tracking, manager-added rows

Revision ID: b41f2c7d9e10
Revises: 9723031b8a36
Create Date: 2026-09-27 21:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b41f2c7d9e10"
down_revision: str | Sequence[str] | None = "9723031b8a36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "applicant_skills",
        sa.Column("source", sa.String(length=10), server_default="agent", nullable=False),
    )
    op.add_column("applicant_skills", sa.Column("edited_at", sa.DateTime(timezone=True)))
    op.add_column("applicant_skills", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_applicant_skills_source", "applicant_skills", "source IN ('agent', 'manager')"
    )

    op.add_column(
        "applicant_skill_evidence",
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("applicant_skill_evidence", sa.Column("edited_at", sa.DateTime(timezone=True)))
    op.add_column("applicant_skill_evidence", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.drop_constraint("ck_evidence_source", "applicant_skill_evidence", type_="check")
    op.create_check_constraint(
        "ck_evidence_source",
        "applicant_skill_evidence",
        "source_type IN ('resume', 'portfolio', 'github', 'manager')",
    )
    op.create_check_constraint(
        "ck_evidence_level", "applicant_skill_evidence", "level IS NULL OR level BETWEEN 0 AND 3"
    )


def downgrade() -> None:
    op.drop_constraint("ck_evidence_level", "applicant_skill_evidence", type_="check")
    op.execute("DELETE FROM applicant_skill_evidence WHERE source_type = 'manager'")
    op.drop_constraint("ck_evidence_source", "applicant_skill_evidence", type_="check")
    op.create_check_constraint(
        "ck_evidence_source",
        "applicant_skill_evidence",
        "source_type IN ('resume', 'portfolio', 'github')",
    )
    op.drop_column("applicant_skill_evidence", "deleted_at")
    op.drop_column("applicant_skill_evidence", "edited_at")
    op.drop_column("applicant_skill_evidence", "position")
    op.drop_constraint("ck_applicant_skills_source", "applicant_skills", type_="check")
    op.drop_column("applicant_skills", "deleted_at")
    op.drop_column("applicant_skills", "edited_at")
    op.drop_column("applicant_skills", "source")
