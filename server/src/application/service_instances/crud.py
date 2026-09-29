from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    FieldSpec,
    evaluate_sqlalchemy_filters,
    evaluate_sqlalchemy_pagination,
    evaluate_sqlalchemy_sorting,
)
from core.utils.model_tools import is_valid_uuid

from .model import ServiceInstance, ServiceInstanceResource, ServiceResourceRole
from .query_options import build_service_instance_query_options


class ServiceInstanceCRUD:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def get_by_id(
        self,
        service_instance_id: str | UUID,
        fields: FieldSpec | None = None,
    ) -> ServiceInstance | None:
        if not is_valid_uuid(service_instance_id):
            raise ValueError(f"Invalid UUID: {service_instance_id}")

        statement = select(ServiceInstance).where(ServiceInstance.id == service_instance_id)
        statement = statement.options(*build_service_instance_query_options(fields))
        result = await self.session.execute(statement)
        return result.scalars().unique().first()

    async def get_for_update(self, service_instance_id: str | UUID) -> ServiceInstance | None:
        """Lock the instance row so concurrent lifecycle actions on it are serialised."""
        statement = (
            select(ServiceInstance)
            .where(ServiceInstance.id == service_instance_id)
            .with_for_update(of=ServiceInstance)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(statement)
        return result.scalars().unique().first()

    async def get_by_service_environment(
        self, service_id: str | UUID, environment_id: str | UUID
    ) -> ServiceInstance | None:
        statement = select(ServiceInstance).where(
            ServiceInstance.service_id == service_id, ServiceInstance.environment_id == environment_id
        )
        result = await self.session.execute(statement.execution_options(populate_existing=True))
        return result.scalars().unique().first()

    async def owned_resource_ids(self, resource_ids: list[UUID]) -> dict[UUID, UUID]:
        """resource_id -> owning service_instance_id, for resources owned (not merely referenced) anywhere."""
        if not resource_ids:
            return {}
        rows = await self.session.execute(
            select(ServiceInstanceResource.resource_id, ServiceInstanceResource.service_instance_id).where(
                ServiceInstanceResource.resource_id.in_(resource_ids),
                ServiceInstanceResource.role != ServiceResourceRole.REFERENCED,
            )
        )
        return {row.resource_id: row.service_instance_id for row in rows}

    async def add_links(self, service_instance_id: UUID, links: list[tuple[str, UUID, str]]) -> None:
        for alias, resource_id, role in links:
            self.session.add(
                ServiceInstanceResource(
                    service_instance_id=service_instance_id, alias=alias, resource_id=resource_id, role=role
                )
            )
        await self.session.flush()

    async def remove_links(self, link_ids: list[UUID]) -> None:
        if link_ids:
            await self.session.execute(delete(ServiceInstanceResource).where(ServiceInstanceResource.id.in_(link_ids)))
            await self.session.flush()

    async def refresh(self, service_instance: ServiceInstance) -> None:
        await self.session.flush()
        await self.session.refresh(service_instance)

    async def get_all(
        self,
        filter: dict[str, Any] | None = None,
        range: tuple[int, int] | None = None,
        sort: tuple[str, str] | None = None,
        fields: FieldSpec | None = None,
    ) -> list[ServiceInstance]:
        statement = select(ServiceInstance)
        statement = evaluate_sqlalchemy_filters(ServiceInstance, statement, filter)
        statement = evaluate_sqlalchemy_sorting(ServiceInstance, statement, sort)
        statement = evaluate_sqlalchemy_pagination(statement, range)

        statement = statement.options(*build_service_instance_query_options(fields))
        result = await self.session.execute(statement)
        return list(result.scalars().unique().all())

    async def count(self, filter: dict[str, Any] | None = None) -> int:
        statement = select(func.count()).select_from(ServiceInstance)
        statement = evaluate_sqlalchemy_filters(ServiceInstance, statement, filter)

        result = await self.session.execute(statement)
        return result.scalar_one() or 0

    async def create(self, body: dict[str, Any]) -> ServiceInstance:
        db_instance = ServiceInstance(**body)
        self.session.add(db_instance)
        await self.session.flush()
        return db_instance

    async def delete(self, service_instance: ServiceInstance) -> None:
        await self.session.delete(service_instance)
