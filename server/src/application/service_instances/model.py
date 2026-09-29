from enum import StrEnum, unique
import uuid

from sqlalchemy import UUID, CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from application.environments.model import Environment
from application.resources.model import Resource
from application.services.model import Service
from core.base_models import Base, BaseEntity
from core.users.model import User


@unique
class ServiceResourceRole(StrEnum):
    DEPENDENCY = "dependency"
    WORKLOAD = "workload"
    # Shared infrastructure the service uses but must never create or destroy.
    REFERENCED = "referenced"


class ServiceInstanceResource(Base):
    __tablename__: str = "service_instance_resources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_instances.id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("resources.id"), nullable=False)
    resource: Mapped[Resource] = relationship("Resource", lazy="joined")
    alias: Mapped[str] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default=ServiceResourceRole.DEPENDENCY)

    __table_args__ = (
        CheckConstraint("role IN ('dependency', 'workload', 'referenced')", name="ck_service_instance_resources_role"),
        Index("ix_service_instance_resources_alias", "service_instance_id", "alias", unique=True),
        # A resource has at most one owner; referencing it is unlimited.
        Index(
            "ix_service_instance_resources_owned_resource",
            "resource_id",
            unique=True,
            postgresql_where=text("role <> 'referenced'"),
        ),
    )


class ServiceInstance(BaseEntity):
    """A Service deployed to one Environment."""

    __tablename__: str = "service_instances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id", name="fk_service_instance_service_id"), nullable=False
    )
    service: Mapped[Service] = relationship("Service", lazy="joined")

    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("environments.id", name="fk_service_instance_environment_id"), nullable=False
    )
    environment: Mapped[Environment] = relationship("Environment", lazy="joined")

    # The legacy abstract `service` Resource whose dependency_config (e.g. service_name) new claims inherit.
    anchor_resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.id", name="fk_service_instance_anchor_resource_id"), nullable=True
    )
    anchor_resource: Mapped[Resource | None] = relationship("Resource", lazy="joined")

    spec_revision_applied: Mapped[int | None] = mapped_column(nullable=True)
    # Service.spec_revision the running reconcile compiled; becomes spec_revision_applied on success.
    target_spec_revision: Mapped[int | None] = mapped_column(nullable=True)

    # The workflow of the current or most recent run; cleared when a new run starts.
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", name="fk_service_instance_workflow_id", ondelete="SET NULL"),
        nullable=True,
    )

    resources: Mapped[list[ServiceInstanceResource]] = relationship(
        "ServiceInstanceResource", lazy="selectin", cascade="all, delete-orphan"
    )

    creator: Mapped[User] = relationship("User", lazy="joined")

    __table_args__ = (Index("ix_service_instance_service_environment", "service_id", "environment_id", unique=True),)
