"""drop usda food source

USDA is no longer in our nutrition-lookup chain (OFF + FatSecret + LLM cover
the domain). Defensive: convert any existing 'usda' rows to 'llm_estimate' so
nothing in the catalog points at a now-removed enum value. The `foods.source`
column is plain VARCHAR(32), so no enum-type alter is required.

Revision ID: a2c4f6d8e012
Revises: 7b21e8c4f15a
Create Date: 2026-05-27 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "a2c4f6d8e012"
down_revision: Union[str, Sequence[str], None] = "7b21e8c4f15a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE foods SET source = 'llm_estimate' WHERE source = 'usda'")


def downgrade() -> None:
    # No-op — we can't reliably re-identify which rows used to be 'usda'.
    pass
