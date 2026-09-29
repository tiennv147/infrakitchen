from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from application.services.compiler import (
    Catalog,
    CatalogTemplate,
    CatalogVersion,
    EnvironmentTarget,
    OwnedResource,
    PlacedResource,
    PlanAction,
    compile_service_spec,
    default_storage_path,
    validate_spec_against_catalog,
)
from application.services.schema import ClaimSpec, ServiceSpec, parse_output_ref
from core.constants.model import ModelStatus

SERVICE_ID = uuid4()
USER_ID = uuid4()
ANCHOR_TID = uuid4()
LZ_TID = uuid4()


def _template(key: str, *, parents: tuple[UUID, ...] = (), **overrides) -> CatalogTemplate:
    values = dict(
        id=uuid4(),
        key=key,
        name=key.title(),
        enabled=True,
        abstract=False,
        claimable=True,
        naming_convention=f"{key}-{{service_name}}",
        parent_template_ids=parents,
    )
    values.update(overrides)
    return CatalogTemplate(**values)


def _catalog(*templates: CatalogTemplate, versions: tuple[CatalogVersion, ...] = ()) -> Catalog:
    return Catalog(
        templates_by_key={t.key: t for t in templates},
        versions={v.id: v for v in versions},
        latest_version_by_template={t.id: uuid4() for t in templates},
    )


LANDING_ZONE = PlacedResource(id=uuid4(), template_id=LZ_TID, name="eks-dev")
ENV = EnvironmentTarget(
    id=uuid4(),
    name="dev-eu-central-1",
    integration_ids=(uuid4(),),
    storage_id=uuid4(),
    storage_path_prefix="state/",
    workspace_id=uuid4(),
    landing_zone=(LANDING_ZONE,),
)


def _compile(spec: ServiceSpec, catalog: Catalog, *, owned=(), anchor=None, environment=ENV):
    return compile_service_spec(
        service_id=SERVICE_ID,
        service_name="checkout",
        spec=spec,
        catalog=catalog,
        environment=environment,
        owned=list(owned),
        created_by=USER_ID,
        anchor=anchor,
    )


class TestServiceSpecSchema:
    def test_whole_value_reference_is_parsed(self):
        ref = parse_output_ref("${cache.outputs.endpoint}")
        assert ref is not None and (ref.alias, ref.output) == ("cache", "endpoint")

    def test_plain_values_are_literals(self):
        assert parse_output_ref("redis://cache") is None
        assert parse_output_ref(6379) is None

    def test_interpolation_is_rejected(self):
        with pytest.raises(ValueError, match="interpolation"):
            parse_output_ref("redis://${cache.outputs.host}:6379")

    def test_duplicate_aliases_rejected(self):
        with pytest.raises(ValidationError, match="Duplicate claim aliases: db"):
            ServiceSpec(claims=[ClaimSpec(alias="db", template="pg"), ClaimSpec(alias="db", template="pg")])

    def test_unknown_reference_rejected(self):
        with pytest.raises(ValidationError, match="unknown claim 'nope'"):
            ServiceSpec(claims=[ClaimSpec(alias="app", template="x", variables={"url": "${nope.outputs.url}"})])

    def test_self_reference_rejected(self):
        with pytest.raises(ValidationError, match="cannot reference itself"):
            ServiceSpec(claims=[ClaimSpec(alias="db", template="pg", parents=["db"])])

    def test_bad_alias_rejected(self):
        with pytest.raises(ValidationError, match="must match"):
            ClaimSpec(alias="Bad-Alias", template="pg")

    def test_unknown_fields_rejected(self):
        with pytest.raises(ValidationError):
            ServiceSpec.model_validate({"claims": [], "workload": {}})


class TestCatalogValidation:
    def test_only_claimable_enabled_concrete_templates_are_accepted(self):
        catalog = _catalog(
            _template("internal", claimable=False),
            _template("off", enabled=False),
            _template("abstract", abstract=True),
        )
        spec = ServiceSpec(
            claims=[
                ClaimSpec(alias="a", template="internal"),
                ClaimSpec(alias="b", template="off"),
                ClaimSpec(alias="c", template="abstract"),
                ClaimSpec(alias="d", template="missing"),
            ]
        )
        errors = validate_spec_against_catalog(spec, catalog)
        assert errors == [
            "Claim 'a': template 'internal' is not in the offering catalog",
            "Claim 'b': template 'off' is disabled",
            "Claim 'c': template 'abstract' is not in the offering catalog",
            "Claim 'd': template 'missing' does not exist",
        ]

    def test_pinned_version_must_belong_to_template(self):
        redis = _template("redis")
        foreign = CatalogVersion(id=uuid4(), template_id=uuid4())
        spec = ServiceSpec(claims=[ClaimSpec(alias="cache", template="redis", source_code_version_id=foreign.id)])
        errors = validate_spec_against_catalog(spec, _catalog(redis, versions=(foreign,)))
        assert errors and "is not a version of 'redis'" in errors[0]

    def test_explicit_parent_must_be_a_parent_template(self):
        redis, pg = _template("redis"), _template("pg")
        spec = ServiceSpec(
            claims=[ClaimSpec(alias="cache", template="redis"), ClaimSpec(alias="db", template="pg", parents=["cache"])]
        )
        errors = validate_spec_against_catalog(spec, _catalog(redis, pg))
        assert errors == ["Claim 'db': 'cache' (redis) is not a valid parent for template 'pg'"]

    def test_cycle_detected(self):
        a, b = _template("a"), _template("b")
        spec = ServiceSpec(
            claims=[
                ClaimSpec(alias="a", template="a", variables={"x": "${b.outputs.y}"}),
                ClaimSpec(alias="b", template="b", variables={"y": "${a.outputs.x}"}),
            ]
        )
        assert "Claims reference each other in a cycle" in validate_spec_against_catalog(spec, _catalog(a, b))


class TestCompileGreenfield:
    def test_two_claims_of_the_same_template_get_distinct_keyed_steps(self):
        redis = _template("redis", parents=(LZ_TID,))
        spec = ServiceSpec(
            claims=[
                ClaimSpec(alias="cache", template="redis", variables={"node_type": "cache.t4g.small"}),
                ClaimSpec(alias="sessions", template="redis"),
            ]
        )
        compiled = _compile(spec, _catalog(redis))

        assert compiled.plan.errors == []
        assert compiled.workflow is not None
        steps = {s.step_key: s for s in compiled.workflow.steps}
        assert set(steps) == {"cache", "sessions"}
        assert steps["cache"].template_id == steps["sessions"].template_id == redis.id
        assert steps["cache"].resolved_variables == {"node_type": "cache.t4g.small"}
        assert steps["cache"].storage_path == "state/dev-eu-central-1/checkout/cache/terraform.tfstate"
        assert steps["sessions"].storage_path == "state/dev-eu-central-1/checkout/sessions/terraform.tfstate"
        assert [i.action for i in compiled.plan.items] == [PlanAction.CREATE, PlanAction.CREATE]

    def test_environment_defaults_are_injected(self):
        redis = _template("redis", parents=(LZ_TID,))
        catalog = _catalog(redis)
        compiled = _compile(ServiceSpec(claims=[ClaimSpec(alias="cache", template="redis")]), catalog)

        assert compiled.workflow is not None
        step = compiled.workflow.steps[0]
        assert step.integration_ids == list(ENV.integration_ids)
        assert step.storage_id == ENV.storage_id
        assert step.workspace_id == ENV.workspace_id
        assert step.parent_resource_ids == [LANDING_ZONE.id]
        assert step.source_code_version_id == catalog.latest_version_by_template[redis.id]
        assert compiled.plan.items[0].parents == ["environment:eks-dev"]

    def test_anchor_satisfies_parent_before_landing_zone(self):
        iam = _template("redis_iam", parents=(ANCHOR_TID,))
        anchor = PlacedResource(id=uuid4(), template_id=ANCHOR_TID, name="checkout")
        compiled = _compile(
            ServiceSpec(claims=[ClaimSpec(alias="iam", template="redis_iam")]), _catalog(iam), anchor=anchor
        )

        assert compiled.workflow is not None
        assert compiled.workflow.steps[0].parent_resource_ids == [anchor.id]
        assert compiled.plan.items[0].parents == ["anchor:checkout"]

    def test_sibling_claim_parent_becomes_parent_step_key_and_orders_steps(self):
        redis = _template("redis", parents=(LZ_TID,))
        iam = _template("redis_iam", parents=(redis.id, ANCHOR_TID))
        anchor = PlacedResource(id=uuid4(), template_id=ANCHOR_TID, name="checkout")
        spec = ServiceSpec(
            claims=[
                ClaimSpec(alias="iam", template="redis_iam", parents=["cache"]),
                ClaimSpec(alias="cache", template="redis"),
            ]
        )
        compiled = _compile(spec, _catalog(redis, iam), anchor=anchor)

        assert compiled.workflow is not None
        steps = {s.step_key: s for s in compiled.workflow.steps}
        assert steps["iam"].parent_step_keys == ["cache"]
        assert steps["iam"].parent_resource_ids == [anchor.id]
        assert steps["cache"].position == 0 and steps["iam"].position == 1

    def test_output_references_become_keyed_wiring(self):
        redis = _template("redis", parents=(LZ_TID,))
        app = _template("app_config", parents=(LZ_TID,))
        spec = ServiceSpec(
            claims=[
                ClaimSpec(alias="cache", template="redis"),
                ClaimSpec(
                    alias="config",
                    template="app_config",
                    variables={"redis_url": "${cache.outputs.endpoint}", "ttl": 60},
                ),
            ]
        )
        compiled = _compile(spec, _catalog(redis, app))

        assert compiled.workflow is not None
        [rule] = compiled.workflow.wiring_snapshot
        assert (rule.source_step_key, rule.source_output, rule.target_step_key, rule.target_variable) == (
            "cache",
            "endpoint",
            "config",
            "redis_url",
        )
        config_step = next(s for s in compiled.workflow.steps if s.step_key == "config")
        assert config_step.resolved_variables == {"ttl": 60}
        assert config_step.position == 1
        assert compiled.plan.items[1].wires == ["redis_url \u2190 cache.outputs.endpoint"]

    def test_missing_parent_is_reported_not_raised(self):
        redis = _template("redis", parents=(uuid4(),))
        compiled = _compile(ServiceSpec(claims=[ClaimSpec(alias="cache", template="redis")]), _catalog(redis))

        assert compiled.workflow is None
        assert "needs a" in compiled.plan.errors[0] and "dev-eu-central-1" in compiled.plan.errors[0]

    def test_missing_parent_outside_catalog_is_named_by_key(self):
        vpc_tid = uuid4()
        redis = _template("redis", parents=(vpc_tid,))
        catalog = Catalog(
            templates_by_key={"redis": redis},
            latest_version_by_template={redis.id: uuid4()},
            template_key_by_id={vpc_tid: "aws_vpc"},
        )
        env = EnvironmentTarget(id=uuid4(), name="bare")
        compiled = _compile(ServiceSpec(claims=[ClaimSpec(alias="cache", template="redis")]), catalog, environment=env)

        assert compiled.plan.errors[0].startswith("Claim 'cache' needs a 'aws_vpc' parent")

    def test_ambiguous_landing_zone_is_reported(self):
        redis = _template("redis", parents=(LZ_TID,))
        env = EnvironmentTarget(
            id=uuid4(),
            name="dev",
            landing_zone=(LANDING_ZONE, PlacedResource(id=uuid4(), template_id=LZ_TID, name="eks-other")),
        )
        compiled = _compile(
            ServiceSpec(claims=[ClaimSpec(alias="cache", template="redis")]), _catalog(redis), environment=env
        )

        assert compiled.workflow is None
        assert "several" in compiled.plan.errors[0]

    def test_template_without_version_or_naming_convention_is_reported(self):
        redis = _template("redis", naming_convention=None)
        catalog = Catalog(templates_by_key={"redis": redis})
        compiled = _compile(ServiceSpec(claims=[ClaimSpec(alias="cache", template="redis")]), catalog)

        assert compiled.workflow is None
        assert compiled.plan.errors == [
            "Claim 'cache': template 'redis' has no active version; pin one",
            "Claim 'cache': template 'redis' has no naming convention",
        ]

    def test_default_storage_path_without_prefix(self):
        env = EnvironmentTarget(id=uuid4(), name="prod")
        assert default_storage_path(env, "checkout", "db") == "services/prod/checkout/db/terraform.tfstate"


def _owned(template: CatalogTemplate, alias: str, **overrides) -> OwnedResource:
    values = dict(
        alias=alias,
        role="dependency",
        id=uuid4(),
        template_id=template.id,
        name=f"{alias}-res",
        source_code_version_id=uuid4(),
        variables={"node_type": "cache.t4g.small", "engine": "7.1"},
        parent_ids=(uuid4(),),
        integration_ids=(uuid4(),),
        storage_id=uuid4(),
        storage_path="legacy/path/terraform.tfstate",
        workspace_id=uuid4(),
    )
    values.update(overrides)
    return OwnedResource(**values)


class TestCompileExistingResources:
    def test_unchanged_claim_is_a_no_op_with_pinned_placement(self):
        redis = _template("redis", parents=(LZ_TID,))
        owned = _owned(redis, "cache")
        spec = ServiceSpec(
            claims=[ClaimSpec(alias="cache", template="redis", variables={"node_type": "cache.t4g.small"})]
        )
        compiled = _compile(spec, _catalog(redis), owned=[owned])

        assert compiled.workflow is not None
        [item] = compiled.plan.items
        assert item.action == PlanAction.NO_OP and item.changes == []
        [step] = compiled.workflow.steps
        assert step.status == ModelStatus.DONE
        assert step.resource_id == owned.id
        assert step.storage_path == "legacy/path/terraform.tfstate"
        assert step.storage_id == owned.storage_id
        assert step.workspace_id == owned.workspace_id
        assert step.parent_resource_ids == list(owned.parent_ids)
        assert step.integration_ids == list(owned.integration_ids)
        assert step.source_code_version_id == owned.source_code_version_id

    def test_changed_variable_and_pinned_version_is_an_update(self):
        redis = _template("redis", parents=(LZ_TID,))
        owned = _owned(redis, "cache")
        new_version = uuid4()
        spec = ServiceSpec(
            claims=[
                ClaimSpec(
                    alias="cache",
                    template="redis",
                    source_code_version_id=new_version,
                    variables={"node_type": "cache.r7g.large"},
                )
            ]
        )
        catalog = _catalog(redis, versions=(CatalogVersion(id=new_version, template_id=redis.id),))
        compiled = _compile(spec, catalog, owned=[owned])

        [item] = compiled.plan.items
        assert item.action == PlanAction.UPDATE
        assert [(c.field, c.before, c.after) for c in item.changes] == [
            ("node_type", "cache.t4g.small", "cache.r7g.large"),
            ("source_code_version_id", str(owned.source_code_version_id), str(new_version)),
        ]
        assert compiled.workflow is not None
        step = compiled.workflow.steps[0]
        assert step.status == ModelStatus.PENDING
        assert step.resolved_variables == {"node_type": "cache.r7g.large", "engine": "7.1"}
        assert step.storage_path == "legacy/path/terraform.tfstate"

    def test_owned_resource_without_claim_is_destroyed_but_referenced_is_untouched(self):
        redis = _template("redis", parents=(LZ_TID,))
        kafka = _template("kafka")
        owned = [_owned(redis, "old_cache"), _owned(kafka, "shared_kafka", role="referenced")]
        compiled = _compile(ServiceSpec(), _catalog(redis, kafka), owned=owned)

        assert [(i.alias, i.action) for i in compiled.plan.items] == [("old_cache", PlanAction.DESTROY)]
        assert compiled.workflow is not None and compiled.workflow.steps == []

    def test_claim_colliding_with_referenced_alias_is_an_error(self):
        kafka = _template("kafka")
        owned = [_owned(kafka, "events", role="referenced")]
        compiled = _compile(
            ServiceSpec(claims=[ClaimSpec(alias="events", template="kafka")]), _catalog(kafka), owned=owned
        )

        assert compiled.workflow is None
        assert "referenced" in compiled.plan.errors[0]

    def test_changing_template_of_existing_claim_is_an_error(self):
        redis, valkey = _template("redis", parents=(LZ_TID,)), _template("valkey", parents=(LZ_TID,))
        compiled = _compile(
            ServiceSpec(claims=[ClaimSpec(alias="cache", template="valkey")]),
            _catalog(redis, valkey),
            owned=[_owned(redis, "cache")],
        )

        assert compiled.workflow is None
        assert "use a new alias" in compiled.plan.errors[0]

    def test_existing_parent_claim_resolves_to_its_resource(self):
        redis = _template("redis", parents=(LZ_TID,))
        iam = _template("redis_iam", parents=(redis.id,))
        cache = _owned(redis, "cache")
        spec = ServiceSpec(
            claims=[
                ClaimSpec(alias="cache", template="redis"),
                ClaimSpec(alias="iam", template="redis_iam", parents=["cache"]),
            ]
        )
        compiled = _compile(spec, _catalog(redis, iam), owned=[cache])

        assert compiled.workflow is not None
        iam_step = next(s for s in compiled.workflow.steps if s.step_key == "iam")
        assert iam_step.parent_resource_ids == [cache.id]
        assert iam_step.parent_step_keys == []

    def test_existing_spec_less_service_compiles_to_empty_plan(self):
        compiled = _compile(ServiceSpec(), Catalog(templates_by_key={}))

        assert compiled.plan.items == [] and compiled.plan.errors == []
        assert compiled.workflow is not None and compiled.workflow.steps == []
