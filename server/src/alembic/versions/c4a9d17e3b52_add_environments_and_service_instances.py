"""add environments and service instances

Revision ID: c4a9d17e3b52
Revises: b7e41c9d2f08
Create Date: 2026-09-25 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4a9d17e3b52"
down_revision: str | None = "b7e41c9d2f08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MODEL_STATUS = (
    "QUEUED",
    "IN_PROGRESS",
    "DONE",
    "ERROR",
    "CANCELLED",
    "UNKNOWN",
    "APPROVAL_PENDING",
    "PENDING",
    "REJECTED",
    "READY",
    "ENABLED",
    "DISABLED",
)
MODEL_STATE = ("PROVISION", "PROVISIONED", "DESTROY", "DESTROYED")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "environments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("tier", sa.String(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("region", sa.String(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("cluster_name", sa.String(), nullable=True),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("storage_id", sa.UUID(), nullable=True),
        sa.Column("storage_path_prefix", sa.String(), nullable=True),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("status", sa.Enum(*MODEL_STATUS, name="model_status", native_enum=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_environment_project_id"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_environment_workspace_id"),
        sa.ForeignKeyConstraint(["storage_id"], ["storages.id"], name="fk_environment_storage_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_environments_name"), "environments", ["name"], unique=True)

    op.create_table(
        "environment_integrations",
        sa.Column("environment_id", sa.UUID(), nullable=False),
        sa.Column("integration_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["integration_id"], ["integrations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("environment_id", "integration_id"),
    )

    op.create_table(
        "environment_parent_resources",
        sa.Column("environment_id", sa.UUID(), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("environment_id", "resource_id"),
    )

    op.create_table(
        "service_instances",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("service_id", sa.UUID(), nullable=False),
        sa.Column("environment_id", sa.UUID(), nullable=False),
        sa.Column("anchor_resource_id", sa.UUID(), nullable=True),
        sa.Column("spec_revision_applied", sa.Integer(), nullable=True),
        sa.Column("state", sa.Enum(*MODEL_STATE, name="model_state", native_enum=False), nullable=False),
        sa.Column("status", sa.Enum(*MODEL_STATUS, name="model_status", native_enum=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], name="fk_service_instance_service_id"),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], name="fk_service_instance_environment_id"),
        sa.ForeignKeyConstraint(
            ["anchor_resource_id"], ["resources.id"], name="fk_service_instance_anchor_resource_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_service_instance_service_environment",
        "service_instances",
        ["service_id", "environment_id"],
        unique=True,
    )

    op.create_table(
        "service_instance_resources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("service_instance_id", sa.UUID(), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column("alias", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.CheckConstraint(
            "role IN ('dependency', 'workload', 'referenced')", name="ck_service_instance_resources_role"
        ),
        sa.ForeignKeyConstraint(["service_instance_id"], ["service_instances.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_service_instance_resources_alias",
        "service_instance_resources",
        ["service_instance_id", "alias"],
        unique=True,
    )
    # A resource has at most one owner; referencing it is unlimited.
    op.create_index(
        "ix_service_instance_resources_owned_resource",
        "service_instance_resources",
        ["resource_id"],
        unique=True,
        postgresql_where=sa.text("role <> 'referenced'"),
    )

    op.create_table(
        "service_links",
        sa.Column("service_id", sa.UUID(), nullable=False),
        sa.Column("depends_on_service_id", sa.UUID(), nullable=False),
        sa.CheckConstraint("service_id <> depends_on_service_id", name="ck_service_links_no_self"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["depends_on_service_id"], ["services.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("service_id", "depends_on_service_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("service_links")
    op.drop_index("ix_service_instance_resources_owned_resource", table_name="service_instance_resources")
    op.drop_index("ix_service_instance_resources_alias", table_name="service_instance_resources")
    op.drop_table("service_instance_resources")
    op.drop_index("ix_service_instance_service_environment", table_name="service_instances")
    op.drop_table("service_instances")
    op.drop_table("environment_parent_resources")
    op.drop_table("environment_integrations")
    op.drop_index(op.f("ix_environments_name"), table_name="environments")
    op.drop_table("environments")
