from datetime import datetime
import uuid

import strawberry
from strawberry_sqlalchemy_mapper import StrawberrySQLAlchemyMapper

from application.service_instances.binding_delivery import BindingPreview
from application.service_instances.bindings import MASK
from application.service_instances.migration import MigrationProposal, ProposedResource
from application.service_instances.model import ServiceDeployment, ServiceInstance, ServiceInstanceResource
from graphql_api.modules.environment.types import EnvironmentType
from graphql_api.modules.resource.types import ResourceType
from graphql_api.modules.service.types import ServiceType
from graphql_api.modules.user.types import UserType


service_instance_mapper = StrawberrySQLAlchemyMapper()


@service_instance_mapper.type(ServiceInstanceResource)
class ServiceInstanceResourceType:
    __exclude__ = ["resource", "service_instance_id"]

    id: uuid.UUID = strawberry.UNSET
    resource: ResourceType | None = None


@service_instance_mapper.type(ServiceInstance)
class ServiceInstanceType:
    __exclude__ = ["created_by", "service", "environment", "anchor_resource", "resources"]

    id: uuid.UUID = strawberry.UNSET
    creator: UserType | None = None
    service: ServiceType | None = None
    environment: EnvironmentType | None = None
    anchor_resource: ResourceType | None = None
    resources: list[ServiceInstanceResourceType] = strawberry.field(default_factory=list)

    @strawberry.field
    def entity_name(self) -> str:
        return "service_instance"


service_instance_mapper.finalize()


@strawberry.type
class BindingItemType:
    key: str
    scope: str
    value: str
    sensitive: bool
    sources: list[str]


@strawberry.type
class ServiceBindingsType:
    deployed: bool
    sink: str
    path: str | None
    namespace: str | None
    secret_provider_class: str | None
    manage_secret_provider_class: bool
    mount_path: str | None
    runtime: list[BindingItemType]
    build: list[BindingItemType]
    errors: list[str]
    applied_keys: list[str]
    applied_at: str | None
    applied_path: str | None

    @staticmethod
    def from_preview(preview: BindingPreview, deployed: bool) -> "ServiceBindingsType":
        target = preview.target
        applied = preview.applied or {}

        def items(scope: str) -> list[BindingItemType]:
            return [
                BindingItemType(
                    key=i.key,
                    scope=i.scope,
                    value=MASK if scope == "runtime" else i.value,
                    sensitive=i.sensitive,
                    sources=i.sources,
                )
                for i in preview.rendered.items
                if i.scope == scope
            ]

        return ServiceBindingsType(
            deployed=deployed,
            sink=target.config.type,
            path=target.path,
            namespace=target.namespace or None,
            secret_provider_class=target.secret_provider_class,
            manage_secret_provider_class=target.config.secret_provider_class,
            mount_path=target.mount_path,
            runtime=items("runtime"),
            build=items("build"),
            errors=preview.rendered.errors,
            applied_keys=list(applied.get("keys", [])),
            applied_at=applied.get("applied_at"),
            applied_path=applied.get("path"),
        )


@strawberry.type
class MigrationAnchorType:
    id: uuid.UUID
    name: str


@strawberry.type
class ServiceDeploymentType:
    id: uuid.UUID
    service_id: uuid.UUID
    service_instance_id: uuid.UUID
    environment_id: uuid.UUID
    environment_name: str
    batch_id: uuid.UUID
    position: int
    version: str
    previous_version: str | None
    status: str
    source: str
    message: str | None
    created_by: uuid.UUID
    created_by_name: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @staticmethod
    def from_model(d: ServiceDeployment) -> "ServiceDeploymentType":
        creator = d.creator
        return ServiceDeploymentType(
            id=d.id,
            service_id=d.service_id,
            service_instance_id=d.service_instance_id,
            environment_id=d.environment_id,
            environment_name=d.environment.name if d.environment else "",
            batch_id=d.batch_id,
            position=d.position,
            version=d.version,
            previous_version=d.previous_version,
            status=d.status,
            source=d.source,
            message=d.message,
            created_by=d.created_by,
            created_by_name=(creator.display_name or creator.identifier) if creator else None,
            created_at=d.created_at,
            started_at=d.started_at,
            finished_at=d.finished_at,
        )


@strawberry.type
class DeployTokenType:
    id: uuid.UUID
    name: str
    token: str
    token_prefix: str
    expires_at: datetime | None


@strawberry.type
class ProposedResourceType:
    resource_id: uuid.UUID
    name: str
    template: str
    state: str
    alias: str
    role: str
    owned_by: str | None


@strawberry.type
class ProposedEnvironmentType:
    environment_id: uuid.UUID
    environment_name: str
    resources: list[ProposedResourceType]


def _resource(r: ProposedResource) -> ProposedResourceType:
    return ProposedResourceType(
        resource_id=r.resource_id,
        name=r.name,
        template=r.template,
        state=r.state,
        alias=r.alias,
        role=str(r.role),
        owned_by=r.owned_by,
    )


@strawberry.type
class MigrationProposalType:
    anchor_id: uuid.UUID
    anchor_name: str
    project_id: uuid.UUID | None
    service_name: str
    existing_service_id: uuid.UUID | None
    environments: list[ProposedEnvironmentType]
    unmatched: list[ProposedResourceType]
    warnings: list[str]

    @staticmethod
    def from_proposal(p: MigrationProposal) -> "MigrationProposalType":
        return MigrationProposalType(
            anchor_id=p.anchor_id,
            anchor_name=p.anchor_name,
            project_id=p.project_id,
            service_name=p.service_name,
            existing_service_id=p.existing_service_id,
            environments=[
                ProposedEnvironmentType(
                    environment_id=e.environment_id,
                    environment_name=e.environment_name,
                    resources=[_resource(r) for r in e.resources],
                )
                for e in p.environments
            ],
            unmatched=[_resource(r) for r in p.unmatched],
            warnings=p.warnings,
        )
