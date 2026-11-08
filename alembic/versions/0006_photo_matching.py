"""Persistent visual index and metadata match review."""

import sqlalchemy as sa

from alembic import op

revision = "0006_photo_matching"
down_revision = "0005_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "photo_index",
        sa.Column(
            "region_id",
            sa.String(36),
            sa.ForeignKey("regions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("signature", sa.String(256), nullable=False),
        sa.Column("features", sa.LargeBinary(), nullable=False),
    )
    op.create_table(
        "photo_matches",
        sa.Column(
            "source_id",
            sa.String(36),
            sa.ForeignKey("regions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "target_id",
            sa.String(36),
            sa.ForeignKey("regions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("source_signature", sa.String(256), nullable=False),
        sa.Column("target_signature", sa.String(256), nullable=False),
        sa.Column("dismissed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Only one collection-wide matcher can be queued/running, even across API processes.
    op.create_index(
        "uq_active_matching_job",
        "jobs",
        ["type"],
        unique=True,
        sqlite_where=sa.text("type = 'match' AND status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_active_matching_job", table_name="jobs")
    op.drop_table("photo_matches")
    op.drop_table("photo_index")
