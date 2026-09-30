"""Propose Services, environments and ownership from existing `service` anchor resources, for operator review.

Direction note: a row in resource_links (parent_id=X, child_id=Y) means X depends on Y, i.e. Y is in X.parents.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from application.services.schema import ALIAS_PATTERN

from .model import ServiceResourceRole

# `service_anchor` is the current key; installs created before it still use `service`.
ANCHOR_TEMPLATES = ("service_anchor", "service")

_DEPENDENTS = text("""
    WITH RECURSIVE dep(id) AS (
        SELECT l.parent_id FROM resource_links l WHERE l.child_id = :anchor
        UNION
        SELECT l.parent_id FROM resource_links l JOIN dep ON l.child_id = dep.id
    )
    SELECT r.id, r.name, t.template, r.state FROM dep
    JOIN resources r ON r.id = dep.id JOIN templates t ON t.id = r.template_id
""")

_CO_PARENTS = text("""
    SELECT l.parent_id AS dependent_id, r.id, r.name, t.template, r.state
    FROM resource_links l JOIN resources r ON r.id = l.child_id JOIN templates t ON t.id = r.template_id
    WHERE l.parent_id IN :ids AND l.child_id <> :anchor AND l.child_id NOT IN :ids
""").bindparams(bindparam("ids", expanding=True))

_ENVIRONMENTS = text("""
    WITH RECURSIVE anc(start_id, id) AS (
        SELECT l.parent_id, l.child_id FROM resource_links l WHERE l.parent_id IN :ids
        UNION
        SELECT anc.start_id, l.child_id FROM resource_links l JOIN anc ON l.parent_id = anc.id
    )
    SELECT DISTINCT anc.start_id, e.id AS environment_id
    FROM anc
    JOIN environment_parent_resources ep ON ep.resource_id = anc.id
    JOIN environments e ON e.id = ep.environment_id
""").bindparams(bindparam("ids", expanding=True))

_OWNERS = text("""
    SELECT sir.resource_id, s.name AS service_name, e.name AS environment_name
    FROM service_instance_resources sir
    JOIN service_instances si ON si.id = sir.service_instance_id
    JOIN services s ON s.id = si.service_id JOIN environments e ON e.id = si.environment_id
    WHERE sir.resource_id IN :ids AND sir.role <> 'referenced'
""").bindparams(bindparam("ids", expanding=True))


@dataclass
class ProposedResource:
    resource_id: UUID
    name: str
    template: str
    state: str
    alias: str
    role: str
    owned_by: str | None = None


@dataclass
class ProposedEnvironment:
    environment_id: UUID
    environment_name: str
    resources: list[ProposedResource] = field(default_factory=list)


@dataclass
class MigrationProposal:
    anchor_id: UUID
    anchor_name: str
    project_id: UUID | None
    service_name: str
    existing_service_id: UUID | None
    environments: list[ProposedEnvironment] = field(default_factory=list)
    unmatched: list[ProposedResource] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


_ENV_PREFIX = re.compile(r"^[a-z0-9]+-[a-z0-9]+-[a-z]{2}-[a-z]+-\d+-")


def to_alias(name: str, anchor_name: str, template: str) -> str:
    """Environment-neutral alias: the name without its <project>-<env>-<region> prefix and the anchor name."""
    marker = f"{anchor_name}-"
    if marker in name:
        before, suffix = name.split(marker, 1)
        raw = f"{_ENV_PREFIX.sub('', before)}{suffix}"
    else:
        raw = _ENV_PREFIX.sub("", name) or template
    alias = re.sub(r"[^a-z0-9_]+", "_", raw.lower()).strip("_")
    alias = re.sub(r"^[^a-z]+", "", alias) or re.sub(r"[^a-z0-9_]+", "_", template.lower())
    alias = alias[:63].rstrip("_")
    return alias if re.fullmatch(ALIAS_PATTERN, alias) else "resource"


def _unique(alias: str, used: set[str]) -> str:
    candidate, n = alias, 2
    while candidate in used:
        candidate = f"{alias[:60]}_{n}"
        n += 1
    used.add(candidate)
    return candidate


async def propose(session: AsyncSession, anchor_id: UUID) -> MigrationProposal:
    anchor = (
        await session.execute(
            text("""
                SELECT r.id, r.name, r.project_id, (SELECT s.id FROM services s WHERE s.name = r.name LIMIT 1) AS sid
                FROM resources r JOIN templates t ON t.id = r.template_id
                WHERE r.id = :id AND t.template IN :tpl
            """).bindparams(bindparam("tpl", expanding=True)),
            {"id": anchor_id, "tpl": list(ANCHOR_TEMPLATES)},
        )
    ).one_or_none()
    if anchor is None:
        raise ValueError(f"Resource {anchor_id} is not a service anchor ({', '.join(ANCHOR_TEMPLATES)})")

    proposal = MigrationProposal(
        anchor_id=anchor.id,
        anchor_name=anchor.name,
        project_id=anchor.project_id,
        service_name=anchor.name,
        existing_service_id=anchor.sid,
    )
    dependents = [
        r for r in (await session.execute(_DEPENDENTS, {"anchor": anchor_id})).all() if r.state != "DESTROYED"
    ]
    if not dependents:
        proposal.warnings.append("No resources depend on this anchor")
        return proposal

    ids = [r.id for r in dependents]
    co_parents = [r for r in (await session.execute(_CO_PARENTS, {"ids": ids, "anchor": anchor_id})).all()]
    envs_by_resource: dict[UUID, set[UUID]] = defaultdict(set)
    for row in (await session.execute(_ENVIRONMENTS, {"ids": ids + [r.id for r in co_parents]})).all():
        envs_by_resource[row.start_id].add(row.environment_id)
    env_names = {row.id: row.name for row in (await session.execute(text("SELECT id, name FROM environments"))).all()}
    all_ids = ids + [r.id for r in co_parents]
    owners = {
        row.resource_id: f"{row.service_name} ({row.environment_name})"
        for row in (await session.execute(_OWNERS, {"ids": all_ids})).all()
    }

    by_env: dict[UUID, ProposedEnvironment] = {}
    used: dict[UUID, set[str]] = defaultdict(set)
    placed_env_of: dict[UUID, UUID] = {}

    def env(env_id: UUID) -> ProposedEnvironment:
        if env_id not in by_env:
            by_env[env_id] = ProposedEnvironment(environment_id=env_id, environment_name=env_names.get(env_id, "?"))
        return by_env[env_id]

    for r in sorted(dependents, key=lambda r: r.name):
        envs = envs_by_resource.get(r.id, set())
        item = ProposedResource(
            resource_id=r.id,
            name=r.name,
            template=r.template,
            state=r.state.lower(),
            alias=to_alias(r.name, anchor.name, r.template),
            role=ServiceResourceRole.DEPENDENCY,
            owned_by=owners.get(r.id),
        )
        if len(envs) == 1:
            env_id = next(iter(envs))
            item.alias = _unique(item.alias, used[env_id])
            env(env_id).resources.append(item)
            placed_env_of[r.id] = env_id
        else:
            proposal.unmatched.append(item)
            if len(envs) > 1:
                proposal.warnings.append(f"{r.name} matches {len(envs)} environments; assign it manually")

    seen: set[tuple[UUID, UUID]] = set()
    for r in sorted(co_parents, key=lambda r: r.name):
        env_id = placed_env_of.get(r.dependent_id)
        if env_id is None or (env_id, r.id) in seen or r.state == "DESTROYED":
            continue
        seen.add((env_id, r.id))
        env(env_id).resources.append(
            ProposedResource(
                resource_id=r.id,
                name=r.name,
                template=r.template,
                state=r.state.lower(),
                alias=_unique(to_alias(r.name, anchor.name, r.template), used[env_id]),
                role=ServiceResourceRole.REFERENCED,
            )
        )

    if not by_env:
        proposal.warnings.append("No dependent could be matched to an environment by its landing zone")
    proposal.environments = sorted(by_env.values(), key=lambda e: e.environment_name)
    return proposal


async def list_anchors(session: AsyncSession, project_id: UUID | None) -> list[tuple[UUID, str]]:
    rows = await session.execute(
        text("""
            SELECT r.id, r.name FROM resources r JOIN templates t ON t.id = r.template_id
            WHERE t.template IN :tpl AND r.state <> 'DESTROYED'
              AND (CAST(:project AS uuid) IS NULL OR r.project_id = :project)
            ORDER BY r.name
        """).bindparams(bindparam("tpl", expanding=True)),
        {"tpl": list(ANCHOR_TEMPLATES), "project": project_id},
    )
    return [(row.id, row.name) for row in rows]
