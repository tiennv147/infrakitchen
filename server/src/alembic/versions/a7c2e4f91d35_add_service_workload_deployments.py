"""add service workload deployments

Revision ID: a7c2e4f91d35
Revises: f5a1d3c8b624
Create Date: 2026-09-30 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7c2e4f91d35"
down_revision: str | None = "f5a1d3c8b624"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("service_instances", sa.Column("workload_version", sa.String(), nullable=True))
    op.create_table(
        "service_deployments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("service_id", sa.UUID(), nullable=False),
        sa.Column("service_instance_id", sa.UUID(), nullable=False),
        sa.Column("environment_id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("previous_version", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('waiting', 'active', 'done', 'error', 'cancelled', 'superseded')",
            name="ck_service_deployments_status",
        ),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_instance_id"], ["service_instances.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_service_deployments_instance", "service_deployments", ["service_instance_id", "created_at"])
    op.create_index("ix_service_deployments_batch", "service_deployments", ["batch_id", "position"])
    op.create_index(
        "ix_service_deployments_one_active",
        "service_deployments",
        ["service_instance_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_service_deployments_one_active", table_name="service_deployments")
    op.drop_index("ix_service_deployments_batch", table_name="service_deployments")
    op.drop_index("ix_service_deployments_instance", table_name="service_deployments")
    op.drop_table("service_deployments")
    op.drop_column("service_instances", "workload_version")
