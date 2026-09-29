import uuid
from typing import Any, cast

import strawberry
from strawberry.scalars import JSON
from strawberry.types import Info

from application.service_instances.dependencies import get_service_instance_service
from application.service_instances.migration import list_anchors, propose
from application.service_instances.service import ServiceInstanceService
from graphql_api.helpers import (
    IsAuthenticated,
    build_field_spec,
    check_api_permission,
    get_entity_selection,
    parse_range,
    parse_sort,
)
from graphql_api.modules.service_instance.types import MigrationAnchorType, MigrationProposalType, ServiceInstanceType


def _build_service(info: Info) -> ServiceInstanceService:
    return get_service_instance_service(info.context["session"])


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
