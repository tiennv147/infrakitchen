from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    FieldSpec,
    evaluate_sqlalchemy_filters,
    evaluate_sqlalchemy_pagination,
    evaluate_sqlalchemy_sorting,
)
from core.utils.model_tools import is_valid_uuid

from .model import ServiceInstance
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
