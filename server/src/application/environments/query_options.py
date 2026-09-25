from typing import Any

from sqlalchemy.orm import joinedload, noload, selectinload

from application.integrations.query_options import build_integration_query_options
from application.projects.query_options import build_project_query_options
from application.resources.query_options import build_resource_query_options
from application.storages.query_options import build_storage_query_options
from application.workspaces.query_options import build_workspace_query_options
from core.database import FieldSpec, build_load_only
from core.users.query_options import build_user_query_options

from .model import Environment


def build_environment_query_options(fields: FieldSpec | None = None) -> list[Any]:
    if fields is None:
        return [
            joinedload(Environment.project),
            joinedload(Environment.workspace),
            joinedload(Environment.storage),
            joinedload(Environment.creator),
            selectinload(Environment.integration_ids),
            selectinload(Environment.parent_resources),
        ]

    opts: list[Any] = build_load_only(Environment, set(fields.keys()))

    joined = {
        "project": (Environment.project, build_project_query_options),
        "workspace": (Environment.workspace, build_workspace_query_options),
        "storage": (Environment.storage, build_storage_query_options),
        "creator": (Environment.creator, build_user_query_options),
    }
    for name, (relation, builder) in joined.items():
        if name in fields:
            opts.append(joinedload(relation).options(*builder(fields[name])))
        else:
            opts.append(noload(relation))

    collections = {
        "integration_ids": (Environment.integration_ids, build_integration_query_options),
        "parent_resources": (Environment.parent_resources, build_resource_query_options),
    }
    for name, (relation, builder) in collections.items():
        if name in fields:
            opts.append(selectinload(relation).options(*builder(fields[name])))
        else:
            opts.append(noload(relation))

    return opts
