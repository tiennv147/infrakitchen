from uuid import uuid4

import pytest
from sqlalchemy import inspect

from application.resources.model import Resource, resource_links
from application.service_instances.adoption import AdoptedResource, claimable_variables, reverse_compile
from application.service_instances.functions import get_service_instance_actions
from application.service_instances.migration import to_alias
from application.services.compiler import (
    Catalog,
    CatalogTemplate,
    CatalogVersion,
    EnvironmentTarget,
    OwnedResource,
    PlanAction,
    compile_service_spec,
)
from application.services.schema import ClaimSpec, ServiceSpec
from core.constants.model import ModelActions, ModelState, ModelStatus


class TestInstanceActions:
    def _actions(self, state, status, can_edit=True, owns=True):
        return get_service_instance_actions(can_edit=can_edit, state=state, status=status, owns_resources=owns)

    def test_readers_can_only_plan(self):
        assert self._actions(ModelState.PROVISIONED, ModelStatus.DONE, can_edit=False) == [ModelActions.DRYRUN]

    def test_running_instance_cannot_be_acted_on(self):
        for status in (ModelStatus.QUEUED, ModelStatus.IN_PROGRESS):
            assert self._actions(ModelState.PROVISIONED, status) == [ModelActions.DRYRUN]

    def test_pending_approval(self):
        assert self._actions(ModelState.PROVISION, ModelStatus.APPROVAL_PENDING) == [
            ModelActions.APPROVE,
            ModelActions.REJECT,
            ModelActions.DRYRUN,
        ]

    def test_deployed_owner_can_reconcile_adopt_destroy(self):
        assert self._actions(ModelState.PROVISIONED, ModelStatus.DONE) == [
            ModelActions.EXECUTE,
            ModelActions.DRYRUN,
            ModelActions.ADOPT,
            ModelActions.DESTROY,
        ]

    def test_instance_without_owned_resources_can_be_removed_instead_of_destroyed(self):
        assert ModelActions.DELETE in self._actions(ModelState.PROVISION, ModelStatus.READY, owns=False)
        assert ModelActions.DESTROY not in self._actions(ModelState.PROVISION, ModelStatus.READY, owns=False)

    def test_failed_deploy_can_retry(self):
        assert self._actions(ModelState.PROVISION, ModelStatus.ERROR)[0] == ModelActions.RETRY

    def test_failed_destroy_can_only_retry(self):
        assert self._actions(ModelState.DESTROY, ModelStatus.ERROR) == [ModelActions.RETRY, ModelActions.DRYRUN]

    def test_destroyed_instance_can_redeploy_or_be_removed(self):
        assert self._actions(ModelState.DESTROYED, ModelStatus.DONE, owns=False) == [
            ModelActions.EXECUTE,
            ModelActions.DRYRUN,
            ModelActions.DELETE,
        ]

    def test_accepts_db_enum_names(self):
        assert self._actions("PROVISIONED", "DONE")[0] == ModelActions.EXECUTE


def _adopted(alias, *, template="aws_redis", version=None, variables=None, parents=(), inherited=()):
    return AdoptedResource(
        alias=alias,
        resource_id=uuid4(),
        template_key=template,
        source_code_version_id=version,
        variables=[{"name": k, "value": v} for k, v in (variables or {}).items()],
        parent_ids=tuple(parents),
        inherited_names=frozenset(inherited),
    )


class TestReverseCompile:
    def test_sensitive_inherited_and_empty_variables_are_not_claimed(self):
        resource = AdoptedResource(
            alias="cache",
            resource_id=uuid4(),
            template_key="aws_redis",
            source_code_version_id=None,
            variables=[
                {"name": "node_type", "value": "cache.t4g.small"},
                {"name": "password", "value": "s3cret", "sensitive": True},
                {"name": "vpc_id", "value": "vpc-1"},
                {"name": "tags", "value": None},
            ],
            inherited_names=frozenset({"vpc_id"}),
        )
        assert claimable_variables(resource) == {"node_type": "cache.t4g.small"}

    def test_new_claims_are_marked_adopted_and_pinned(self):
        version = uuid4()
        cluster = _adopted("cluster", template="aws_msk", version=version, variables={"name": "events"})
        acl = _adopted("acl", template="aws_msk_acl", parents=[cluster.resource_id])
        spec, errors = reverse_compile(
            ServiceSpec(), [cluster, acl], {cluster.resource_id: "cluster", acl.resource_id: "acl"}
        )

        assert errors == []
        claims = {c.alias: c for c in spec.claims}
        assert claims["cluster"].adopted and claims["cluster"].source_code_version_id == version
        assert claims["cluster"].variables == {"name": "events"}
        assert claims["acl"].parents == ["cluster"]

    def test_second_environment_keeps_only_agreed_variables_and_unpins_different_versions(self):
        dev = _adopted("cache", version=uuid4(), variables={"node_type": "t4g.small", "engine": "7.1"})
        spec, _ = reverse_compile(ServiceSpec(), [dev], {})
        prod = _adopted("cache", version=uuid4(), variables={"node_type": "r7g.large", "engine": "7.1"})
        spec, errors = reverse_compile(spec, [prod], {})

        assert errors == []
        [claim] = spec.claims
        assert claim.variables == {"engine": "7.1"}
        assert claim.source_code_version_id is None

    def test_existing_developer_wiring_survives(self):
        spec = ServiceSpec(
            claims=[
                ClaimSpec(alias="cache", template="aws_redis"),
                ClaimSpec(alias="cfg", template="app", variables={"url": "${cache.outputs.endpoint}", "ttl": 5}),
            ]
        )
        adopted = _adopted("cfg", template="app", variables={"url": "redis://x", "ttl": 5})
        new, errors = reverse_compile(spec, [adopted], {})

        assert errors == []
        assert new.claims[1].variables == {"url": "${cache.outputs.endpoint}", "ttl": 5}

    def test_template_mismatch_is_reported(self):
        spec = ServiceSpec(claims=[ClaimSpec(alias="cache", template="aws_redis")])
        _, errors = reverse_compile(spec, [_adopted("cache", template="aws_rds")], {})
        assert errors and "aws_rds" in errors[0]


class TestAdoptionIsInert:
    """Verification #12: the first plan after adopting existing resources is all no-ops."""

    def test_plan_after_adoption_is_all_no_ops(self):
        redis = CatalogTemplate(
            id=uuid4(),
            key="aws_redis",
            name="Redis",
            enabled=True,
            abstract=False,
            claimable=False,
            naming_convention="x",
            parent_template_ids=(uuid4(),),
        )
        acl = CatalogTemplate(
            id=uuid4(),
            key="aws_msk_acl",
            name="ACL",
            enabled=False,
            abstract=False,
            claimable=False,
            naming_convention="y",
            parent_template_ids=(redis.id,),
        )
        version = uuid4()
        cache = _adopted("cache", version=version, variables={"node_type": "t4g.small"}, inherited=["vpc_id"])
        topic = _adopted("topic", template="aws_msk_acl", variables={"topic": "orders"}, parents=[cache.resource_id])
        spec, errors = reverse_compile(
            ServiceSpec(), [cache, topic], {cache.resource_id: "cache", topic.resource_id: "topic"}
        )
        assert errors == []

        owned = [
            OwnedResource(
                alias="cache",
                role="dependency",
                id=cache.resource_id,
                template_id=redis.id,
                name="c",
                source_code_version_id=version,
                variables={"node_type": "t4g.small", "vpc_id": "vpc-9"},
            ),
            OwnedResource(
                alias="topic",
                role="dependency",
                id=topic.resource_id,
                template_id=acl.id,
                name="t",
                source_code_version_id=None,
                variables={"topic": "orders"},
                parent_ids=(cache.resource_id,),
            ),
            OwnedResource(
                alias="shared",
                role="referenced",
                id=uuid4(),
                template_id=uuid4(),
                name="s",
                source_code_version_id=None,
            ),
        ]
        compiled = compile_service_spec(
            service_id=uuid4(),
            service_name="svc",
            spec=spec,
            catalog=Catalog(
                templates_by_key={"aws_redis": redis, "aws_msk_acl": acl},
                versions={version: CatalogVersion(id=version, template_id=redis.id)},
            ),
            environment=EnvironmentTarget(id=uuid4(), name="dev"),
            owned=owned,
            created_by=uuid4(),
        )

        assert compiled.plan.errors == []
        assert [(i.alias, i.action) for i in compiled.plan.items] == [
            ("cache", PlanAction.NO_OP),
            ("topic", PlanAction.NO_OP),
        ]
        assert compiled.workflow is not None
        assert all(step.status == ModelStatus.DONE for step in compiled.workflow.steps)

    def test_unsettled_owned_resource_plans_an_update(self):
        redis = CatalogTemplate(
            id=uuid4(),
            key="aws_redis",
            name="Redis",
            enabled=True,
            abstract=False,
            claimable=True,
            naming_convention="x",
        )
        owned = OwnedResource(
            alias="cache",
            role="dependency",
            id=uuid4(),
            template_id=redis.id,
            name="c",
            source_code_version_id=None,
            state="provision",
            status="error",
        )
        compiled = compile_service_spec(
            service_id=uuid4(),
            service_name="svc",
            spec=ServiceSpec(claims=[ClaimSpec(alias="cache", template="aws_redis")]),
            catalog=Catalog(templates_by_key={"aws_redis": redis}),
            environment=EnvironmentTarget(id=uuid4(), name="dev"),
            owned=[owned],
            created_by=uuid4(),
        )

        [item] = compiled.plan.items
        assert item.action == PlanAction.UPDATE
        assert [(c.field, c.before) for c in item.changes] == [("state", "provision/error")]
        assert compiled.workflow is not None and compiled.workflow.steps[0].status == ModelStatus.PENDING


class TestMigrationAliases:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("shop-dev-eu-west-1-shop-order-api-order_events-topic", "order_events_topic"),
            ("shop-prod-eu-central-1-shop-order-api-sa", "sa"),
            ("shop-dev-eu-west-1-edge-msk-shop-order-api-iam", "edge_msk_iam"),
            ("shop-dev-eu-west-1-shared-msk", "shared_msk"),
        ],
    )
    def test_aliases_drop_environment_and_anchor(self, name, expected):
        assert to_alias(name, "shop-order-api", "aws_msk_acl") == expected

    def test_same_resource_in_two_environments_gets_the_same_alias(self):
        dev = to_alias("shop-dev-eu-west-1-shop-cart-api-sa", "shop-cart-api", "k8s_service_account_iam")
        prod = to_alias("shop-prod-us-east-1-shop-cart-api-sa", "shop-cart-api", "k8s_service_account_iam")
        assert dev == prod == "sa"

    def test_falls_back_to_template_key(self):
        assert to_alias("123", "anchor", "aws_msk") == "aws_msk"


class TestResourceLinksDirection:
    """Verification #17: resource_links.parent_id holds the dependent resource. Migration SQL relies on it."""

    def test_parents_relationship_reads_dependency_from_child_id(self):
        relationship = inspect(Resource).relationships["parents"]
        assert relationship.secondary is resource_links
        local = {c.name for c in relationship.local_columns}
        assert local == {"id"}
        assert str(relationship.primaryjoin).endswith("resource_links.parent_id")
        assert str(relationship.secondaryjoin).endswith("resource_links.child_id")
