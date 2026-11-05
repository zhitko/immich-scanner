"""Per-photo retouch choice, status, and derivative paths."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_retouch"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("regions") as batch:
        batch.alter_column(
            "uploaded_crop_signature",
            type_=sa.String(length=512),
            existing_type=sa.String(length=256),
            existing_nullable=True,
        )
        batch.add_column(
            sa.Column(
                "retouch_upscale",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "retouch_faces",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "retouch_colorize",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "retouch_scratches",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "upload_source",
                sa.String(length=16),
                nullable=False,
                server_default="crop",
            )
        )
        batch.add_column(
            sa.Column(
                "retouch_status",
                sa.String(length=16),
                nullable=False,
                server_default="none",
            )
        )
        batch.add_column(sa.Column("retouch_error", sa.Text(), nullable=True))
        batch.add_column(sa.Column("retouch_signature", sa.String(length=256), nullable=True))
        batch.add_column(sa.Column("retouch_path", sa.String(length=1024), nullable=True))
        batch.add_column(sa.Column("crop_path", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("regions") as batch:
        batch.drop_column("crop_path")
        batch.drop_column("retouch_path")
        batch.drop_column("retouch_signature")
        batch.drop_column("retouch_error")
        batch.drop_column("retouch_status")
        batch.drop_column("upload_source")
        batch.drop_column("retouch_scratches")
        batch.drop_column("retouch_colorize")
        batch.drop_column("retouch_faces")
        batch.drop_column("retouch_upscale")
        batch.alter_column(
            "uploaded_crop_signature",
            type_=sa.String(length=256),
            existing_type=sa.String(length=512),
            existing_nullable=True,
        )
