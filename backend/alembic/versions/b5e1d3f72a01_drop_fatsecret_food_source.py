"""drop fatsecret food source

FatSecret is no longer in our nutrition-lookup chain (their `basic` scope
doesn't include `foods.search.v3`, and we replaced the path with OFF +
LLM-estimate). Defensive: rewrite any rows whose `source = 'fatsecret'`
to `'open_food_facts'`, since most FS hits originally came from OFF-like
data anyway and the value distribution is closer than `llm_estimate`.

The `foods.source` column is plain VARCHAR(32), so no enum-type alter is
required — just a data UPDATE.

Revision ID: b5e1d3f72a01
Revises: a2c4f6d8e012
Create Date: 2026-05-28 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "b5e1d3f72a01"
down_revision: Union[str, Sequence[str], None] = "a2c4f6d8e012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE foods SET source = 'open_food_facts' WHERE source = 'fatsecret'"
    )


def downgrade() -> None:
    # No-op — we can't reliably re-identify which OFF rows came from FS.
    pass
