from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from application.environments.model import Environment
from application.projects.model import Project
from application.resources.model import Resource
from application.services.compiler import PlanAction
from application.services.model import Service
from application.services.schema import ServiceCreate, ServiceSpec, ServiceUpdate
from application.services.service import ServiceService
from core.audit_logs.handler import AuditLogHandler
from core.base_models import PatchBodyModel
from core.constants.model import ModelActions, ModelState, ModelStatus
from core.database import FieldSpec
from core.errors import DependencyError, EntityExistsError, EntityNotFound, EntityWrongState
from core.users.model import UserDTO
from core.utils.event_sender import EventSender

from .adoption import AdoptedResource, reverse_compile
from .crud import ServiceInstanceCRUD
from .deployments import BUSY, DeploymentService
from .functions import get_service_instance_actions
from .model import ServiceInstance, ServiceResourceRole
from .schema import AdoptResources, ApplyServiceMigration, ServiceInstanceCreate, ServiceInstanceResponse


def _inherited_names(resource: Resource) -> frozenset[str]:
    configs: list[Any] = []
    for parent in resource.parents or []:
        configs += parent.dependency_config or []
    project: Project | None = resource.project
    if project is not None:
        configs += getattr(project, "dependency_config", None) or []
    names = set()
    for config in configs:
        data = config if isinstance(config, dict) else getattr(config, "__dict__", {})
        if data.get("inherited_by_children") and data.get("name"):
            names.add(data["name"])
    return frozenset(names)


class ServiceInstanceService:
    def __init__(
        self,
        crud: ServiceInstanceCRUD,
        event_sender: EventSender,
        audit_log_handler: AuditLogHandler,
        service_service: ServiceService | None = None,
    ):
        self.crud: ServiceInstanceCRUD = crud
        self.event_sender: EventSender = event_sender
        self.audit_log_handler: AuditLogHandler = audit_log_handler
        self.service_service: ServiceService | None = service_service

    @property
    def services(self) -> ServiceService:
        if self.service_service is None:
            raise RuntimeError("ServiceInstanceService was built without a ServiceService")
        return self.service_service

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

    async def get_actions(self, service_instance_id: str | UUID, requester: UserDTO) -> list[str]:
        instance = await self.crud.get_by_id(service_instance_id)
        if not instance:
            raise EntityNotFound("Service instance not found")
        can_edit = ModelActions.EDIT in await self.services.get_actions(instance.service_id, requester)
        return get_service_instance_actions(
            can_edit=can_edit,
            state=instance.state,
            status=instance.status,
            owns_resources=any(link.role != ServiceResourceRole.REFERENCED for link in instance.resources),
        )

    async def send(self, instance: ServiceInstance, action: str) -> ServiceInstance:
        await self.crud.refresh(instance)
        await self.event_sender.send_event(ServiceInstanceResponse.model_validate(instance), action)
        return instance

    async def queue_run(self, instance: ServiceInstance, requester: UserDTO, approval_required: bool) -> None:
        if approval_required:
            instance.status = ModelStatus.APPROVAL_PENDING
            return
        instance.status = ModelStatus.QUEUED
        await self.event_sender.send_task(
            instance.id,
            requester=requester,
            action=ModelActions.EXECUTE,
            audit_log_id=self.audit_log_handler.audit_log_id,
        )

    async def patch_action(
        self, service_instance_id: str | UUID, body: PatchBodyModel, requester: UserDTO
    ) -> ServiceInstance:
        instance = await self.crud.get_for_update(service_instance_id)
        if not instance:
            raise EntityNotFound("Service instance not found")
        if body.action not in await self.get_actions(instance.id, requester):
            raise EntityWrongState(
                f"Action {body.action} is not allowed while the instance is {instance.state}/{instance.status}"
            )

        environment = await self.crud.session.get(Environment, instance.environment_id)
        approval_required = bool(environment and environment.approval_required)
        await self.audit_log_handler.create_log(instance.id, requester.id, body.action)

        match body.action:
            case ModelActions.EXECUTE:
                compiled = await self.services.compile(instance.service_id, instance.environment_id, requester)
                if compiled.plan.errors:
                    raise ValueError("Cannot deploy: " + "; ".join(compiled.plan.errors))
                if instance.state == ModelState.DESTROYED or instance.spec_revision_applied is None:
                    instance.state = ModelState.PROVISION
                instance.workflow_id = None
                await self.queue_run(instance, requester, approval_required)
            case ModelActions.DESTROY:
                instance.state = ModelState.DESTROY
                instance.workflow_id = None
                await self.queue_run(instance, requester, approval_required)
            case ModelActions.APPROVE:
                await self.queue_run(instance, requester, approval_required=False)
            case ModelActions.REJECT:
                applied = instance.spec_revision_applied is not None
                instance.state = ModelState.PROVISIONED if applied else ModelState.PROVISION
                instance.status = ModelStatus.DONE if applied else ModelStatus.READY
                await DeploymentService(self).cancel_active(instance, "Approval rejected", requester)
            case ModelActions.RETRY:
                await self.queue_run(instance, requester, approval_required=False)
            case _:
                raise ValueError(f"Action {body.action} is not supported")

        return await self.send(instance, body.action)

    async def adopt_resources(self, request: AdoptResources, requester: UserDTO) -> ServiceInstance:
        """
        Link existing resources to the service in one environment without provisioning anything, and fold the
        owned ones into the service spec so the next plan for this environment is a no-op.
        """
        instance = await self.crud.get_by_service_environment(request.service_id, request.environment_id)
        if instance is None:
            instance = await self.create_service_instance(
                ServiceInstanceCreate(
                    service_id=request.service_id,
                    environment_id=request.environment_id,
                    anchor_resource_id=request.anchor_resource_id,
                ),
                requester,
            )
        else:
            instance = await self.crud.get_for_update(instance.id) or instance
            if instance.status in BUSY:
                raise EntityWrongState("The service has a run in progress in this environment; adopt afterwards")
            if request.anchor_resource_id and instance.anchor_resource_id not in (None, request.anchor_resource_id):
                raise ValueError("The service already has a different anchor resource in this environment")
            if request.anchor_resource_id:
                instance.anchor_resource_id = request.anchor_resource_id

        items = request.resources
        aliases = [item.alias for item in items]
        duplicates = sorted({a for a in aliases if aliases.count(a) > 1})
        if duplicates:
            raise ValueError(f"Duplicate aliases: {', '.join(duplicates)}")
        resource_ids = [item.resource_id for item in items]
        if len(set(resource_ids)) != len(resource_ids):
            raise ValueError("The same resource is listed more than once")
        taken = {link.alias for link in instance.resources} & set(aliases)
        if taken:
            raise EntityExistsError(f"Aliases already used in this environment: {', '.join(sorted(taken))}")

        rows = await self.crud.session.execute(
            select(Resource)
            .where(Resource.id.in_(resource_ids))
            .options(selectinload(Resource.parents))
            .execution_options(populate_existing=True)
        )
        resources = {r.id: r for r in rows.scalars().unique()}
        missing = [str(rid) for rid in resource_ids if rid not in resources]
        if missing:
            raise EntityNotFound(f"Resources not found: {', '.join(missing)}")

        owners = await self.crud.owned_resource_ids(resource_ids)
        conflicts = []
        for item in items:
            resource = resources[item.resource_id]
            if resource.state in (ModelState.DESTROY, ModelState.DESTROYED):
                raise EntityWrongState(f"Resource {resource.name} is {resource.state} and cannot be adopted")
            if item.role == ServiceResourceRole.REFERENCED:
                continue
            if resource.abstract:
                raise ValueError(f"Resource {resource.name} is abstract; it can only be referenced or be the anchor")
            if item.resource_id in owners:
                conflicts.append({"id": str(resource.id), "name": resource.name, "entityName": "resource"})
        if conflicts:
            raise DependencyError(
                message=f"{len(conflicts)} resources are already owned by a service; reference them instead",
                metadata=conflicts,
            )

        await self.crud.add_links(instance.id, [(i.alias, i.resource_id, i.role) for i in items])
        await self.crud.refresh(instance)

        service = await self.services.crud.get_by_id(instance.service_id)
        if service is None:
            raise EntityNotFound("Service not found")
        old_spec = ServiceSpec.model_validate(service.spec or {})
        old_revision = service.spec_revision
        was_current = instance.spec_revision_applied == old_revision

        owned_items = [i for i in items if i.role != ServiceResourceRole.REFERENCED]
        if owned_items:
            alias_by_resource = {
                link.resource_id: link.alias
                for link in instance.resources
                if link.role != ServiceResourceRole.REFERENCED
            }
            adopted = [
                AdoptedResource(
                    alias=item.alias,
                    resource_id=item.resource_id,
                    template_key=resources[item.resource_id].template.template,
                    source_code_version_id=resources[item.resource_id].source_code_version_id,
                    variables=list(resources[item.resource_id].variables or []),
                    parent_ids=tuple(p.id for p in resources[item.resource_id].parents),
                    inherited_names=_inherited_names(resources[item.resource_id]),
                )
                for item in owned_items
            ]
            new_spec, errors = reverse_compile(old_spec, adopted, alias_by_resource)
            if errors:
                raise ValueError("; ".join(errors))
            if new_spec != old_spec:
                await self.services.update_service(str(service.id), ServiceUpdate(spec=new_spec), requester)
                await self.services.crud.refresh(service)

        if was_current or (
            instance.spec_revision_applied is None and await self._nothing_to_apply(service, instance, requester)
        ):
            instance.spec_revision_applied = service.spec_revision
            instance.state = ModelState.PROVISIONED
            instance.status = ModelStatus.DONE

        await self.audit_log_handler.create_log(instance.id, requester.id, ModelActions.ADOPT)
        return await self.send(instance, ModelActions.ADOPT)

    async def _nothing_to_apply(self, service: Service, instance: ServiceInstance, requester: UserDTO) -> bool:
        """The environment already matches the spec: every claim is a no-op and nothing else needs delivering."""
        spec = ServiceSpec.model_validate(service.spec or {})
        if spec.bindings or spec.managed_workload is not None:
            return False
        plan = (await self.services.compile(service.id, instance.environment_id, requester)).plan
        return not plan.errors and all(item.action == PlanAction.NO_OP for item in plan.items)

    async def apply_migration(self, request: ApplyServiceMigration, requester: UserDTO) -> Service:
        """Create (or reuse) the Service for an anchor and adopt the reviewed resources environment by environment."""
        existing = (
            await self.crud.session.execute(
                select(Service).where(Service.name == request.service_name, Service.project_id == request.project_id)
            )
        ).scalar_one_or_none()
        service = existing or await self.services.create_service(
            ServiceCreate(
                name=request.service_name,
                project_id=request.project_id,
                description="Created from existing resources of a service anchor",
                labels=["migrated"],
            ),
            requester,
        )
        for environment in request.environments:
            await self.adopt_resources(
                AdoptResources(
                    service_id=service.id,
                    environment_id=environment.environment_id,
                    anchor_resource_id=request.anchor_resource_id,
                    resources=environment.resources,
                ),
                requester,
            )
        return service
