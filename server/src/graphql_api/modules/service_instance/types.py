import uuid

import strawberry
from strawberry_sqlalchemy_mapper import StrawberrySQLAlchemyMapper

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
