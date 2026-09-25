import uuid

import strawberry
from strawberry_sqlalchemy_mapper import StrawberrySQLAlchemyMapper

from application.environments.model import Environment
from graphql_api.modules.integration.types import IntegrationType
from graphql_api.modules.project.types import ProjectType
from graphql_api.modules.resource.types import ResourceType
from graphql_api.modules.storage.types import StorageType
from graphql_api.modules.user.types import UserType
from graphql_api.modules.workspace.types import WorkspaceType


environment_mapper = StrawberrySQLAlchemyMapper()


@environment_mapper.type(Environment)
class EnvironmentType:
    __exclude__ = ["created_by", "project", "workspace", "storage", "integration_ids", "parent_resources"]

    id: uuid.UUID = strawberry.UNSET
    creator: UserType | None = None
    project: ProjectType | None = None
    workspace: WorkspaceType | None = None
    storage: StorageType | None = None
    integration_ids: list[IntegrationType] = strawberry.field(default_factory=list)
    parent_resources: list[ResourceType] = strawberry.field(default_factory=list)

    @strawberry.field
    def entity_name(self) -> str:
        return "environment"


environment_mapper.finalize()
