"""Create users, groups, memberships, and path permissions.

Revision ID: 20260827_0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "20260827_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("session_generation", sa.Integer(), nullable=False),
        sa.Column("api_token_generation", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_email", "user", ["email"], unique=True)
    op.create_table(
        "group",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_group_name", "group", ["name"], unique=True)
    op.create_table(
        "usergroup",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["group.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "group_id"),
    )
    op.create_table(
        "permission",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("path_prefix", sa.String(), nullable=False),
        sa.Column("can_read", sa.Boolean(), nullable=False),
        sa.Column("can_write", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["group.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_permission_group_id", "permission", ["group_id"], unique=False)
    op.create_index(
        "ix_permission_path_prefix",
        "permission",
        ["path_prefix"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_permission_path_prefix", table_name="permission")
    op.drop_index("ix_permission_group_id", table_name="permission")
    op.drop_table("permission")
    op.drop_table("usergroup")
    op.drop_index("ix_group_name", table_name="group")
    op.drop_table("group")
    op.drop_index("ix_user_email", table_name="user")
    op.drop_table("user")
