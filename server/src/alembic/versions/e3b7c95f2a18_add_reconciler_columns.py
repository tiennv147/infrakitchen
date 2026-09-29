"""add reconciler columns

Revision ID: e3b7c95f2a18
Revises: d8e2f4a61c07
Create Date: 2026-09-29 14:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e3b7c95f2a18"
down_revision: str | None = "d8e2f4a61c07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("services", sa.Column("spec_revision", sa.Integer(), server_default="1", nullable=False))

    op.add_column("workflows", sa.Column("parent_entity_name", sa.String(), nullable=True))
    op.add_column("workflows", sa.Column("parent_entity_id", sa.UUID(), nullable=True))

    op.add_column("service_instances", sa.Column("target_spec_revision", sa.Integer(), nullable=True))
    op.add_column("service_instances", sa.Column("workflow_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_service_instance_workflow_id",
        "service_instances",
        "workflows",
        ["workflow_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_service_instance_workflow_id", "service_instances", type_="foreignkey")
    op.drop_column("service_instances", "workflow_id")
    op.drop_column("service_instances", "target_spec_revision")

    op.drop_column("workflows", "parent_entity_id")
    op.drop_column("workflows", "parent_entity_name")

    op.drop_column("services", "spec_revision")
