import uuid

import strawberry
from strawberry.scalars import JSON
from strawberry_sqlalchemy_mapper import StrawberrySQLAlchemyMapper

from application.services.compiler import PlanAction, ServicePlan
from application.services.model import Service
from graphql_api.modules.project.types import ProjectType
from graphql_api.modules.user.types import UserType


service_mapper = StrawberrySQLAlchemyMapper()


@service_mapper.type(Service)
class ServiceType:
    # Only the relation is excluded, so it can be re-declared with ProjectType.
    # The project_id scalar stays auto-mapped and queryable.
    __exclude__ = ["created_by", "project", "depends_on", "dependents"]

    id: uuid.UUID = strawberry.UNSET
    creator: UserType | None = None
    owners: list[UserType] = strawberry.field(default_factory=list)
    project: ProjectType | None = None
    depends_on: list["ServiceType"] = strawberry.field(default_factory=list)
    dependents: list["ServiceType"] = strawberry.field(default_factory=list)

    @strawberry.field
    def entity_name(self) -> str:
        return "service"


service_mapper.finalize()


@strawberry.type
class ServicePlanChangeType:
    field: str
    before: JSON | None = None
    after: JSON | None = None


@strawberry.type
class ServicePlanItemType:
    alias: str
    action: str
    role: str
    template: str | None
    template_id: uuid.UUID | None
    resource_id: uuid.UUID | None
    resource_name: str | None
    position: int | None
    source_code_version_id: uuid.UUID | None
    storage_path: str | None
    parents: list[str]
    wires: list[str]
    changes: list[ServicePlanChangeType]


@strawberry.type
class ServicePlanType:
    service_id: uuid.UUID
    environment_id: uuid.UUID
    service_instance_id: uuid.UUID | None
    items: list[ServicePlanItemType]
    errors: list[str]
    creates: int
    updates: int
    no_ops: int
    destroys: int

    @staticmethod
    def from_plan(plan: ServicePlan) -> "ServicePlanType":
        return ServicePlanType(
            service_id=plan.service_id,
            environment_id=plan.environment_id,
            service_instance_id=plan.service_instance_id,
            items=[
                ServicePlanItemType(
                    alias=item.alias,
                    action=item.action.value,
                    role=item.role,
                    template=item.template,
                    template_id=item.template_id,
                    resource_id=item.resource_id,
                    resource_name=item.resource_name,
                    position=item.position,
                    source_code_version_id=item.source_code_version_id,
                    storage_path=item.storage_path,
                    parents=item.parents,
                    wires=item.wires,
                    changes=[
                        ServicePlanChangeType(field=c.field, before=c.before, after=c.after) for c in item.changes
                    ],
                )
                for item in plan.items
            ],
            errors=plan.errors,
            creates=plan.count(PlanAction.CREATE),
            updates=plan.count(PlanAction.UPDATE),
            no_ops=plan.count(PlanAction.NO_OP),
            destroys=plan.count(PlanAction.DESTROY),
        )


@strawberry.type
class ServiceGraphNodeType:
    """Same fields as ResourceTreeNodeType, plus the node's entity and how it relates to its parent."""

    id: uuid.UUID
    node_id: str
    name: str
    entity_name: str
    relation: str
    state: str
    status: str
    template_name: str
    children: list["ServiceGraphNodeType"]
