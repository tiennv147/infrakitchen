from datetime import datetime, UTC
import uuid

from pydantic import BaseModel, ConfigDict, Field, computed_field

from application.environments.schema import EnvironmentShort
from application.resources.schema import ResourceShort
from application.services.schema import ServiceShort
from core.constants.model import ModelState, ModelStatus
from core.users.schema import UserShort

from .model import ServiceResourceRole


class ServiceInstanceResourceResponse(BaseModel):
    id: uuid.UUID
    alias: str
    role: ServiceResourceRole
    resource_id: uuid.UUID
    resource: ResourceShort | None = Field(default=None)

    model_config = ConfigDict(from_attributes=True)


class ServiceInstanceCreate(BaseModel):
    service_id: uuid.UUID = Field(...)
    environment_id: uuid.UUID = Field(...)
    anchor_resource_id: uuid.UUID | None = Field(default=None)

    model_config = ConfigDict(from_attributes=True)


class ServiceInstanceResponse(BaseModel):
    id: uuid.UUID = Field(...)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), frozen=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    revision_number: int = Field(default=1)
    creator: UserShort | None = Field(default=None)

    service_id: uuid.UUID = Field(...)
    service: ServiceShort | None = Field(default=None)
    environment_id: uuid.UUID = Field(...)
    environment: EnvironmentShort | None = Field(default=None)
    anchor_resource_id: uuid.UUID | None = Field(default=None)
    anchor_resource: ResourceShort | None = Field(default=None)
    spec_revision_applied: int | None = Field(default=None)
    state: ModelState = Field(default=ModelState.PROVISION)
    status: ModelStatus = Field(default=ModelStatus.READY)
    resources: list[ServiceInstanceResourceResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    def _entity_name(self) -> str:
        return "service_instance"
