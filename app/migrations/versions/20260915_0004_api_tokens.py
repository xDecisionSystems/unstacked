"""Create api_token, tracking issued bearer tokens for listing and revocation.

Revision ID: 20260915_0004
Revises: 20260827_0003
"""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0004"
down_revision = "20260827_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_token",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("jti", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_token_user_id", "api_token", ["user_id"], unique=False)
    op.create_index("ix_api_token_jti", "api_token", ["jti"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_api_token_jti", table_name="api_token")
    op.drop_index("ix_api_token_user_id", table_name="api_token")
    op.drop_table("api_token")
