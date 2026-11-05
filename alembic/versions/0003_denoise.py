"""Split the combined upscale-and-denoise flag.

Existing rows used ``retouch_upscale`` for that one step, so denoise starts equal
to it. A false upscale bit stays denoise off.

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_denoise"
down_revision: str | None = "0002_retouch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("regions") as batch:
        batch.add_column(
            sa.Column(
                "retouch_denoise",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    op.execute("UPDATE regions SET retouch_denoise = retouch_upscale")


def downgrade() -> None:
    with op.batch_alter_table("regions") as batch:
        batch.drop_column("retouch_denoise")
