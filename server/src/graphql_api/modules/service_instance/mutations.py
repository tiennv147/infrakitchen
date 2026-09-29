import uuid

import strawberry
from strawberry.experimental import pydantic as strawberry_pydantic
from strawberry.types import Info

from application.service_instances.dependencies import get_service_instance_service
from application.service_instances.model import ServiceResourceRole
from application.service_instances.schema import (
    AdoptResourceItem,
    AdoptResources,
    ApplyServiceMigration,
    MigrationEnvironment,
    ServiceInstanceCreate,
)
from application.services.dependencies import get_service_service
from core.base_models import PatchBodyModel
from core.constants.model import ModelActions
from core.errors import AccessDenied, EntityNotFound
from core.users.model import UserDTO
from graphql_api.helpers import IsAuthenticated, check_api_permission
from graphql_api.modules.service.types import ServiceType
from graphql_api.modules.service_instance.types import ServiceInstanceType


@strawberry_pydantic.input(model=ServiceInstanceCreate, all_fields=True)
class ServiceInstanceCreateInput:
    service_id: uuid.UUID = strawberry.UNSET
    environment_id: uuid.UUID = strawberry.UNSET
    anchor_resource_id: uuid.UUID | None = None


@strawberry.input
class ServiceInstanceActionInput:
    action: str


@strawberry.input
class AdoptResourceInput:
    alias: str
    resource_id: uuid.UUID
    role: str = ServiceResourceRole.DEPENDENCY.value


@strawberry.input
class AdoptResourcesInput:
    service_id: uuid.UUID
    environment_id: uuid.UUID
    resources: list[AdoptResourceInput]
    anchor_resource_id: uuid.UUID | None = None


@strawberry.input
class MigrationEnvironmentInput:
    environment_id: uuid.UUID
    resources: list[AdoptResourceInput]


@strawberry.input
class ApplyServiceMigrationInput:
    anchor_resource_id: uuid.UUID
    project_id: uuid.UUID
    service_name: str
    environments: list[MigrationEnvironmentInput]


def _items(resources: list[AdoptResourceInput]) -> list[AdoptResourceItem]:
    return [
        AdoptResourceItem(alias=r.alias, resource_id=r.resource_id, role=ServiceResourceRole(r.role)) for r in resources
    ]


async def _assert_can_edit_service(info: Info, service_id: uuid.UUID, requester: UserDTO) -> None:
    """Deploying a service is an edit of that service, so its owners and admins control it."""
    service = get_service_service(info.context["session"])
    if ModelActions.EDIT not in await service.get_actions(service_id=service_id, requester=requester):
        raise AccessDenied(f"Access denied for action {ModelActions.EDIT.value}")


@strawberry.type
class ServiceInstanceMutation:
    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def create_service_instance(self, info: Info, input: ServiceInstanceCreateInput) -> ServiceInstanceType:
        requester = info.context["request"].state.user
        body = input.to_pydantic()
        await _assert_can_edit_service(info, body.service_id, requester)

        service = get_service_instance_service(info.context["session"])
        return await service.create_service_instance(service_instance=body, requester=requester)

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def delete_service_instance(self, info: Info, id: uuid.UUID) -> bool:
        requester = info.context["request"].state.user
        service = get_service_instance_service(info.context["session"])

        instance = await service.query_by_id(id, fields={"id": None, "service_id": None})
        if not instance:
            raise EntityNotFound("Service instance not found")
        await _assert_can_edit_service(info, instance.service_id, requester)

        await service.delete(service_instance_id=str(id), requester=requester)
        return True

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def service_instance_action(
        self, info: Info, id: uuid.UUID, input: ServiceInstanceActionInput
    ) -> ServiceInstanceType:
        """Deploy/reconcile (execute), destroy, approve, reject or retry a service in one environment."""
        requester = info.context["request"].state.user
        service = get_service_instance_service(info.context["session"])
        return await service.patch_action(id, PatchBodyModel(action=input.action), requester)

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def adopt_resources(self, info: Info, input: AdoptResourcesInput) -> ServiceInstanceType:
        """Link existing resources to a service in one environment; provisions nothing."""
        requester = info.context["request"].state.user
        await _assert_can_edit_service(info, input.service_id, requester)
        service = get_service_instance_service(info.context["session"])
        return await service.adopt_resources(
            AdoptResources(
                service_id=input.service_id,
                environment_id=input.environment_id,
                anchor_resource_id=input.anchor_resource_id,
                resources=_items(input.resources),
            ),
            requester,
        )

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    async def apply_service_migration(self, info: Info, input: ApplyServiceMigrationInput) -> ServiceType:
        """Create the Service for a `service` anchor and adopt the operator-reviewed resources."""
        await check_api_permission(info, "service", ["admin"])
        requester = info.context["request"].state.user
        service = get_service_instance_service(info.context["session"])
        return await service.apply_migration(
            ApplyServiceMigration(
                anchor_resource_id=input.anchor_resource_id,
                project_id=input.project_id,
                service_name=input.service_name,
                environments=[
                    MigrationEnvironment(environment_id=e.environment_id, resources=_items(e.resources))
                    for e in input.environments
                ],
            ),
            requester,
        )
