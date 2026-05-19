"""add target_weight_kg to users

Asked during onboarding when goal is LOSE or GAIN. Nullable because users
who pick MAINTAIN don't have one.

Revision ID: 7b21e8c4f15a
Revises: 3a9801ca256a
Create Date: 2026-05-20 00:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7b21e8c4f15a"
down_revision: Union[str, Sequence[str], None] = "3a9801ca256a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("target_weight_kg", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "target_weight_kg")
