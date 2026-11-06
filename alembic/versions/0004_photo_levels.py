"""Optional color balance and contrast correction for faded prints."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_photo_levels"
down_revision: str | None = "0003_denoise"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("regions") as batch:
        for name in ("retouch_color_balance", "retouch_contrast"):
            batch.add_column(
                sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false())
            )


def downgrade() -> None:
    with op.batch_alter_table("regions") as batch:
        batch.drop_column("retouch_contrast")
        batch.drop_column("retouch_color_balance")
