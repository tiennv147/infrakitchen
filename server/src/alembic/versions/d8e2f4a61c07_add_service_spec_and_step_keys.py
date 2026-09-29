"""add service spec and step-keyed workflow steps

Revision ID: d8e2f4a61c07
Revises: c4a9d17e3b52
Create Date: 2026-09-29 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d8e2f4a61c07"
down_revision: str | None = "c4a9d17e3b52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("services", sa.Column("spec", sa.JSON(), server_default="{}", nullable=False))

    op.add_column("workflow_steps", sa.Column("step_key", sa.String(), nullable=True))
    op.add_column("workflow_steps", sa.Column("parent_step_keys", sa.JSON(), server_default="[]", nullable=False))
    op.add_column("workflow_steps", sa.Column("storage_path", sa.Text(), nullable=True))
    op.add_column("workflow_steps", sa.Column("workspace_id", sa.UUID(), nullable=True))
    op.create_index(
        "uq_workflow_steps_workflow_step_key",
        "workflow_steps",
        ["workflow_id", "step_key"],
        unique=True,
        postgresql_where=sa.text("step_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_workflow_steps_workflow_step_key", table_name="workflow_steps")
    op.drop_column("workflow_steps", "workspace_id")
    op.drop_column("workflow_steps", "storage_path")
    op.drop_column("workflow_steps", "parent_step_keys")
    op.drop_column("workflow_steps", "step_key")

    op.drop_column("services", "spec")
