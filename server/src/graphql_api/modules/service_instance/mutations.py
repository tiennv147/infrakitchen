import uuid

import strawberry
from strawberry.experimental import pydantic as strawberry_pydantic
from strawberry.types import Info

from application.service_instances.dependencies import get_service_instance_service
from application.service_instances.schema import ServiceInstanceCreate
from application.services.dependencies import get_service_service
from core.constants.model import ModelActions
from core.errors import AccessDenied, EntityNotFound
from core.users.model import UserDTO
from graphql_api.helpers import IsAuthenticated
from graphql_api.modules.service_instance.types import ServiceInstanceType


@strawberry_pydantic.input(model=ServiceInstanceCreate, all_fields=True)
class ServiceInstanceCreateInput:
    service_id: uuid.UUID = strawberry.UNSET
    environment_id: uuid.UUID = strawberry.UNSET
    anchor_resource_id: uuid.UUID | None = None


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
