"""Service topology as trees for the UI graph view: dependencies, dependents, and services a resource affects."""

from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from application.environments.model import Environment
from application.resources.model import Resource
from application.service_instances.model import ServiceInstance, ServiceInstanceResource, ServiceResourceRole
from application.templates.model import Template

from .model import Service, service_links

MAX_DEPTH = 5


@dataclass(frozen=True)
class ServiceInfo:
    id: UUID
    name: str
    display_name: str | None = None


@dataclass(frozen=True)
class LinkInfo:
    """A resource linked to a service in one environment."""

    service_id: UUID
    environment_name: str
    alias: str
    role: str
    resource_id: UUID
    resource_name: str
    template: str
    state: str
    status: str


@dataclass
class GraphNode:
    id: UUID
    node_id: str
    name: str
    entity_name: str
    relation: str
    state: str = ""
    status: str = ""
    template_name: str = ""
    children: list["GraphNode"] = field(default_factory=list)


@dataclass
class Topology:
    services: dict[UUID, ServiceInfo]
    depends_on: dict[UUID, list[UUID]]
    dependents: dict[UUID, list[UUID]]
    links: list[LinkInfo]

    def links_of(self, service_id: UUID) -> list[LinkInfo]:
        return sorted(
            (link for link in self.links if link.service_id == service_id),
            key=lambda link: (link.environment_name, link.alias),
        )

    def users_of(self, resource_id: UUID) -> list[LinkInfo]:
        return sorted(
            (link for link in self.links if link.resource_id == resource_id),
            key=lambda link: (link.role == ServiceResourceRole.REFERENCED, link.environment_name),
        )


_LABELS = {"root": "Service", "depends_on": "Depends on", "used_by": "Used by"}


def _service_node(topology: Topology, service_id: UUID, path: str, relation: str, detail: str = "") -> GraphNode:
    info = topology.services[service_id]
    label = _LABELS.get(relation, relation)
    return GraphNode(
        id=service_id,
        node_id=path,
        name=info.display_name or info.name,
        entity_name="service",
        relation=relation,
        template_name=f"{label}: {detail}" if detail else label,
    )


def _resource_node(link: LinkInfo, path: str) -> GraphNode:
    relation = "referenced" if link.role == ServiceResourceRole.REFERENCED else "owned"
    return GraphNode(
        id=link.resource_id,
        node_id=path,
        name=link.resource_name,
        entity_name="resource",
        relation=relation,
        state=link.state,
        status=link.status,
        template_name=f"{link.template} · {link.alias} · {relation} · {link.environment_name}",
    )


def dependency_tree(topology: Topology, root: UUID, environment_name: str | None = None) -> GraphNode:
    """The service, the services it depends on (recursively), and the resources each one uses."""

    def build(service_id: UUID, path: str, relation: str, ancestors: frozenset[UUID], depth: int) -> GraphNode:
        node = _service_node(topology, service_id, path, relation)
        if depth >= MAX_DEPTH:
            return node
        for dep in sorted(topology.depends_on.get(service_id, []), key=lambda s: topology.services[s].name):
            if dep in ancestors:
                node.children.append(_service_node(topology, dep, f"{path}/{dep}", "depends_on", "cycle"))
            else:
                node.children.append(build(dep, f"{path}/{dep}", "depends_on", ancestors | {dep}, depth + 1))
        for link in topology.links_of(service_id):
            if environment_name is None or link.environment_name == environment_name:
                node.children.append(_resource_node(link, f"{path}/r:{link.environment_name}:{link.alias}"))
        return node

    return build(root, str(root), "root", frozenset({root}), 0)


def dependents_tree(topology: Topology, root: UUID) -> GraphNode:
    """The service and every service that depends on it, directly or not: what a change here can break."""

    def build(service_id: UUID, path: str, relation: str, ancestors: frozenset[UUID], depth: int) -> GraphNode:
        node = _service_node(topology, service_id, path, relation)
        if depth >= MAX_DEPTH:
            return node
        for dependent in sorted(topology.dependents.get(service_id, []), key=lambda s: topology.services[s].name):
            if dependent not in ancestors:
                node.children.append(
                    build(dependent, f"{path}/{dependent}", "used_by", ancestors | {dependent}, depth + 1)
                )
        return node

    return build(root, str(root), "root", frozenset({root}), 0)


def resource_impact_tree(topology: Topology, resource: GraphNode) -> GraphNode:
    """A resource, the services that own or reference it, and the services depending on those."""
    for link in topology.users_of(resource.id):
        relation = "referenced" if link.role == ServiceResourceRole.REFERENCED else "owned"
        path = f"{resource.node_id}/{link.service_id}:{link.environment_name}"
        service = _service_node(
            topology, link.service_id, path, "used_by", f"{relation} as {link.alias} in {link.environment_name}"
        )
        service.children = dependents_tree(topology, link.service_id).children
        _prefix(service.children, path)
        resource.children.append(service)
    return resource


def _prefix(nodes: list[GraphNode], prefix: str) -> None:
    for node in nodes:
        node.node_id = f"{prefix}/{node.node_id}"
        _prefix(node.children, prefix)


async def load_topology(session: AsyncSession) -> Topology:
    services = {
        row.id: ServiceInfo(id=row.id, name=row.name, display_name=row.display_name)
        for row in await session.execute(select(Service.id, Service.name, Service.display_name))
    }
    depends_on: dict[UUID, list[UUID]] = defaultdict(list)
    dependents: dict[UUID, list[UUID]] = defaultdict(list)
    for row in await session.execute(select(service_links.c.service_id, service_links.c.depends_on_service_id)):
        depends_on[row.service_id].append(row.depends_on_service_id)
        dependents[row.depends_on_service_id].append(row.service_id)

    rows = await session.execute(
        select(
            ServiceInstance.service_id,
            Environment.name.label("environment_name"),
            ServiceInstanceResource.alias,
            ServiceInstanceResource.role,
            Resource.id.label("resource_id"),
            Resource.name.label("resource_name"),
            Template.template,
            Resource.state,
            Resource.status,
        )
        .join(ServiceInstance, ServiceInstance.id == ServiceInstanceResource.service_instance_id)
        .join(Environment, Environment.id == ServiceInstance.environment_id)
        .join(Resource, Resource.id == ServiceInstanceResource.resource_id)
        .join(Template, Template.id == Resource.template_id)
    )
    links = [
        LinkInfo(
            service_id=row.service_id,
            environment_name=row.environment_name,
            alias=row.alias,
            role=row.role,
            resource_id=row.resource_id,
            resource_name=row.resource_name,
            template=row.template,
            state=str(row.state),
            status=str(row.status),
        )
        for row in rows
    ]
    return Topology(services=services, depends_on=dict(depends_on), dependents=dict(dependents), links=links)


async def resource_node(session: AsyncSession, resource_id: UUID) -> GraphNode | None:
    row = (
        await session.execute(
            select(Resource.id, Resource.name, Resource.state, Resource.status, Template.template)
            .join(Template, Template.id == Resource.template_id)
            .where(Resource.id == resource_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return GraphNode(
        id=row.id,
        node_id=str(row.id),
        name=row.name,
        entity_name="resource",
        relation="root",
        state=str(row.state),
        status=str(row.status),
        template_name=row.template,
    )
