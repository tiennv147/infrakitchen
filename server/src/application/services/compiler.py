"""Compile a ServiceSpec for one Environment into a Workflow plus a human-readable plan.

The compiler is pure: callers load catalog, environment and owned-resource snapshots and pass them in.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from application.workflows.functions import topological_levels
from application.workflows.schema import WiringRule, WorkflowCreate, WorkflowStepCreate
from core.constants.model import ModelStatus

from .schema import ClaimSpec, ServiceSpec


@dataclass(frozen=True)
class CatalogTemplate:
    id: UUID
    key: str
    name: str
    enabled: bool
    abstract: bool
    claimable: bool
    naming_convention: str | None
    parent_template_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class CatalogVersion:
    id: UUID
    template_id: UUID
    enabled: bool = True


@dataclass(frozen=True)
class PlacedResource:
    """An existing resource that can serve as a parent (anchor or landing zone)."""

    id: UUID
    template_id: UUID
    name: str


@dataclass(frozen=True)
class EnvironmentTarget:
    id: UUID
    name: str
    integration_ids: tuple[UUID, ...] = ()
    storage_id: UUID | None = None
    storage_path_prefix: str | None = None
    workspace_id: UUID | None = None
    landing_zone: tuple[PlacedResource, ...] = ()


@dataclass(frozen=True)
class OwnedResource:
    """A resource already linked to the service instance. Its placement is pinned."""

    alias: str
    role: str
    id: UUID
    template_id: UUID
    name: str
    source_code_version_id: UUID | None
    variables: dict[str, Any] = field(default_factory=dict)
    parent_ids: tuple[UUID, ...] = ()
    integration_ids: tuple[UUID, ...] = ()
    storage_id: UUID | None = None
    storage_path: str | None = None
    workspace_id: UUID | None = None
    state: str = "provisioned"
    status: str = "done"

    @property
    def settled(self) -> bool:
        return self.state.lower() == "provisioned" and self.status.lower() == "done"


@dataclass(frozen=True)
class Catalog:
    templates_by_key: dict[str, CatalogTemplate]
    versions: dict[UUID, CatalogVersion] = field(default_factory=dict)
    latest_version_by_template: dict[UUID, UUID] = field(default_factory=dict)
    # Keys of every template seen, including parents outside the catalog, for readable errors.
    template_key_by_id: dict[UUID, str] = field(default_factory=dict)

    def key_of(self, template_id: UUID) -> str:
        if template_id in self.template_key_by_id:
            return self.template_key_by_id[template_id]
        return next((t.key for t in self.templates_by_key.values() if t.id == template_id), str(template_id))


class PlanAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    NO_OP = "no_op"
    DESTROY = "destroy"


class PlanChange(BaseModel):
    field: str
    before: Any = None
    after: Any = None


class PlanItem(BaseModel):
    alias: str
    action: PlanAction
    role: str
    template: str | None = None
    template_id: UUID | None = None
    resource_id: UUID | None = None
    resource_name: str | None = None
    position: int | None = None
    source_code_version_id: UUID | None = None
    storage_path: str | None = None
    parents: list[str] = Field(default_factory=list)
    wires: list[str] = Field(default_factory=list)
    changes: list[PlanChange] = Field(default_factory=list)


class ServicePlan(BaseModel):
    service_id: UUID
    environment_id: UUID
    service_instance_id: UUID | None = None
    items: list[PlanItem] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    def count(self, action: PlanAction) -> int:
        return sum(1 for item in self.items if item.action == action)


@dataclass
class CompiledService:
    plan: ServicePlan
    workflow: WorkflowCreate | None


def validate_spec_against_catalog(spec: ServiceSpec, catalog: Catalog) -> list[str]:
    """Problems that make a spec unusable in any environment."""
    errors: list[str] = []
    for claim in spec.claims:
        template = catalog.templates_by_key.get(claim.template)
        if template is None:
            errors.append(f"Claim '{claim.alias}': template '{claim.template}' does not exist")
            continue
        # Adopted claims describe resources that already exist, whatever catalog status their template has.
        if not claim.adopted and (not template.claimable or template.abstract):
            errors.append(f"Claim '{claim.alias}': template '{claim.template}' is not in the offering catalog")
        elif not claim.adopted and not template.enabled:
            errors.append(f"Claim '{claim.alias}': template '{claim.template}' is disabled")
        if claim.source_code_version_id is not None:
            version = catalog.versions.get(claim.source_code_version_id)
            if version is None or version.template_id != template.id:
                errors.append(
                    f"Claim '{claim.alias}': version {claim.source_code_version_id} "
                    f"is not a version of '{claim.template}'"
                )
            elif not version.enabled:
                errors.append(f"Claim '{claim.alias}': version {claim.source_code_version_id} is disabled")

    by_alias = {claim.alias: claim for claim in spec.claims}
    for claim in spec.claims:
        template = catalog.templates_by_key.get(claim.template)
        if template is None:
            continue
        for parent_alias in claim.parents:
            parent_template = catalog.templates_by_key.get(by_alias[parent_alias].template)
            if parent_template is not None and parent_template.id not in template.parent_template_ids:
                errors.append(
                    f"Claim '{claim.alias}': '{parent_alias}' ({parent_template.key}) "
                    f"is not a valid parent for template '{template.key}'"
                )

    try:
        _order(spec)
    except ValueError:
        errors.append("Claims reference each other in a cycle")
    return errors


def default_storage_path(environment: EnvironmentTarget, service_name: str, alias: str) -> str:
    prefix = (environment.storage_path_prefix or "services").strip("/")
    return f"{prefix}/{environment.name}/{service_name}/{alias}/terraform.tfstate"


def _order(spec: ServiceSpec) -> dict[str, int]:
    edges: list[tuple[str, str]] = []
    for claim in spec.claims:
        edges.extend((ref.alias, claim.alias) for ref in claim.output_refs().values())
        edges.extend((parent, claim.alias) for parent in claim.parents)
    return dict(topological_levels([claim.alias for claim in spec.claims], edges))


def compile_service_spec(
    *,
    service_id: UUID,
    service_name: str,
    spec: ServiceSpec,
    catalog: Catalog,
    environment: EnvironmentTarget,
    owned: list[OwnedResource],
    created_by: UUID,
    anchor: PlacedResource | None = None,
    service_instance_id: UUID | None = None,
) -> CompiledService:
    plan = ServicePlan(service_id=service_id, environment_id=environment.id, service_instance_id=service_instance_id)
    plan.errors.extend(validate_spec_against_catalog(spec, catalog))

    owned_by_alias = {resource.alias: resource for resource in owned}
    for claim in spec.claims:
        existing = owned_by_alias.get(claim.alias)
        if existing is not None and existing.role == "referenced":
            plan.errors.append(f"Claim '{claim.alias}' collides with a referenced resource of the same alias")
    if plan.errors:
        return CompiledService(plan=plan, workflow=None)

    positions = _order(spec)
    steps: list[WorkflowStepCreate] = []
    wiring: list[WiringRule] = []
    claims_by_alias = {claim.alias: claim for claim in spec.claims}
    templates_by_alias = {claim.alias: catalog.templates_by_key[claim.template] for claim in spec.claims}

    for claim in sorted(spec.claims, key=lambda c: (positions[c.alias], c.alias)):
        template = templates_by_alias[claim.alias]
        existing = owned_by_alias.get(claim.alias)

        if existing is not None and existing.template_id != template.id:
            plan.errors.append(
                f"Claim '{claim.alias}' changes template to '{template.key}'; "
                "replacing a resource is not supported, use a new alias"
            )
            continue
        if existing is not None and existing.state.lower() in ("destroy", "destroyed"):
            plan.errors.append(
                f"Claim '{claim.alias}': resource {existing.name} is {existing.state.lower()}; use a new alias"
            )
            continue

        if existing is None:
            parent_ids, parent_keys, parent_labels, errors = _resolve_parents(
                claim, template, catalog, environment, anchor, owned_by_alias, claims_by_alias
            )
            errors.extend(_create_problems(claim, template, catalog))
            if errors:
                plan.errors.extend(errors)
                continue
            item, step = _plan_create(
                claim, template, positions[claim.alias], catalog, environment, service_name, parent_ids, parent_keys
            )
            item.parents = parent_labels
        else:
            item, step = _plan_existing(claim, template, positions[claim.alias], existing)

        wires = _wiring_for(claim, templates_by_alias)
        item.wires = [f"{w.target_variable} \u2190 {w.source_step_key}.outputs.{w.source_output}" for w in wires]
        wiring.extend(wires)
        plan.items.append(item)
        steps.append(step)

    claimed = {claim.alias for claim in spec.claims}
    for resource in owned:
        if resource.alias in claimed or resource.role == "referenced":
            continue
        plan.items.append(
            PlanItem(
                alias=resource.alias,
                action=PlanAction.DESTROY,
                role=resource.role,
                template_id=resource.template_id,
                resource_id=resource.id,
                resource_name=resource.name,
                storage_path=resource.storage_path,
            )
        )

    if plan.errors:
        return CompiledService(plan=plan, workflow=None)
    workflow = WorkflowCreate(wiring_snapshot=wiring, created_by=created_by, steps=steps)
    return CompiledService(plan=plan, workflow=workflow)


def _wiring_for(claim: ClaimSpec, templates_by_alias: dict[str, CatalogTemplate]) -> list[WiringRule]:
    return [
        WiringRule(
            source_template_id=templates_by_alias[ref.alias].id,
            source_output=ref.output,
            target_template_id=templates_by_alias[claim.alias].id,
            target_variable=variable,
            source_step_key=ref.alias,
            target_step_key=claim.alias,
        )
        for variable, ref in claim.output_refs().items()
    ]


def _resolve_parents(
    claim: ClaimSpec,
    template: CatalogTemplate,
    catalog: Catalog,
    environment: EnvironmentTarget,
    anchor: PlacedResource | None,
    owned_by_alias: dict[str, OwnedResource],
    claims_by_alias: dict[str, ClaimSpec],
) -> tuple[list[UUID], list[str], list[str], list[str]]:
    """Pick exactly one parent per parent template: sibling claim, then anchor, then landing zone."""
    resource_ids: list[UUID] = []
    step_keys: list[str] = []
    labels: list[str] = []
    errors: list[str] = []

    explicit = {catalog.templates_by_key[claims_by_alias[a].template].id: a for a in claim.parents}
    for parent_template_id in template.parent_template_ids:
        sibling = explicit.get(parent_template_id)
        if sibling is not None:
            owned = owned_by_alias.get(sibling)
            if owned is not None:
                resource_ids.append(owned.id)
            else:
                step_keys.append(sibling)
            labels.append(f"claim:{sibling}")
            continue
        if anchor is not None and anchor.template_id == parent_template_id:
            resource_ids.append(anchor.id)
            labels.append(f"anchor:{anchor.name}")
            continue
        landing = [r for r in environment.landing_zone if r.template_id == parent_template_id]
        if len(landing) == 1:
            resource_ids.append(landing[0].id)
            labels.append(f"environment:{landing[0].name}")
            continue
        parent_key = catalog.key_of(parent_template_id)
        if landing:
            errors.append(
                f"Claim '{claim.alias}': environment '{environment.name}' has several '{parent_key}' resources; "
                f"claim the intended one under 'parents'"
            )
        else:
            errors.append(
                f"Claim '{claim.alias}' needs a '{parent_key}' parent: add a claim for it under 'parents', "
                f"or add one to the landing zone of environment '{environment.name}'"
            )
    return resource_ids, step_keys, labels, errors


def _create_problems(claim: ClaimSpec, template: CatalogTemplate, catalog: Catalog) -> list[str]:
    errors: list[str] = []
    if claim.source_code_version_id is None and template.id not in catalog.latest_version_by_template:
        errors.append(f"Claim '{claim.alias}': template '{template.key}' has no active version; pin one")
    if not template.naming_convention:
        errors.append(f"Claim '{claim.alias}': template '{template.key}' has no naming convention")
    return errors


def _plan_create(
    claim: ClaimSpec,
    template: CatalogTemplate,
    position: int,
    catalog: Catalog,
    environment: EnvironmentTarget,
    service_name: str,
    parent_ids: list[UUID],
    parent_keys: list[str],
) -> tuple[PlanItem, WorkflowStepCreate]:
    version_id = claim.source_code_version_id or catalog.latest_version_by_template[template.id]
    storage_path = default_storage_path(environment, service_name, claim.alias)
    variables = claim.literal_variables()
    step = WorkflowStepCreate(
        template_id=template.id,
        position=position,
        step_key=claim.alias,
        resolved_variables=variables,
        source_code_version_id=version_id,
        parent_resource_ids=parent_ids,
        parent_step_keys=parent_keys,
        integration_ids=list(environment.integration_ids),
        storage_id=environment.storage_id,
        storage_path=storage_path,
        workspace_id=environment.workspace_id,
    )
    item = PlanItem(
        alias=claim.alias,
        action=PlanAction.CREATE,
        role="dependency",
        template=template.key,
        template_id=template.id,
        position=position,
        source_code_version_id=version_id,
        storage_path=storage_path,
        changes=[PlanChange(field=name, after=value) for name, value in sorted(variables.items())],
    )
    return item, step


def _plan_existing(
    claim: ClaimSpec,
    template: CatalogTemplate,
    position: int,
    existing: OwnedResource,
) -> tuple[PlanItem, WorkflowStepCreate]:
    """Owned resources keep their placement; only variables and a pinned version can change."""
    changes: list[PlanChange] = []
    for name, value in sorted(claim.literal_variables().items()):
        if existing.variables.get(name) != value:
            changes.append(PlanChange(field=name, before=existing.variables.get(name), after=value))

    version_id = existing.source_code_version_id
    if claim.source_code_version_id is not None and claim.source_code_version_id != existing.source_code_version_id:
        changes.append(
            PlanChange(
                field="source_code_version_id",
                before=str(existing.source_code_version_id) if existing.source_code_version_id else None,
                after=str(claim.source_code_version_id),
            )
        )
        version_id = claim.source_code_version_id

    if not existing.settled:
        changes.append(
            PlanChange(
                field="state",
                before=f"{existing.state.lower()}/{existing.status.lower()}",
                after="provisioned/done",
            )
        )

    action = PlanAction.UPDATE if changes else PlanAction.NO_OP
    step = WorkflowStepCreate(
        template_id=template.id,
        position=position,
        step_key=claim.alias,
        status=ModelStatus.PENDING if changes else ModelStatus.DONE,
        resource_id=existing.id,
        resolved_variables={**existing.variables, **claim.literal_variables()},
        source_code_version_id=version_id,
        parent_resource_ids=list(existing.parent_ids),
        integration_ids=list(existing.integration_ids),
        storage_id=existing.storage_id,
        storage_path=existing.storage_path,
        workspace_id=existing.workspace_id,
    )
    item = PlanItem(
        alias=claim.alias,
        action=action,
        role=existing.role,
        template=template.key,
        template_id=template.id,
        resource_id=existing.id,
        resource_name=existing.name,
        position=step.position,
        source_code_version_id=version_id,
        storage_path=existing.storage_path,
        changes=changes,
    )
    return item, step
