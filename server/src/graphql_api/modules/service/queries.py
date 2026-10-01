import uuid
from typing import Any, cast

import strawberry
from strawberry.scalars import JSON
from strawberry.types import Info

from application.environments.model import Environment
from application.services.graph import (
    GraphNode,
    dependency_tree,
    dependents_tree,
    load_topology,
    resource_impact_tree,
    resource_node,
)
from application.services.service import ServiceService
from application.services.dependencies import get_service_service
from core.errors import EntityNotFound
from graphql_api.helpers import (
    IsAuthenticated,
    build_field_spec,
    check_api_permission,
    get_entity_selection,
    parse_range,
    parse_sort,
)
from graphql_api.modules.service.types import ServiceGraphNodeType, ServicePlanType, ServiceType


def _graph(node: GraphNode) -> ServiceGraphNodeType:
    return ServiceGraphNodeType(
        id=node.id,
        node_id=node.node_id,
        name=node.name,
        entity_name=node.entity_name,
        relation=node.relation,
        state=node.state,
        status=node.status,
        template_name=node.template_name,
        children=[_graph(child) for child in node.children],
    )


def _build_service(info: Info) -> ServiceService:
    session = info.context["session"]
    return get_service_service(session)


@strawberry.type
class ServiceQuery:
    @strawberry.field(permission_classes=[IsAuthenticated])
    async def service(self, info: Info, id: uuid.UUID) -> ServiceType | None:
        await check_api_permission(info, "service", ["read"])
        service = _build_service(info)
        entity_fields = get_entity_selection(info.selected_fields, "service")
        fields = build_field_spec(entity_fields)
        return await service.query_by_id(id, fields=fields)

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def services(
        self,
        info: Info,
        filter: JSON | None = None,
        sort: list[str] | None = None,
        range: list[int] | None = None,
    ) -> list[ServiceType]:
        await check_api_permission(info, "service", ["read"])
        service = _build_service(info)
        entity_fields = get_entity_selection(info.selected_fields, "services")
        fields = build_field_spec(entity_fields)
        return await service.query_all(
            filter=cast(dict[str, Any], cast(object, filter)) if filter else None,
            sort=parse_sort(sort),
            range=parse_range(range),
            fields=fields,
        )

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def services_count(
        self,
        info: Info,
        filter: JSON | None = None,
    ) -> int:
        await check_api_permission(info, "service", ["read"])
        service = _build_service(info)
        return await service.count(
            filter=cast(dict[str, Any], cast(object, filter)) if filter else None,
        )

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def service_actions(self, info: Info, id: uuid.UUID) -> list[str]:
        await check_api_permission(info, "service", ["read"])
        service = _build_service(info)
        requester = info.context["request"].state.user
        return await service.get_actions(service_id=id, requester=requester)

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def service_plan(self, info: Info, service_id: uuid.UUID, environment_id: uuid.UUID) -> ServicePlanType:
        """Dry run: what applying the service spec to this environment would create, update or destroy."""
        await check_api_permission(info, "service", ["read"])
        service = _build_service(info)
        requester = info.context["request"].state.user
        return ServicePlanType.from_plan(await service.plan(service_id, environment_id, requester))

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def service_graph(
        self,
        info: Info,
        id: uuid.UUID,
        direction: str = "dependencies",
        environment_id: uuid.UUID | None = None,
    ) -> ServiceGraphNodeType:
        """dependencies: services this one depends on and the resources each uses (owned or referenced).
        dependents: every service that depends on this one, i.e. what a change here can break."""
        await check_api_permission(info, "service", ["read"])
        if direction not in ("dependencies", "dependents"):
            raise ValueError("direction must be 'dependencies' or 'dependents'")
        session = info.context["session"]
        topology = await load_topology(session)
        if id not in topology.services:
            raise EntityNotFound("Service not found")
        if direction == "dependents":
            return _graph(dependents_tree(topology, id))
        environment = await session.get(Environment, environment_id) if environment_id else None
        if environment_id and environment is None:
            raise EntityNotFound("Environment not found")
        return _graph(dependency_tree(topology, id, environment.name if environment else None))

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def resource_impact(self, info: Info, id: uuid.UUID) -> ServiceGraphNodeType:
        """Services that own or reference a resource, and the services depending on them."""
        await check_api_permission(info, "service", ["read"])
        session = info.context["session"]
        root = await resource_node(session, id)
        if root is None:
            raise EntityNotFound("Resource not found")
        return _graph(resource_impact_tree(await load_topology(session), root))
