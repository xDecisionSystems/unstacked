"""Track the owner's token generation at issuance on each api_token row.

Revision ID: 20260916_0005
Revises: 20260915_0004
"""

import sqlalchemy as sa
from alembic import op

revision = "20260916_0005"
down_revision = "20260915_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("api_token") as batch_op:
        batch_op.add_column(
            sa.Column("generation", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("api_token") as batch_op:
        batch_op.drop_column("generation")
