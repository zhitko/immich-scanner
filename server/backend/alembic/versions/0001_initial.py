"""Initial schema for scans, regions, jobs, and settings."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scans",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("original_path", sa.String(length=1024), nullable=True),
        sa.Column("preview_path", sa.String(length=1024), nullable=True),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("dpi", sa.Integer(), nullable=True),
        sa.Column("device_name", sa.String(length=256), nullable=True),
        sa.Column("upload_state", sa.String(length=32), nullable=False),
        sa.Column("files_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("detection_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_scans_created_at", "scans", ["created_at"])
    op.create_table(
        "regions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "scan_id",
            sa.String(length=36),
            sa.ForeignKey("scans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("center_x", sa.Float(), nullable=False),
        sa.Column("center_y", sa.Float(), nullable=False),
        sa.Column("width", sa.Float(), nullable=False),
        sa.Column("height", sa.Float(), nullable=False),
        sa.Column("angle_deg", sa.Float(), nullable=False),
        sa.Column("quarter_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("taken_at", sa.DateTime(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("album_id", sa.String(length=64), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("visibility", sa.String(length=32), nullable=True),
        sa.Column("upload_status", sa.String(length=32), nullable=False),
        sa.Column("immich_asset_id", sa.String(length=64), nullable=True),
        sa.Column("immich_status", sa.String(length=32), nullable=True),
        sa.Column("album_linked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metadata_synced", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("uploaded_crop_signature", sa.String(length=256), nullable=True),
        sa.Column("upload_error", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_regions_scan_id", "regions", ["scan_id"])
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "scan_id",
            sa.String(length=36),
            sa.ForeignKey("scans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("region_id", sa.String(length=36), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_jobs_status_created", "jobs", ["status", "created_at"])
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_index("ix_jobs_status_created", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_regions_scan_id", table_name="regions")
    op.drop_table("regions")
    op.drop_index("ix_scans_created_at", table_name="scans")
    op.drop_table("scans")
