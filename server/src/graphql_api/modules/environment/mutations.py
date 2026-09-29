import uuid

import strawberry
from strawberry.experimental import pydantic as strawberry_pydantic
from strawberry.scalars import JSON
from strawberry.types import Info

from application.environments.dependencies import get_environment_service
from application.environments.schema import EnvironmentCreate, EnvironmentUpdate
from core.base_models import PatchBodyModel
from core.constants.model import ModelActions
from core.errors import AccessDenied
from core.users.functions import user_has_access_to_entity
from graphql_api.helpers import IsAuthenticated, check_api_permission
from graphql_api.modules.environment.types import EnvironmentType
from graphql_api.modules.permission.mutations import EntityPolicyCreateInput
from graphql_api.modules.permission.types import PermissionType


@strawberry_pydantic.input(model=EnvironmentCreate, all_fields=True)
class EnvironmentCreateInput:
    name: str = strawberry.UNSET
    display_name: str | None = None
    description: str = ""
    tier: str = "dev"
    rank: int = 0
    project_id: uuid.UUID | None = None
    region: str | None = None
    account_id: str | None = None
    cluster_name: str | None = None
    workspace_id: uuid.UUID | None = None
    storage_id: uuid.UUID | None = None
    storage_path_prefix: str | None = None
    integration_ids: list[uuid.UUID] = strawberry.field(default_factory=list)
    parent_resources: list[uuid.UUID] = strawberry.field(default_factory=list)
    approval_required: bool = False
    binding_sink: JSON | None = None
    labels: list[str] = strawberry.field(default_factory=list)


@strawberry_pydantic.input(model=EnvironmentUpdate, all_fields=False)
class EnvironmentUpdateInput:
    display_name: str | None = None
    description: str | None = None
    tier: str | None = None
    rank: int | None = None
    project_id: uuid.UUID | None = None
    region: str | None = None
    account_id: str | None = None
    cluster_name: str | None = None
    workspace_id: uuid.UUID | None = None
    storage_id: uuid.UUID | None = None
    storage_path_prefix: str | None = None
    integration_ids: list[uuid.UUID] | None = None
    parent_resources: list[uuid.UUID] | None = None
    approval_required: bool | None = None
    binding_sink: JSON | None = None
    labels: list[str] | None = None


@strawberry.input
class EnvironmentActionInput:
    action: str


@strawberry.type
class EnvironmentMutation:
    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def create_environment(self, info: Info, input: EnvironmentCreateInput) -> EnvironmentType:
        await check_api_permission(info, "environment", ["admin"])
        requester = info.context["request"].state.user
        service = get_environment_service(info.context["session"])
        return await service.create_environment(environment=input.to_pydantic(), requester=requester)

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def update_environment(self, info: Info, id: uuid.UUID, input: EnvironmentUpdateInput) -> EnvironmentType:
        requester = info.context["request"].state.user
        service = get_environment_service(info.context["session"])

        if ModelActions.EDIT not in await service.get_actions(environment_id=id, requester=requester):
            raise AccessDenied(f"Access denied for action {ModelActions.EDIT.value}")

        return await service.update_environment(
            environment_id=str(id), environment=input.to_pydantic(), requester=requester
        )

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def environment_action(self, info: Info, id: uuid.UUID, input: EnvironmentActionInput) -> EnvironmentType:
        requester = info.context["request"].state.user
        service = get_environment_service(info.context["session"])

        if input.action not in {ModelActions.ENABLE.value, ModelActions.DISABLE.value}:
            raise ValueError("Invalid action")
        if input.action not in await service.get_actions(environment_id=id, requester=requester):
            raise AccessDenied(f"Access denied for action {input.action}")

        return await service.patch_action(
            environment_id=str(id), body=PatchBodyModel(action=input.action), requester=requester
        )

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def delete_environment(self, info: Info, id: uuid.UUID) -> bool:
        requester = info.context["request"].state.user
        service = get_environment_service(info.context["session"])

        if ModelActions.DELETE not in await service.get_actions(environment_id=id, requester=requester):
            raise AccessDenied(f"Access denied for action {ModelActions.DELETE.value}")

        await service.delete(environment_id=str(id), requester=requester)
        return True

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def create_environment_policy(self, info: Info, input: EntityPolicyCreateInput) -> list[PermissionType]:
        requester = info.context["request"].state.user

        if not await user_has_access_to_entity(requester, input.entity_id, "admin", "environment"):  # pyright: ignore
            raise AccessDenied("Access denied: admin access to environment required")

        service = get_environment_service(info.context["session"])
        return await service.create_environment_policy(
            environment_policy=input.to_pydantic(),
            requester=requester,
        )
