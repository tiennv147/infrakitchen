from typing import Any
from uuid import UUID

from sqlalchemy import select

from application.environments.model import Environment
from application.resources.model import Resource
from application.services.model import Service
from core.audit_logs.handler import AuditLogHandler
from core.constants.model import ModelActions, ModelState, ModelStatus
from core.database import FieldSpec
from core.errors import DependencyError, EntityExistsError, EntityNotFound, EntityWrongState
from core.users.model import UserDTO
from core.utils.event_sender import EventSender

from .crud import ServiceInstanceCRUD
from .model import ServiceInstance, ServiceResourceRole
from .schema import ServiceInstanceCreate, ServiceInstanceResponse


class ServiceInstanceService:
    def __init__(
        self,
        crud: ServiceInstanceCRUD,
        event_sender: EventSender,
        audit_log_handler: AuditLogHandler,
    ):
        self.crud: ServiceInstanceCRUD = crud
        self.event_sender: EventSender = event_sender
        self.audit_log_handler: AuditLogHandler = audit_log_handler

    async def get_by_id(self, service_instance_id: str | UUID) -> ServiceInstanceResponse | None:
        instance = await self.crud.get_by_id(service_instance_id)
        if instance is None:
            return None
        return ServiceInstanceResponse.model_validate(instance)

    async def count(self, filter: dict[str, Any] | None = None) -> int:
        return await self.crud.count(filter=filter)

    async def query_by_id(
        self, service_instance_id: str | UUID, fields: FieldSpec | None = None
    ) -> ServiceInstance | None:
        return await self.crud.get_by_id(service_instance_id, fields=fields)

    async def query_all(
        self,
        filter: dict[str, Any] | None = None,
        range: tuple[int, int] | None = None,
        sort: tuple[str, str] | None = None,
        fields: FieldSpec | None = None,
    ) -> list[ServiceInstance]:
        return await self.crud.get_all(filter=filter, range=range, sort=sort, fields=fields)

    async def _scalar(self, statement: Any) -> Any:
        return (await self.crud.session.execute(statement)).scalar_one_or_none()

    async def create_service_instance(
        self, service_instance: ServiceInstanceCreate, requester: UserDTO
    ) -> ServiceInstance:
        if await self._scalar(select(Service.id).where(Service.id == service_instance.service_id)) is None:
            raise EntityNotFound(f"Service {service_instance.service_id} not found")

        environment_status = await self._scalar(
            select(Environment.status).where(Environment.id == service_instance.environment_id)
        )
        if environment_status is None:
            raise EntityNotFound(f"Environment {service_instance.environment_id} not found")
        if environment_status != ModelStatus.ENABLED:
            raise EntityWrongState("Environment is disabled and cannot receive new services")

        if service_instance.anchor_resource_id is not None:
            anchor = select(Resource.id).where(Resource.id == service_instance.anchor_resource_id)
            if await self._scalar(anchor) is None:
                raise EntityNotFound(f"Anchor resource {service_instance.anchor_resource_id} not found")

        existing = await self.crud.count(
            filter={
                "service_id": str(service_instance.service_id),
                "environment_id": str(service_instance.environment_id),
            }
        )
        if existing:
            raise EntityExistsError("Service is already deployed to this environment")

        body = service_instance.model_dump()
        body.update(created_by=requester.id, state=ModelState.PROVISION, status=ModelStatus.READY)

        new_instance = await self.crud.create(body)
        result = await self.crud.get_by_id(new_instance.id)
        if not result:
            raise EntityNotFound("Service instance not found after creation")

        await self.audit_log_handler.create_log(new_instance.id, requester.id, ModelActions.CREATE)
        await self.event_sender.send_event(ServiceInstanceResponse.model_validate(result), ModelActions.CREATE)
        return result

    async def delete(self, service_instance_id: str, requester: UserDTO) -> None:
        existing = await self.crud.get_by_id(service_instance_id)
        if not existing:
            raise EntityNotFound("Service instance not found")

        owned = [link for link in existing.resources if link.role != ServiceResourceRole.REFERENCED]
        if owned:
            raise DependencyError(
                message=f"Cannot remove environment, the service still owns {len(owned)} resources",
                metadata=[
                    {"id": str(link.resource_id), "name": link.alias, "entityName": "resource"} for link in owned
                ],
            )

        await self.audit_log_handler.create_log(service_instance_id, requester.id, ModelActions.DELETE)
        await self.crud.delete(existing)
