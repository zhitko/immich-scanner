"""Optional light corner repair."""

import sqlalchemy as sa

from alembic import op

revision = "0008_light_corners"
down_revision = "0007_paper_texture"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("regions") as batch:
        batch.add_column(
            sa.Column(
                "retouch_light_corners", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("regions") as batch:
        batch.drop_column("retouch_light_corners")
