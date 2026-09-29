from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from application.environments.schema import BindingSinkConfig
from application.service_instances.binding_delivery import target_for
from application.service_instances.bindings import (
    BoundOutput,
    BoundResource,
    merge_managed,
    render_bindings,
)
from application.services.compiler import Catalog, CatalogTemplate, validate_spec_against_catalog
from application.services.schema import BindingSpec, ClaimSpec, ServiceSpec


def _resource(alias="cache", *, outputs=None, published=(), role="dependency", template="aws_redis"):
    return BoundResource(
        alias=alias,
        role=role,
        name=f"{alias}-resource",
        template_key=template,
        binding_outputs=tuple(published),
        outputs={k: v if isinstance(v, BoundOutput) else BoundOutput(v) for k, v in (outputs or {}).items()},
    )


def _render(*bindings, resources):
    return render_bindings(list(bindings), {r.alias: r for r in resources})


class TestRender:
    def test_interpolates_several_references_into_text(self):
        cache = _resource(outputs={"host": "redis.internal", "port": 6379})
        rendered = _render(
            BindingSpec(key="REDIS_URL", value="redis://${cache.outputs.host}:${cache.outputs.port}/0"),
            resources=[cache],
        )

        assert rendered.errors == []
        assert rendered.payload("runtime") == {"REDIS_URL": "redis://redis.internal:6379/0"}
        assert rendered.items[0].sources == ["cache.outputs.host", "cache.outputs.port"]

    def test_referenced_resources_can_be_bound(self):
        kafka = _resource("shared_kafka", role="referenced", outputs={"brokers": "b-1:9098"}, template="aws_msk")
        rendered = _render(BindingSpec(key="KAFKA_BROKERS", value="${shared_kafka.outputs.brokers}"), resources=[kafka])

        assert rendered.payload("runtime") == {"KAFKA_BROKERS": "b-1:9098"}

    def test_literal_bindings_need_no_resources(self):
        rendered = _render(BindingSpec(key="LOG_LEVEL", value="info"), resources=[])
        assert rendered.payload("runtime") == {"LOG_LEVEL": "info"}

    def test_structured_output_values_are_json(self):
        cache = _resource(outputs={"nodes": ["a", "b"]})
        rendered = _render(BindingSpec(key="NODES", value="${cache.outputs.nodes}"), resources=[cache])
        assert rendered.payload("runtime") == {"NODES": '["a", "b"]'}

    def test_unknown_alias_missing_output_and_unpublished_output_are_errors(self):
        cache = _resource(outputs={"host": "h", "password": "p"}, published=["host", "port"])
        rendered = _render(
            BindingSpec(key="A", value="${nope.outputs.host}"),
            BindingSpec(key="B", value="${cache.outputs.port}"),
            BindingSpec(key="C", value="${cache.outputs.password}"),
            BindingSpec(key="D", value="${cache.outputs.host}"),
            resources=[cache],
        )

        assert rendered.payload("runtime") == {"D": "h"}
        assert len(rendered.errors) == 3
        assert "neither a claim nor a referenced resource" in rendered.errors[0]
        assert "has no output 'port' yet" in rendered.errors[1]
        assert "not published for binding" in rendered.errors[2]

    def test_sensitive_outputs_are_runtime_only(self):
        db = _resource("db", outputs={"password": BoundOutput("s3cret", sensitive=True)})
        rendered = _render(
            BindingSpec(key="DB_PASSWORD", value="${db.outputs.password}"),
            BindingSpec(key="LEAK", value="${db.outputs.password}", scope="build"),
            resources=[db],
        )

        assert rendered.items[0].sensitive is True
        assert rendered.payload("build") == {}
        assert rendered.errors_for("build") == ["LEAK: sensitive output 'db.password' cannot be a build binding"]
        assert rendered.errors_for("runtime") == []

    def test_build_and_runtime_are_split(self):
        ecr = _resource("registry", outputs={"url": "123.dkr.ecr/app"}, template="aws_ecr")
        rendered = _render(
            BindingSpec(key="ECR_REPO", value="${registry.outputs.url}", scope="build"),
            BindingSpec(key="IMAGE", value="${registry.outputs.url}"),
            resources=[ecr],
        )
        assert rendered.payload("build") == {"ECR_REPO": "123.dkr.ecr/app"}
        assert rendered.payload("runtime") == {"IMAGE": "123.dkr.ecr/app"}


class TestMergeManaged:
    def test_foreign_keys_survive_and_managed_keys_are_replaced(self):
        existing = {"FEATURE_FLAG": "on", "REDIS_URL": "old", "STALE": "x"}
        merged = merge_managed(existing, {"REDIS_URL": "new", "DB_URL": "db"}, managed_before={"REDIS_URL", "STALE"})
        assert merged == {"FEATURE_FLAG": "on", "REDIS_URL": "new", "DB_URL": "db"}

    def test_a_foreign_key_with_the_same_name_is_taken_over(self):
        assert merge_managed({"REDIS_URL": "hand-made"}, {"REDIS_URL": "managed"}, set()) == {"REDIS_URL": "managed"}


class TestSpec:
    def test_duplicate_binding_keys_rejected(self):
        with pytest.raises(ValidationError, match="Duplicate binding keys: A"):
            ServiceSpec(bindings=[BindingSpec(key="A", value="1"), BindingSpec(key="A", value="2")])

    @pytest.mark.parametrize("key", ["1BAD", "has space", ""])
    def test_bad_keys_rejected(self, key):
        with pytest.raises(ValidationError):
            BindingSpec(key=key, value="x")

    def test_malformed_reference_rejected(self):
        with pytest.raises(ValidationError, match="Unsupported reference"):
            BindingSpec(key="A", value="${cache.host}")

    def test_catalog_rejects_unpublished_outputs_at_save_time(self):
        redis = CatalogTemplate(
            id=uuid4(),
            key="aws_redis",
            name="Redis",
            enabled=True,
            abstract=False,
            claimable=True,
            naming_convention="x",
            binding_outputs=("redis_primary_endpoint",),
        )
        spec = ServiceSpec(
            claims=[ClaimSpec(alias="cache", template="aws_redis")],
            bindings=[
                BindingSpec(key="OK", value="${cache.outputs.redis_primary_endpoint}"),
                BindingSpec(key="NO", value="${cache.outputs.iam_user_arn}"),
                BindingSpec(key="REF", value="${shared_kafka.outputs.brokers}"),
            ],
        )
        errors = validate_spec_against_catalog(spec, Catalog(templates_by_key={"aws_redis": redis}))
        assert errors == [
            "Binding 'NO': output 'iam_user_arn' of 'aws_redis' is not published for binding "
            "(allowed: redis_primary_endpoint)"
        ]


class TestSinkConfig:
    def test_defaults_to_the_chart_contract(self):
        config = BindingSinkConfig()
        assert (config.type, config.path_template) == ("aws_secrets_manager", "config-{service_name}")

    def test_kubernetes_needs_a_cluster(self):
        with pytest.raises(ValidationError, match="cluster_resource_id"):
            BindingSinkConfig(type="kubernetes_secret")
        with pytest.raises(ValidationError, match="cluster_resource_id"):
            BindingSinkConfig(secret_provider_class=True)

    def test_unknown_placeholder_rejected(self):
        with pytest.raises(ValidationError, match="Unknown placeholder"):
            BindingSinkConfig(path_template="config-{team}")

    def test_target_resolves_names_per_environment(self):
        environment = SimpleNamespace(
            name="shop-staging-us-east-1",
            region="us-east-1",
            binding_sink={"path_template": "{environment}/config-{service_name}", "namespace": "checkout"},
        )
        target = target_for(environment, SimpleNamespace(name="checkout-api"))  # type: ignore[arg-type]
        assert target.path == "shop-staging-us-east-1/config-checkout-api"
        assert target.namespace == "checkout"
        assert target.secret_provider_class == "checkout-api"
        assert target.mount_path == "/secrets"

    def test_sink_can_be_turned_off(self):
        environment = SimpleNamespace(name="dev", region="eu-west-1", binding_sink={"type": "none"})
        target = target_for(environment, SimpleNamespace(name="svc"))  # type: ignore[arg-type]
        assert target.path is None and target.mount_path is None
