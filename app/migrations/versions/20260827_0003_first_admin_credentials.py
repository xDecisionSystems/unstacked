"""Add username login and the mandatory first-password-change flag.

Revision ID: 20260827_0003
Revises: 20260827_0002
"""

import sqlalchemy as sa
from alembic import op

revision = "20260827_0003"
down_revision = "20260827_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing deployments authenticated by unique email.  Preserve that
    # stable identifier as their initial username before making the new column
    # required, so an upgrade neither loses access nor needs a second account.
    with op.batch_alter_table("user") as batch_op:
        batch_op.add_column(sa.Column("username", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "must_change_password",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    op.execute('UPDATE "user" SET username = email WHERE username IS NULL')

    with op.batch_alter_table("user") as batch_op:
        batch_op.alter_column("username", existing_type=sa.String(), nullable=False)
        batch_op.create_unique_constraint("uq_user_username", ["username"])
        batch_op.create_check_constraint("ck_user_username_nonempty", "length(username) > 0")


def downgrade() -> None:
    with op.batch_alter_table("user") as batch_op:
        batch_op.drop_constraint("ck_user_username_nonempty", type_="check")
        batch_op.drop_constraint("uq_user_username", type_="unique")
        batch_op.drop_column("must_change_password")
        batch_op.drop_column("username")
