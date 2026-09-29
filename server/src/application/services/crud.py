from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from application.environments.model import Environment
from application.resources.model import Resource
from application.service_instances.model import ServiceInstance, ServiceInstanceResource
from application.source_code_versions.model import SourceCodeVersion
from application.templates.model import Template
from core.constants.model import ModelStatus, VersionLifecycleState
from core.database import (
    FieldSpec,
    evaluate_sqlalchemy_filters,
    evaluate_sqlalchemy_pagination,
    evaluate_sqlalchemy_sorting,
)
from core.users.model import User
from core.utils.model_tools import is_valid_uuid

from .compiler import Catalog, CatalogTemplate, CatalogVersion, EnvironmentTarget, OwnedResource, PlacedResource
from .model import Service
from .query_options import build_service_query_options
from .schema import ServiceSpec


class ServiceCRUD:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def get_by_id(
        self,
        service_id: str | UUID,
        fields: FieldSpec | None = None,
    ) -> Service | None:
        if not is_valid_uuid(service_id):
            raise ValueError(f"Invalid UUID: {service_id}")

        statement = select(Service).where(Service.id == service_id)
        statement = statement.options(*build_service_query_options(fields))
        result = await self.session.execute(statement)
        return result.scalars().unique().first()

    async def get_all(
        self,
        filter: dict[str, Any] | None = None,
        range: tuple[int, int] | None = None,
        sort: tuple[str, str] | None = None,
        fields: FieldSpec | None = None,
    ) -> list[Service]:
        statement = select(Service)
        statement = evaluate_sqlalchemy_filters(Service, statement, filter)
        statement = evaluate_sqlalchemy_sorting(Service, statement, sort)
        statement = evaluate_sqlalchemy_pagination(statement, range)

        statement = statement.options(*build_service_query_options(fields))
        result = await self.session.execute(statement)
        return list(result.scalars().unique().all())

    async def count(self, filter: dict[str, Any] | None = None) -> int:
        statement = select(func.count()).select_from(Service)
        statement = evaluate_sqlalchemy_filters(Service, statement, filter)

        result = await self.session.execute(statement)
        return result.scalar_one() or 0

    async def _resolve_users(self, user_ids: list[Any]) -> list[User]:
        result = await self.session.execute(select(User).where(User.id.in_(user_ids)))
        users = list(result.scalars().all())
        if len(users) != len(set(str(user_id) for user_id in user_ids)):
            raise ValueError("Some owner ids were not found")
        return users

    async def _resolve_services(self, service_ids: list[Any], self_id: UUID | None = None) -> list[Service]:
        wanted = {str(service_id) for service_id in service_ids}
        if self_id is not None and str(self_id) in wanted:
            raise ValueError("A service cannot depend on itself")
        result = await self.session.execute(select(Service).where(Service.id.in_(wanted)))
        services = list(result.scalars().unique().all())
        if len(services) != len(wanted):
            raise ValueError("Some depends_on service ids were not found")
        return services

    async def create(self, body: dict[str, Any]) -> Service:
        owner_ids = body.pop("owners", [])
        depends_on_ids = body.pop("depends_on", [])
        db_service = Service(**body)

        if owner_ids:
            db_service.owners = await self._resolve_users(owner_ids)
        if depends_on_ids:
            db_service.depends_on = await self._resolve_services(depends_on_ids)

        self.session.add(db_service)
        await self.session.flush()
        return db_service

    async def update(self, existing_service: Service, body: dict[str, Any]) -> Service:
        for key, value in body.items():
            if key not in ("owners", "depends_on") and hasattr(existing_service, key):
                setattr(existing_service, key, value)

        if body.get("owners") == []:
            existing_service.owners = []
        elif body.get("owners"):
            existing_service.owners = await self._resolve_users(body.pop("owners"))

        if "depends_on" in body:
            # Load the current links so replacement diffs instead of re-inserting existing ones.
            await self.session.refresh(existing_service, ["depends_on"])
            ids = body["depends_on"]
            existing_service.depends_on = await self._resolve_services(ids, self_id=existing_service.id) if ids else []

        return existing_service

    async def delete(self, service: Service) -> None:
        await self.session.delete(service)

    async def refresh(self, service: Service) -> None:
        await self.session.refresh(service)

    async def load_catalog(self, spec: ServiceSpec) -> Catalog:
        keys = {claim.template for claim in spec.claims}
        if not keys:
            return Catalog(templates_by_key={})
        templates = list(
            (
                await self.session.execute(
                    select(Template)
                    .where(Template.template.in_(keys))
                    .options(selectinload(Template.parents))
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        )
        by_key = {
            t.template: CatalogTemplate(
                id=t.id,
                key=t.template,
                name=t.name,
                enabled=t.status == ModelStatus.ENABLED,
                abstract=t.abstract,
                claimable=bool((t.configuration or {}).get("claimable")),
                naming_convention=(t.configuration or {}).get("naming_convention"),
                parent_template_ids=tuple(p.id for p in t.parents),
            )
            for t in templates
        }

        pinned = {claim.source_code_version_id for claim in spec.claims if claim.source_code_version_id}
        versions: dict[UUID, CatalogVersion] = {}
        if pinned:
            rows = await self.session.execute(
                select(SourceCodeVersion.id, SourceCodeVersion.template_id, SourceCodeVersion.status).where(
                    SourceCodeVersion.id.in_(pinned)
                )
            )
            versions = {
                row.id: CatalogVersion(
                    id=row.id, template_id=row.template_id, enabled=row.status != ModelStatus.DISABLED
                )
                for row in rows
            }

        latest: dict[UUID, UUID] = {}
        rows = await self.session.execute(
            select(SourceCodeVersion.id, SourceCodeVersion.template_id)
            .where(
                SourceCodeVersion.template_id.in_([t.id for t in by_key.values()]),
                SourceCodeVersion.lifecycle_state == VersionLifecycleState.ACTIVE,
                SourceCodeVersion.status != ModelStatus.DISABLED,
            )
            .order_by(SourceCodeVersion.index.desc(), SourceCodeVersion.created_at.desc())
        )
        for row in rows:
            latest.setdefault(row.template_id, row.id)

        return Catalog(
            templates_by_key=by_key,
            versions=versions,
            latest_version_by_template=latest,
            template_key_by_id={p.id: p.template for t in templates for p in t.parents}
            | {t.id: t.template for t in templates},
        )

    async def load_environment_target(self, environment_id: UUID | str) -> EnvironmentTarget | None:
        environment = (
            await self.session.execute(
                select(Environment)
                .where(Environment.id == environment_id)
                .options(selectinload(Environment.integration_ids), selectinload(Environment.parent_resources))
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if environment is None:
            return None
        return EnvironmentTarget(
            id=environment.id,
            name=environment.name,
            integration_ids=tuple(i.id for i in environment.integration_ids),
            storage_id=environment.storage_id,
            storage_path_prefix=environment.storage_path_prefix,
            workspace_id=environment.workspace_id,
            landing_zone=tuple(
                PlacedResource(id=r.id, template_id=r.template_id, name=r.name) for r in environment.parent_resources
            ),
        )

    async def load_instance(
        self, service_id: UUID | str, environment_id: UUID | str
    ) -> tuple[UUID | None, PlacedResource | None, list[OwnedResource]]:
        instance = (
            (
                await self.session.execute(
                    select(ServiceInstance)
                    .where(ServiceInstance.service_id == service_id, ServiceInstance.environment_id == environment_id)
                    .options(
                        joinedload(ServiceInstance.anchor_resource),
                        selectinload(ServiceInstance.resources)
                        .joinedload(ServiceInstanceResource.resource)
                        .selectinload(Resource.parents),
                        selectinload(ServiceInstance.resources)
                        .joinedload(ServiceInstanceResource.resource)
                        .selectinload(Resource.integration_ids),
                    )
                    .execution_options(populate_existing=True)
                )
            )
            .unique()
            .scalar_one_or_none()
        )
        if instance is None:
            return None, None, []

        anchor = instance.anchor_resource
        placed_anchor = (
            PlacedResource(id=anchor.id, template_id=anchor.template_id, name=anchor.name) if anchor else None
        )
        owned = [
            OwnedResource(
                alias=link.alias,
                role=link.role,
                id=link.resource.id,
                template_id=link.resource.template_id,
                name=link.resource.name,
                source_code_version_id=link.resource.source_code_version_id,
                variables={v["name"]: v.get("value") for v in link.resource.variables or [] if "name" in v},
                parent_ids=tuple(p.id for p in link.resource.parents),
                integration_ids=tuple(i.id for i in link.resource.integration_ids),
                storage_id=link.resource.storage_id,
                storage_path=link.resource.storage_path,
                workspace_id=link.resource.workspace_id,
                state=str(link.resource.state),
                status=str(link.resource.status),
            )
            for link in instance.resources
        ]
        return instance.id, placed_anchor, owned
