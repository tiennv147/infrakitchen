from datetime import datetime, UTC
import uuid

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Mapped, mapped_column, relationship

from application.projects.model import Project
from core.base_models import Base, BaseRevision
from sqlalchemy import UUID, CheckConstraint, Column, DateTime, ForeignKey, Index, JSON, Table, func

from core.users.model import User, UserDTO


service_owners = Table(
    "service_owners",
    Base.metadata,
    Column("service_id", ForeignKey("services.id"), primary_key=True),
    Column("user_id", ForeignKey("users.id"), primary_key=True),
)

# Topology metadata only: service_id depends on depends_on_service_id.
service_links = Table(
    "service_links",
    Base.metadata,
    Column("service_id", ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
    Column("depends_on_service_id", ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
    CheckConstraint("service_id <> depends_on_service_id", name="ck_service_links_no_self"),
)


class Service(BaseRevision):
    __tablename__: str = "services"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(index=True)
    display_name: Mapped[str | None] = mapped_column(nullable=True)
    description: Mapped[str | None] = mapped_column()

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", name="fk_service_project_id"),
        nullable=False,
    )
    project: Mapped["Project"] = relationship("Project", lazy="joined")

    repository_url: Mapped[str | None] = mapped_column(nullable=True)

    labels: Mapped[list[str]] = mapped_column(JSON, default=list)

    creator: Mapped[User] = relationship("User", lazy="joined")
    owners: Mapped[list[User]] = relationship(secondary=service_owners, lazy="selectin")

    depends_on: Mapped[list["Service"]] = relationship(
        "Service",
        secondary=service_links,
        primaryjoin=lambda: Service.id == service_links.c.service_id,
        secondaryjoin=lambda: Service.id == service_links.c.depends_on_service_id,
        back_populates="dependents",
        lazy="selectin",
        passive_deletes=True,
    )
    dependents: Mapped[list["Service"]] = relationship(
        "Service",
        secondary=service_links,
        primaryjoin=lambda: Service.id == service_links.c.depends_on_service_id,
        secondaryjoin=lambda: Service.id == service_links.c.service_id,
        back_populates="depends_on",
        lazy="selectin",
        passive_deletes=True,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), default=func.now())
    revision_number: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[str | uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    # Names are unique per project rather than globally, so two projects can each own an "api" service.
    __table_args__ = (Index("ix_service_project_id_name", "project_id", "name", unique=True),)


class ServiceDTO(BaseModel):
    id: uuid.UUID = Field(...)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), frozen=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    revision_number: int = Field(default=1)
    created_by: UserDTO | uuid.UUID = Field()

    name: str = Field(...)
    display_name: str | None = Field(default=None)
    description: str = Field(default="")
    project_id: uuid.UUID = Field(...)
    repository_url: str | None = Field(default=None)
    owners: list[UserDTO] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
