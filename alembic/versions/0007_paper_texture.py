"""Optional native-resolution paper texture reduction."""

import sqlalchemy as sa

from alembic import op

revision = "0007_paper_texture"
down_revision = "0006_photo_matching"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("regions") as batch:
        for name in ("retouch_paper_mesh", "retouch_paper_embossed"):
            batch.add_column(
                sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false())
            )


def downgrade() -> None:
    with op.batch_alter_table("regions") as batch:
        batch.drop_column("retouch_paper_embossed")
        batch.drop_column("retouch_paper_mesh")
