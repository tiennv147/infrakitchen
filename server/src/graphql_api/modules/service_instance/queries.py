import uuid
from typing import Any, cast

import strawberry
from strawberry.scalars import JSON
from strawberry.types import Info

from application.service_instances.dependencies import get_service_instance_service
from application.service_instances.service import ServiceInstanceService
from graphql_api.helpers import (
    IsAuthenticated,
    build_field_spec,
    check_api_permission,
    get_entity_selection,
    parse_range,
    parse_sort,
)
from graphql_api.modules.service_instance.types import ServiceInstanceType


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
