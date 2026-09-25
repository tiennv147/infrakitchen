import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select

from application.projects.model import Project
from application.service_instances.model import ServiceInstance
from application.services.model import Service
from core.audit_logs.handler import AuditLogHandler
from core.base_models import PatchBodyModel
from core.constants.model import ModelActions, ModelStatus
from core.database import FieldSpec, to_dict
from core.errors import DependencyError, EntityNotFound, EntityWrongState
from core.permissions.model import Permission
from core.permissions.schema import EntityPolicyCreate
from core.permissions.service import PermissionService
from core.revisions.handler import RevisionHandler
from core.users.model import UserDTO
from core.utils.event_sender import EventSender
from core.utils.model_tools import model_db_dump, to_json_serializable

from .crud import EnvironmentCRUD
from .functions import get_environment_actions
from .model import Environment
from .schema import EnvironmentCreate, EnvironmentResponse, EnvironmentUpdate

logger = logging.getLogger(__name__)

_COLLECTION_FIELDS = ("integration_ids", "parent_resources")


def _has_changes(body: dict[str, Any], existing: Environment) -> bool:
    for key, new_value in body.items():
        current = getattr(existing, key)
        if key in _COLLECTION_FIELDS:
            if sorted(str(v) for v in new_value) != sorted(str(obj.id) for obj in current):
                return True
        elif new_value != current:
            return True
    return False


class EnvironmentService:
    def __init__(
        self,
        crud: EnvironmentCRUD,
        permission_service: PermissionService,
        revision_handler: RevisionHandler,
        event_sender: EventSender,
        audit_log_handler: AuditLogHandler,
    ):
        self.crud: EnvironmentCRUD = crud
        self.permission_service: PermissionService = permission_service
        self.revision_handler: RevisionHandler = revision_handler
        self.event_sender: EventSender = event_sender
        self.audit_log_handler: AuditLogHandler = audit_log_handler

    async def get_by_id(self, environment_id: str | UUID) -> EnvironmentResponse | None:
        environment = await self.crud.get_by_id(environment_id)
        if environment is None:
            return None
        return EnvironmentResponse.model_validate(environment)

    async def get_all(self, **kwargs) -> list[EnvironmentResponse]:
        environments = await self.crud.get_all(**kwargs)
        return [EnvironmentResponse.model_validate(environment) for environment in environments]

    async def count(self, filter: dict[str, Any] | None = None) -> int:
        return await self.crud.count(filter=filter)

    async def query_by_id(self, environment_id: str | UUID, fields: FieldSpec | None = None) -> Environment | None:
        return await self.crud.get_by_id(environment_id, fields=fields)

    async def query_all(
        self,
        filter: dict[str, Any] | None = None,
        range: tuple[int, int] | None = None,
        sort: tuple[str, str] | None = None,
        fields: FieldSpec | None = None,
    ) -> list[Environment]:
        return await self.crud.get_all(filter=filter, range=range, sort=sort, fields=fields)

    async def _assert_project_exists(self, project_id: str | UUID) -> None:
        project = (
            await self.crud.session.execute(select(Project.id).where(Project.id == project_id))
        ).scalar_one_or_none()
        if project is None:
            raise EntityNotFound(f"Project {project_id} not found")

    async def create_environment(self, environment: EnvironmentCreate, requester: UserDTO) -> Environment:
        if environment.project_id:
            await self._assert_project_exists(environment.project_id)

        body = to_json_serializable(environment.model_dump(exclude_unset=True))
        body["created_by"] = requester.id

        new_environment = await self.crud.create(body)
        result = await self.crud.get_by_id(new_environment.id)
        if not result:
            raise EntityNotFound("Environment not found after creation")

        await self.revision_handler.handle_revision(new_environment)
        await self.audit_log_handler.create_log(
            new_environment.id, requester.id, ModelActions.CREATE, revision_number=new_environment.revision_number
        )
        await self.event_sender.send_event(EnvironmentResponse.model_validate(result), ModelActions.CREATE)
        return result

    async def update_environment(
        self, environment_id: str, environment: EnvironmentUpdate, requester: UserDTO
    ) -> Environment:
        existing = await self.crud.get_by_id(environment_id)
        if not existing:
            raise EntityNotFound("Environment not found")

        body = model_db_dump(environment, exclude_defaults=True, exclude_none=True)
        if not _has_changes(body, existing):
            raise ValueError("No changes detected; the environment is already up to date.")

        if body.get("project_id"):
            await self._assert_project_exists(body["project_id"])

        self.revision_handler.original_entity_instance_dump = to_dict(existing)
        await self.crud.update(existing, body)

        await self.revision_handler.handle_revision(existing)
        await self.audit_log_handler.create_log(
            existing.id, requester.id, ModelActions.UPDATE, revision_number=existing.revision_number
        )
        await self.crud.refresh(existing)
        await self.event_sender.send_event(EnvironmentResponse.model_validate(existing), ModelActions.UPDATE)
        return existing

    async def delete(self, environment_id: str, requester: UserDTO) -> None:
        existing = await self.crud.get_by_id(environment_id)
        if not existing:
            raise EntityNotFound("Environment not found")

        if existing.status == ModelStatus.ENABLED:
            raise EntityWrongState("Environment must be disabled before deletion")

        deployed = list(
            (
                await self.crud.session.execute(
                    select(Service.id, Service.name)
                    .join(ServiceInstance, ServiceInstance.service_id == Service.id)
                    .where(ServiceInstance.environment_id == existing.id)
                )
            ).all()
        )
        if deployed:
            raise DependencyError(
                message=f"Cannot delete environment, {len(deployed)} services are deployed to it",
                metadata=[
                    {"id": str(service_id), "name": service_name, "entityName": "service"}
                    for service_id, service_name in deployed
                ],
            )

        await self.audit_log_handler.create_log(environment_id, requester.id, ModelActions.DELETE)
        await self.revision_handler.delete_revisions(environment_id)
        await self.crud.delete(existing)

    async def patch_action(self, environment_id: str, body: PatchBodyModel, requester: UserDTO) -> Environment:
        existing = await self.crud.get_by_id(environment_id)
        if not existing:
            raise EntityNotFound("Environment not found")

        match body.action:
            case ModelActions.DISABLE:
                if existing.status == ModelStatus.DISABLED:
                    raise EntityWrongState("Environment is already disabled")
                existing.status = ModelStatus.DISABLED
            case ModelActions.ENABLE:
                if existing.status == ModelStatus.ENABLED:
                    raise EntityWrongState("Environment is already enabled")
                existing.status = ModelStatus.ENABLED
            case _:
                raise ValueError("Invalid action")

        await self.audit_log_handler.create_log(
            existing.id, requester.id, body.action, revision_number=existing.revision_number
        )
        await self.event_sender.send_event(EnvironmentResponse.model_validate(existing), body.action)
        return existing

    async def get_actions(self, environment_id: str | UUID, requester: UserDTO) -> list[str]:
        environment = await self.crud.get_by_id(environment_id, fields={"id": None, "status": None})
        if not environment:
            raise EntityNotFound("Environment not found")
        return await get_environment_actions(requester, environment_id, environment.status)

    async def create_environment_policy(
        self,
        environment_policy: EntityPolicyCreate,
        requester: UserDTO,
    ) -> list[Permission]:
        if not await self.crud.get_by_id(environment_policy.entity_id, fields={"id": None}):
            raise EntityNotFound(f"Environment {environment_policy.entity_id} not found")

        policy = await self.permission_service.create_entity_policy(
            environment_policy,
            requester,
            reload_permission=False,
        )
        await self.permission_service.casbin_enforcer.send_reload_event()
        return [policy]
