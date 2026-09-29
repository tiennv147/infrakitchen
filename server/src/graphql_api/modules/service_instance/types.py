import uuid

import strawberry
from strawberry_sqlalchemy_mapper import StrawberrySQLAlchemyMapper

from application.service_instances.migration import MigrationProposal, ProposedResource
from application.service_instances.model import ServiceInstance, ServiceInstanceResource
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
class MigrationAnchorType:
    id: uuid.UUID
    name: str


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
