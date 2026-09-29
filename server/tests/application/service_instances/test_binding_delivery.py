from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from application.service_instances import binding_delivery as delivery_module
from application.service_instances.binding_delivery import BindingDelivery
from core.adapters.provider_adapters import BindingSinkAdapter
from core.errors import CannotProceed


class FakeSink(BindingSinkAdapter):
    __binding_sink_name__ = "fake_for_tests"

    def __init__(self, documents=None):
        self.documents: dict[str, dict[str, str]] = documents or {}
        self.deleted: list[str] = []

    async def read(self, path):
        return dict(self.documents[path]) if path in self.documents else None

    async def write(self, path, payload):
        created = path not in self.documents
        self.documents[path] = dict(payload)
        return created

    async def delete(self, path):
        self.documents.pop(path, None)
        self.deleted.append(path)


def _link(alias, outputs, role="dependency"):
    return SimpleNamespace(
        alias=alias,
        role=role,
        resource=SimpleNamespace(
            name=f"{alias}-res",
            outputs=[{"name": k, "value": v, "sensitive": False} for k, v in outputs.items()],
            template=SimpleNamespace(template="aws_redis", configuration={}),
        ),
    )


def _setup(bindings, *, state=None, sink_config=None, documents=None):
    service = SimpleNamespace(name="checkout", spec={"bindings": bindings})
    environment = SimpleNamespace(name="dev", region="eu-west-1", binding_sink=sink_config, integration_ids=[])
    instance = SimpleNamespace(resources=[_link("cache", {"host": "redis.local"})], binding_state=state)
    delivery = BindingDelivery(session=None)  # type: ignore[arg-type]
    sink = FakeSink(documents)
    delivery._sink = AsyncMock(return_value=sink)  # type: ignore[method-assign]
    return delivery, instance, service, environment, sink


REDIS = {"key": "REDIS_HOST", "value": "${cache.outputs.host}"}


class TestApply:
    @pytest.mark.asyncio
    async def test_creates_the_secret_and_records_what_it_manages(self):
        delivery, instance, service, environment, sink = _setup([REDIS])

        state = await delivery.apply(instance, service, environment)

        assert sink.documents == {"config-checkout": {"REDIS_HOST": "redis.local"}}
        assert state is not None
        assert (state["path"], state["keys"], state["created"]) == ("config-checkout", ["REDIS_HOST"], True)

    @pytest.mark.asyncio
    async def test_existing_keys_written_by_others_survive(self):
        delivery, instance, service, environment, sink = _setup(
            [REDIS], documents={"config-checkout": {"FEATURE_X": "on"}}
        )

        state = await delivery.apply(instance, service, environment)

        assert sink.documents["config-checkout"] == {"FEATURE_X": "on", "REDIS_HOST": "redis.local"}
        assert state is not None and state["created"] is False

    @pytest.mark.asyncio
    async def test_removed_binding_is_removed_from_the_secret(self):
        previous = {"path": "config-checkout", "keys": ["OLD_KEY", "REDIS_HOST"], "created": False}
        delivery, instance, service, environment, sink = _setup(
            [REDIS], state=previous, documents={"config-checkout": {"OLD_KEY": "x", "REDIS_HOST": "old", "OTHER": "y"}}
        )

        await delivery.apply(instance, service, environment)

        assert sink.documents["config-checkout"] == {"REDIS_HOST": "redis.local", "OTHER": "y"}

    @pytest.mark.asyncio
    async def test_path_change_cleans_the_old_location(self):
        previous = {"path": "config-old", "keys": ["REDIS_HOST"], "created": True}
        delivery, instance, service, environment, sink = _setup(
            [REDIS], state=previous, documents={"config-old": {"REDIS_HOST": "old"}}
        )

        await delivery.apply(instance, service, environment)

        assert "config-old" in sink.deleted
        assert sink.documents == {"config-checkout": {"REDIS_HOST": "redis.local"}}

    @pytest.mark.asyncio
    async def test_render_errors_stop_before_touching_the_sink(self):
        delivery, instance, service, environment, sink = _setup([{"key": "X", "value": "${missing.outputs.host}"}])

        with pytest.raises(CannotProceed, match="Cannot render bindings"):
            await delivery.apply(instance, service, environment)
        delivery._sink.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_no_bindings_and_nothing_written_before_is_a_no_op(self):
        delivery, instance, service, environment, _ = _setup([])
        assert await delivery.apply(instance, service, environment) is None
        delivery._sink.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_build_bindings_are_never_written_to_the_sink(self):
        delivery, instance, service, environment, sink = _setup(
            [REDIS, {"key": "ECR_REPO", "value": "repo", "scope": "build"}]
        )
        await delivery.apply(instance, service, environment)
        assert sink.documents["config-checkout"] == {"REDIS_HOST": "redis.local"}

    @pytest.mark.asyncio
    async def test_secret_provider_class_is_ensured_when_configured(self, monkeypatch):
        ensure = AsyncMock(return_value="created")
        monkeypatch.setattr(delivery_module, "ensure_secret_provider_class", ensure)
        config = {"secret_provider_class": True, "cluster_resource_id": str(uuid4()), "namespace": "shop"}
        delivery, instance, service, environment, _ = _setup([REDIS], sink_config=config)
        delivery._cluster = AsyncMock(return_value="k8s-config")  # type: ignore[method-assign]

        state = await delivery.apply(instance, service, environment)

        ensure.assert_awaited_once_with("k8s-config", "shop", "checkout", "config-checkout", ["REDIS_HOST"])
        assert state is not None and state["spc"] == {
            "name": "checkout",
            "namespace": "shop",
            "created": True,
            "status": "created",
        }

    @pytest.mark.asyncio
    async def test_turning_the_sink_off_removes_what_was_written(self):
        previous = {"sink": "aws_secrets_manager", "path": "config-checkout", "keys": ["REDIS_HOST"], "created": True}
        delivery, instance, service, environment, sink = _setup(
            [REDIS], state=previous, sink_config={"type": "none"}, documents={"config-checkout": {"REDIS_HOST": "x"}}
        )

        assert await delivery.apply(instance, service, environment) is None
        assert sink.deleted == ["config-checkout"]


class TestRemove:
    @pytest.mark.asyncio
    async def test_secret_we_created_is_deleted_when_empty(self):
        previous = {"sink": "aws_secrets_manager", "path": "config-checkout", "keys": ["REDIS_HOST"], "created": True}
        delivery, instance, service, environment, sink = _setup(
            [REDIS], state=previous, documents={"config-checkout": {"REDIS_HOST": "x"}}
        )
        await delivery.remove(instance, service, environment)
        assert sink.deleted == ["config-checkout"]

    @pytest.mark.asyncio
    async def test_shared_secret_keeps_other_keys(self):
        previous = {"sink": "aws_secrets_manager", "path": "config-checkout", "keys": ["REDIS_HOST"], "created": False}
        delivery, instance, service, environment, sink = _setup(
            [REDIS], state=previous, documents={"config-checkout": {"REDIS_HOST": "x", "FEATURE_X": "on"}}
        )
        await delivery.remove(instance, service, environment)
        assert sink.documents["config-checkout"] == {"FEATURE_X": "on"}
        assert sink.deleted == []

    @pytest.mark.asyncio
    async def test_secret_someone_else_created_is_never_deleted(self):
        previous = {"sink": "aws_secrets_manager", "path": "config-checkout", "keys": ["REDIS_HOST"], "created": False}
        delivery, instance, service, environment, sink = _setup(
            [REDIS], state=previous, documents={"config-checkout": {"REDIS_HOST": "x"}}
        )
        await delivery.remove(instance, service, environment)
        assert sink.deleted == [] and sink.documents["config-checkout"] == {}

    @pytest.mark.asyncio
    async def test_only_our_secret_provider_class_is_deleted(self, monkeypatch):
        delete = AsyncMock()
        monkeypatch.setattr(delivery_module, "delete_secret_provider_class", delete)
        previous = {
            "sink": "aws_secrets_manager",
            "path": "config-checkout",
            "keys": [],
            "created": False,
            "spc": {"name": "checkout", "namespace": "shop", "created": False, "status": "existing"},
        }
        delivery, instance, service, environment, _ = _setup([REDIS], state=previous)
        await delivery.remove(instance, service, environment)
        delete.assert_not_awaited()
