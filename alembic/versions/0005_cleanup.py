"""Native cleanup stages and selectable enlargement."""

import sqlalchemy as sa

from alembic import op

revision = "0005_cleanup"
down_revision = "0004_photo_levels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("regions") as batch:
        for name in ("retouch_dust", "retouch_deblur", "retouch_gentle_denoise"):
            batch.add_column(
                sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false())
            )
        batch.add_column(
            sa.Column("retouch_output_scale", sa.Integer(), nullable=False, server_default="4")
        )


def downgrade() -> None:
    with op.batch_alter_table("regions") as batch:
        for name in (
            "retouch_output_scale", "retouch_gentle_denoise", "retouch_deblur", "retouch_dust"
        ):
            batch.drop_column(name)
