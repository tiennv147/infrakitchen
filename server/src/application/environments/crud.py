from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from application.integrations.model import Integration
from application.resources.model import Resource
from core.database import (
    FieldSpec,
    evaluate_sqlalchemy_filters,
    evaluate_sqlalchemy_pagination,
    evaluate_sqlalchemy_sorting,
)
from core.errors import EntityNotFound
from core.utils.model_tools import is_valid_uuid

from .model import Environment
from .query_options import build_environment_query_options

_COLLECTIONS: dict[str, type[Integration] | type[Resource]] = {
    "integration_ids": Integration,
    "parent_resources": Resource,
}


class EnvironmentCRUD:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def get_by_id(
        self,
        environment_id: str | UUID,
        fields: FieldSpec | None = None,
    ) -> Environment | None:
        if not is_valid_uuid(environment_id):
            raise ValueError(f"Invalid UUID: {environment_id}")

        statement = select(Environment).where(Environment.id == environment_id)
        statement = statement.options(*build_environment_query_options(fields))
        result = await self.session.execute(statement)
        return result.scalars().unique().first()

    async def get_all(
        self,
        filter: dict[str, Any] | None = None,
        range: tuple[int, int] | None = None,
        sort: tuple[str, str] | None = None,
        fields: FieldSpec | None = None,
    ) -> list[Environment]:
        statement = select(Environment)
        statement = evaluate_sqlalchemy_filters(Environment, statement, filter)
        statement = evaluate_sqlalchemy_sorting(Environment, statement, sort)
        statement = evaluate_sqlalchemy_pagination(statement, range)

        statement = statement.options(*build_environment_query_options(fields))
        result = await self.session.execute(statement)
        return list(result.scalars().unique().all())

    async def count(self, filter: dict[str, Any] | None = None) -> int:
        statement = select(func.count()).select_from(Environment)
        statement = evaluate_sqlalchemy_filters(Environment, statement, filter)

        result = await self.session.execute(statement)
        return result.scalar_one() or 0

    async def _resolve(self, key: str, ids: list[Any]) -> list[Any]:
        model = _COLLECTIONS[key]
        result = await self.session.execute(select(model).where(model.id.in_(ids)))
        objects = list(result.scalars().all())
        found = {str(obj.id) for obj in objects}
        missing = {str(i) for i in ids} - found
        if missing:
            raise EntityNotFound(f"{model.__name__} not found: {', '.join(sorted(missing))}")
        return objects

    async def create(self, body: dict[str, Any]) -> Environment:
        collections = {key: body.pop(key, []) for key in _COLLECTIONS}
        db_environment = Environment(**body)

        for key, ids in collections.items():
            if ids:
                setattr(db_environment, key, await self._resolve(key, ids))

        self.session.add(db_environment)
        await self.session.flush()
        return db_environment

    async def update(self, existing: Environment, body: dict[str, Any]) -> Environment:
        for key, value in body.items():
            if key not in _COLLECTIONS and hasattr(existing, key):
                setattr(existing, key, value)

        for key in _COLLECTIONS:
            if key not in body:
                continue
            ids = body[key]
            setattr(existing, key, await self._resolve(key, ids) if ids else [])

        return existing

    async def delete(self, environment: Environment) -> None:
        await self.session.delete(environment)

    async def refresh(self, environment: Environment) -> None:
        await self.session.flush()
        await self.session.refresh(environment)
