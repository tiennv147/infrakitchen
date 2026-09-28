from datetime import datetime
import uuid

from sqlalchemy import UUID, Column, DateTime, ForeignKey, JSON, Table, func
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from application.integrations.model import Integration
from application.projects.model import Project
from application.resources.model import Resource
from application.storages.model import Storage
from application.workspaces.model import Workspace
from core.base_models import Base, BaseRevision
from core.constants.model import ModelStatus
from core.users.model import User


environment_integrations = Table(
    "environment_integrations",
    Base.metadata,
    Column("environment_id", ForeignKey("environments.id", ondelete="CASCADE"), primary_key=True),
    Column("integration_id", ForeignKey("integrations.id", ondelete="CASCADE"), primary_key=True),
)

environment_parent_resources = Table(
    "environment_parent_resources",
    Base.metadata,
    Column("environment_id", ForeignKey("environments.id", ondelete="CASCADE"), primary_key=True),
    Column("resource_id", ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True),
)


class Environment(BaseRevision):
    """A deployment target: one environment in one region/cluster."""

    __tablename__: str = "environments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(nullable=True)
    description: Mapped[str] = mapped_column(default="")

    tier: Mapped[str] = mapped_column(default="dev")
    rank: Mapped[int] = mapped_column(default=0)

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", name="fk_environment_project_id"),
        nullable=True,
    )
    project: Mapped[Project | None] = relationship("Project", lazy="joined")

    region: Mapped[str | None] = mapped_column(nullable=True)
    account_id: Mapped[str | None] = mapped_column(nullable=True)
    cluster_name: Mapped[str | None] = mapped_column(nullable=True)

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", name="fk_environment_workspace_id"),
        nullable=True,
    )
    workspace: Mapped[Workspace | None] = relationship("Workspace", lazy="joined")

    storage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("storages.id", name="fk_environment_storage_id"),
        nullable=True,
    )
    storage: Mapped[Storage | None] = relationship("Storage", lazy="joined")
    storage_path_prefix: Mapped[str | None] = mapped_column(nullable=True)

    integration_ids: Mapped[list[Integration]] = relationship(secondary=environment_integrations, lazy="selectin")
    # Landing-zone resources that claims created in this environment attach under.
    parent_resources: Mapped[list[Resource]] = relationship(secondary=environment_parent_resources, lazy="selectin")

    approval_required: Mapped[bool] = mapped_column(default=False)

    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[ModelStatus] = mapped_column(
        SQLAlchemyEnum(ModelStatus, name="model_status", native_enum=False),
        nullable=False,
        default=ModelStatus.ENABLED,
    )

    creator: Mapped[User] = relationship("User", lazy="joined")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), default=func.now())
    revision_number: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[str | uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
