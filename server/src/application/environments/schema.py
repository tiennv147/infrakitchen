from datetime import datetime, UTC
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, computed_field

from application.integrations.schema import IntegrationShort
from application.projects.schema import ProjectShort
from application.resources.schema import ResourceShort
from application.storages.schema import StorageShort
from application.workspaces.schema import WorkspaceShort
from core.constants.model import ModelStatus
from core.users.schema import UserShort

type EnvironmentTier = Literal["dev", "staging", "prod"]


class EnvironmentShort(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str | None = Field(default=None)
    tier: EnvironmentTier = Field(default="dev")

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    def _entity_name(self) -> str:
        return "environment"


class EnvironmentCreate(BaseModel):
    name: str = Field(..., min_length=1)
    display_name: str | None = Field(default=None)
    description: str = Field(default="")
    tier: EnvironmentTier = Field(default="dev")
    rank: int = Field(default=0, ge=0)
    project_id: uuid.UUID | None = Field(default=None)
    region: str | None = Field(default=None)
    account_id: str | None = Field(default=None)
    cluster_name: str | None = Field(default=None)
    workspace_id: uuid.UUID | None = Field(default=None)
    storage_id: uuid.UUID | None = Field(default=None)
    storage_path_prefix: str | None = Field(default=None)
    integration_ids: list[uuid.UUID] = Field(default_factory=list)
    parent_resources: list[uuid.UUID] = Field(default_factory=list)
    approval_required: bool = Field(default=False)
    labels: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class EnvironmentUpdate(BaseModel):
    display_name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    tier: EnvironmentTier | None = Field(default=None)
    rank: int | None = Field(default=None, ge=0)
    project_id: uuid.UUID | None = Field(default=None)
    region: str | None = Field(default=None)
    account_id: str | None = Field(default=None)
    cluster_name: str | None = Field(default=None)
    workspace_id: uuid.UUID | None = Field(default=None)
    storage_id: uuid.UUID | None = Field(default=None)
    storage_path_prefix: str | None = Field(default=None)
    integration_ids: list[uuid.UUID] | None = Field(default=None)
    parent_resources: list[uuid.UUID] | None = Field(default=None)
    approval_required: bool | None = Field(default=None)
    labels: list[str] | None = Field(default=None)

    model_config = ConfigDict(from_attributes=True)


class EnvironmentResponse(BaseModel):
    id: uuid.UUID = Field(...)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), frozen=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    revision_number: int = Field(default=1)
    creator: UserShort | None = Field(default=None)

    name: str = Field(...)
    display_name: str | None = Field(default=None)
    description: str = Field(default="")
    tier: EnvironmentTier = Field(default="dev")
    rank: int = Field(default=0)
    project_id: uuid.UUID | None = Field(default=None)
    project: ProjectShort | None = Field(default=None)
    region: str | None = Field(default=None)
    account_id: str | None = Field(default=None)
    cluster_name: str | None = Field(default=None)
    workspace_id: uuid.UUID | None = Field(default=None)
    workspace: WorkspaceShort | None = Field(default=None)
    storage_id: uuid.UUID | None = Field(default=None)
    storage: StorageShort | None = Field(default=None)
    storage_path_prefix: str | None = Field(default=None)
    integration_ids: list[IntegrationShort] = Field(default_factory=list)
    parent_resources: list[ResourceShort] = Field(default_factory=list)
    approval_required: bool = Field(default=False)
    labels: list[str] = Field(default_factory=list)
    status: ModelStatus = Field(default=ModelStatus.ENABLED)

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    def _entity_name(self) -> str:
        return "environment"
