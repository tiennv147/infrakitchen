from typing import Any

from sqlalchemy.orm import joinedload, raiseload, selectinload

from application.environments.query_options import build_environment_query_options
from application.resources.query_options import build_resource_query_options
from application.services.query_options import build_service_query_options
from core.database import FieldSpec, build_load_only
from core.users.query_options import build_user_query_options

from .model import ServiceInstance, ServiceInstanceResource


def build_service_instance_query_options(fields: FieldSpec | None = None) -> list[Any]:
    if fields is None:
        return [
            joinedload(ServiceInstance.service),
            joinedload(ServiceInstance.environment),
            joinedload(ServiceInstance.anchor_resource),
            joinedload(ServiceInstance.creator),
            selectinload(ServiceInstance.resources).joinedload(ServiceInstanceResource.resource),
        ]

    opts: list[Any] = build_load_only(ServiceInstance, set(fields.keys()))

    joined = {
        ("service",): (ServiceInstance.service, build_service_query_options),
        ("environment",): (ServiceInstance.environment, build_environment_query_options),
        ("anchorResource", "anchor_resource"): (ServiceInstance.anchor_resource, build_resource_query_options),
        ("creator",): (ServiceInstance.creator, build_user_query_options),
    }
    for keys, (relation, builder) in joined.items():
        key = next((k for k in keys if k in fields), None)
        if key is not None:
            opts.append(joinedload(relation).options(*builder(fields[key])))
        else:
            opts.append(raiseload(relation))

    if "resources" in fields:
        opts.append(selectinload(ServiceInstance.resources).joinedload(ServiceInstanceResource.resource))
    else:
        opts.append(raiseload(ServiceInstance.resources))

    return opts
