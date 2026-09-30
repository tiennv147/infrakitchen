import uuid
from typing import Any, cast

import strawberry
from strawberry.scalars import JSON
from strawberry.types import Info

from application.environments.model import Environment
from application.service_instances.binding_delivery import BindingPreview
from application.service_instances.binding_delivery import preview as binding_preview
from application.service_instances.crud import ServiceInstanceCRUD
from application.service_instances.dependencies import get_service_instance_service
from application.service_instances.deployments import DeploymentService
from application.service_instances.migration import list_anchors, propose
from application.service_instances.model import ServiceInstance
from application.service_instances.service import ServiceInstanceService
from application.services.model import Service
from core.errors import AccessDenied, EntityNotFound
from core.users.functions import user_has_access_to_entity
from graphql_api.helpers import (
    IsAuthenticated,
    build_field_spec,
    check_api_permission,
    get_entity_selection,
    parse_range,
    parse_sort,
)
from graphql_api.modules.service_instance.types import (
    MigrationAnchorType,
    MigrationProposalType,
    ServiceBindingsType,
    ServiceDeploymentType,
    ServiceInstanceType,
)


def _build_service(info: Info) -> ServiceInstanceService:
    return get_service_instance_service(info.context["session"])


async def _binding_preview(info: Info, service_id: uuid.UUID, environment_id: uuid.UUID) -> tuple[BindingPreview, bool]:
    session = info.context["session"]
    service = await session.get(Service, service_id)
    environment = await session.get(Environment, environment_id)
    if service is None or environment is None:
        raise EntityNotFound("Service or environment not found")
    instance = await ServiceInstanceCRUD(session=session).get_by_service_environment(service_id, environment_id)
    placeholder = ServiceInstance(resources=[], binding_state=None)
    return binding_preview(instance or placeholder, service, environment), instance is not None


@strawberry.type
class ServiceInstanceQuery:
    @strawberry.field(permission_classes=[IsAuthenticated])
    async def service_instance(self, info: Info, id: uuid.UUID) -> ServiceInstanceType | None:
        await check_api_permission(info, "service", ["read"])
        fields = build_field_spec(get_entity_selection(info.selected_fields, "serviceInstance"))
        return await _build_service(info).query_by_id(id, fields=fields)

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def service_instances(
        self,
        info: Info,
        filter: JSON | None = None,
        sort: list[str] | None = None,
        range: list[int] | None = None,
    ) -> list[ServiceInstanceType]:
        await check_api_permission(info, "service", ["read"])
        fields = build_field_spec(get_entity_selection(info.selected_fields, "serviceInstances"))
        return await _build_service(info).query_all(
            filter=cast(dict[str, Any], cast(object, filter)) if filter else None,
            sort=parse_sort(sort),
            range=parse_range(range),
            fields=fields,
        )

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def service_instances_count(self, info: Info, filter: JSON | None = None) -> int:
        await check_api_permission(info, "service", ["read"])
        return await _build_service(info).count(
            filter=cast(dict[str, Any], cast(object, filter)) if filter else None,
        )

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def service_instance_actions(self, info: Info, id: uuid.UUID) -> list[str]:
        await check_api_permission(info, "service", ["read"])
        requester = info.context["request"].state.user
        return await _build_service(info).get_actions(id, requester)

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def service_bindings(
        self, info: Info, service_id: uuid.UUID, environment_id: uuid.UUID
    ) -> ServiceBindingsType:
        """Read-only preview of what the service's bindings resolve to in one environment."""
        await check_api_permission(info, "service", ["read"])
        preview, deployed = await _binding_preview(info, service_id, environment_id)
        return ServiceBindingsType.from_preview(preview, deployed)

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def service_build_bindings(self, info: Info, service_id: uuid.UUID, environment_id: uuid.UUID) -> JSON:
        """Build-scope bindings for CI, e.g. {"ECR_REPO": "..."}. Never contains sensitive outputs."""
        await check_api_permission(info, "service", ["read"])
        requester = info.context["request"].state.user
        if not await user_has_access_to_entity(requester, service_id, "read", "service"):
            raise AccessDenied("Access denied to this service's bindings")
        preview, _ = await _binding_preview(info, service_id, environment_id)
        build_errors = preview.rendered.errors_for("build")
        if build_errors:
            raise ValueError("; ".join(build_errors))
        return cast(JSON, cast(object, preview.rendered.payload("build")))

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def service_deployments(
        self, info: Info, service_id: uuid.UUID, environment_id: uuid.UUID | None = None, limit: int = 50
    ) -> list[ServiceDeploymentType]:
        """Workload deployment history, newest first."""
        await check_api_permission(info, "service", ["read"])
        deployments = DeploymentService(_build_service(info))
        rows = await deployments.history(service_id, environment_id, max(1, min(limit, 200)))
        return [ServiceDeploymentType.from_model(d) for d in rows]

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def service_migration_anchors(
        self, info: Info, project_id: uuid.UUID | None = None
    ) -> list[MigrationAnchorType]:
        await check_api_permission(info, "service", ["admin"])
        anchors = await list_anchors(info.context["session"], project_id)
        return [MigrationAnchorType(id=anchor_id, name=name) for anchor_id, name in anchors]

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def service_migration_preview(self, info: Info, anchor_resource_id: uuid.UUID) -> MigrationProposalType:
        """Read-only proposal of the Service, environments and ownership for one `service` anchor resource."""
        await check_api_permission(info, "service", ["admin"])
        return MigrationProposalType.from_proposal(await propose(info.context["session"], anchor_resource_id))
