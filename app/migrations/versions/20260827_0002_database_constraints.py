"""Enforce permission and token-generation invariants.

Revision ID: 20260827_0002
Revises: 20260827_0001
"""

from alembic import op

revision = "20260827_0002"
down_revision = "20260827_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user") as batch_op:
        batch_op.create_check_constraint(
            "ck_user_session_generation_nonnegative",
            "session_generation >= 0",
        )
        batch_op.create_check_constraint(
            "ck_user_api_token_generation_nonnegative",
            "api_token_generation >= 0",
        )

    with op.batch_alter_table("permission") as batch_op:
        batch_op.create_unique_constraint(
            "uq_permission_group_path_prefix",
            ["group_id", "path_prefix"],
        )
        batch_op.create_check_constraint(
            "ck_permission_path_prefix_nonempty",
            "length(path_prefix) > 0",
        )
        batch_op.create_check_constraint(
            "ck_permission_write_requires_read",
            "can_write = 0 OR can_read = 1",
        )


def downgrade() -> None:
    with op.batch_alter_table("permission") as batch_op:
        batch_op.drop_constraint("ck_permission_write_requires_read", type_="check")
        batch_op.drop_constraint("ck_permission_path_prefix_nonempty", type_="check")
        batch_op.drop_constraint("uq_permission_group_path_prefix", type_="unique")

    with op.batch_alter_table("user") as batch_op:
        batch_op.drop_constraint("ck_user_api_token_generation_nonnegative", type_="check")
        batch_op.drop_constraint("ck_user_session_generation_nonnegative", type_="check")
