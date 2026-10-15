import uuid
from typing import Any, cast

import strawberry
from strawberry.scalars import JSON
from strawberry.types import Info

from application.environments.dependencies import get_environment_service
from application.environments.service import EnvironmentService
from graphql_api.helpers import (
    IsAuthenticated,
    build_field_spec,
    check_api_permission,
    get_entity_selection,
    parse_range,
    parse_sort,
)
from graphql_api.modules.environment.types import EnvironmentType


def _build_service(info: Info) -> EnvironmentService:
    return get_environment_service(info.context["session"])


@strawberry.type
class EnvironmentQuery:
    @strawberry.field(permission_classes=[IsAuthenticated])
    async def environment(self, info: Info, id: uuid.UUID) -> EnvironmentType | None:
        await check_api_permission(info, "environment", ["read"])
        fields = build_field_spec(get_entity_selection(info.selected_fields, "environment"))
        return await _build_service(info).query_by_id(id, fields=fields)

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def environments(
        self,
        info: Info,
        filter: JSON | None = None,
        sort: list[str] | None = None,
        range: list[int] | None = None,
    ) -> list[EnvironmentType]:
        await check_api_permission(info, "environment", ["read"])
        fields = build_field_spec(get_entity_selection(info.selected_fields, "environments"))
        return await _build_service(info).query_all(
            filter=cast(dict[str, Any], cast(object, filter)) if filter else None,
            sort=parse_sort(sort),
            range=parse_range(range),
            fields=fields,
        )

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def environments_count(self, info: Info, filter: JSON | None = None) -> int:
        await check_api_permission(info, "environment", ["read"])
        return await _build_service(info).count(
            filter=cast(dict[str, Any], cast(object, filter)) if filter else None,
        )

    @strawberry.field(permission_classes=[IsAuthenticated])
    async def environment_actions(self, info: Info, id: uuid.UUID) -> list[str]:
        await check_api_permission(info, "environment", ["read"])
        requester = info.context["request"].state.user
        return await _build_service(info).get_actions(environment_id=id, requester=requester)
