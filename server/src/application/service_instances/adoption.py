"""Reverse-compile adopted resources into ServiceSpec claims so the first plan of every adopted instance is a no-op."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from application.services.schema import ClaimSpec, ServiceSpec, parse_output_ref


@dataclass(frozen=True)
class AdoptedResource:
    alias: str
    resource_id: UUID
    template_key: str
    source_code_version_id: UUID | None
    variables: list[dict[str, Any]] = field(default_factory=list)
    parent_ids: tuple[UUID, ...] = ()
    # Variables provided by parents/project dependency_config; they differ per environment, so never claimed.
    inherited_names: frozenset[str] = frozenset()


def claimable_variables(resource: AdoptedResource) -> dict[str, Any]:
    return {
        v["name"]: v.get("value")
        for v in resource.variables
        if "name" in v
        and not v.get("sensitive")
        and v["name"] not in resource.inherited_names
        and v.get("value") is not None
    }


def reverse_compile(
    spec: ServiceSpec, adopted: list[AdoptedResource], alias_by_resource: dict[UUID, str]
) -> tuple[ServiceSpec, list[str]]:
    """
    Merge adopted resources into the spec. A claim that already exists keeps only the variables every adopted
    resource agrees on and stays pinned only if the versions match, so no adopted instance plans a change.
    Returns the new spec and any conflicts that prevent adoption.
    """
    claims = {claim.alias: claim.model_copy(deep=True) for claim in spec.claims}
    order = [claim.alias for claim in spec.claims]
    errors: list[str] = []

    for resource in adopted:
        variables = claimable_variables(resource)
        parents = sorted(
            alias_by_resource[pid]
            for pid in resource.parent_ids
            if pid in alias_by_resource and pid != resource.resource_id
        )
        claim = claims.get(resource.alias)
        if claim is None:
            claims[resource.alias] = ClaimSpec(
                alias=resource.alias,
                template=resource.template_key,
                source_code_version_id=resource.source_code_version_id,
                variables=variables,
                parents=parents,
                adopted=True,
            )
            order.append(resource.alias)
            continue

        if claim.template != resource.template_key:
            errors.append(
                f"Alias '{resource.alias}' is claimed as '{claim.template}' "
                f"but the resource is '{resource.template_key}'"
            )
            continue
        claim.variables = {
            name: value
            for name, value in claim.variables.items()
            if parse_output_ref(value) is not None or variables.get(name) == value
        }
        if claim.source_code_version_id != resource.source_code_version_id:
            claim.source_code_version_id = None
        claim.parents = sorted(set(claim.parents) | set(parents))

    known = set(claims)
    for claim in claims.values():
        claim.parents = [p for p in claim.parents if p in known and p != claim.alias]

    return ServiceSpec(
        claims=[claims[alias] for alias in order], bindings=spec.bindings, workload=spec.workload
    ), errors
