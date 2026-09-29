import base64
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from botocore.exceptions import ClientError
from kubernetes_asyncio.client.exceptions import ApiException

from application.service_instances import binding_sinks
from application.service_instances.binding_sinks import (
    AwsSecretsManagerSink,
    KubernetesSecretSink,
    ensure_secret_provider_class,
    secret_provider_class_body,
)


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "op")


def _aws_sink(sm: AsyncMock) -> AwsSecretsManagerSink:
    sink = AwsSecretsManagerSink.__new__(AwsSecretsManagerSink)

    @asynccontextmanager
    async def client():
        yield sm

    sink.client_factory = Mock()
    type(sink.client_factory).client = property(lambda _self: client())
    return sink


class TestAwsSecretsManagerSink:
    @pytest.mark.asyncio
    async def test_read_missing_secret_is_none(self):
        sm = AsyncMock()
        sm.get_secret_value.side_effect = _client_error("ResourceNotFoundException")
        assert await _aws_sink(sm).read("config-svc") is None

    @pytest.mark.asyncio
    async def test_read_refuses_non_object_documents(self):
        sm = AsyncMock()
        sm.get_secret_value.return_value = {"SecretString": '"plain"'}
        with pytest.raises(ValueError, match="not a JSON object"):
            await _aws_sink(sm).read("config-svc")

    @pytest.mark.asyncio
    async def test_write_updates_existing_secret(self):
        sm = AsyncMock()
        created = await _aws_sink(sm).write("config-svc", {"B": "2", "A": "1"})

        assert created is False
        assert sm.put_secret_value.await_args.kwargs == {
            "SecretId": "config-svc",
            "SecretString": '{"A": "1", "B": "2"}',
        }
        sm.create_secret.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_write_creates_a_tagged_secret_when_missing(self):
        sm = AsyncMock()
        sm.put_secret_value.side_effect = _client_error("ResourceNotFoundException")

        assert await _aws_sink(sm).write("config-svc", {"A": "1"}) is True
        kwargs = sm.create_secret.await_args.kwargs
        assert kwargs["Name"] == "config-svc"
        assert json.loads(kwargs["SecretString"]) == {"A": "1"}
        assert {"Key": "managed-by", "Value": "infrakitchen"} in kwargs["Tags"]

    @pytest.mark.asyncio
    async def test_other_errors_are_not_swallowed(self):
        sm = AsyncMock()
        sm.put_secret_value.side_effect = _client_error("AccessDeniedException")
        with pytest.raises(ClientError):
            await _aws_sink(sm).write("config-svc", {"A": "1"})

    @pytest.mark.asyncio
    async def test_delete_is_recoverable_and_tolerates_missing(self):
        sm = AsyncMock()
        sm.delete_secret.side_effect = _client_error("ResourceNotFoundException")
        await _aws_sink(sm).delete("config-svc")
        assert sm.delete_secret.await_args.kwargs == {"SecretId": "config-svc", "RecoveryWindowInDays": 7}

    @pytest.mark.asyncio
    async def test_invalid_names_never_reach_aws(self):
        sm = AsyncMock()
        with pytest.raises(ValueError, match="not a valid AWS secret name"):
            await _aws_sink(sm).write("bad name!", {})
        sm.put_secret_value.assert_not_awaited()


@pytest.fixture
def k8s(monkeypatch):
    core, custom = AsyncMock(), AsyncMock()

    @asynccontextmanager
    async def api_client(_configuration):
        yield Mock()

    monkeypatch.setattr(binding_sinks, "ApiClient", api_client)
    monkeypatch.setattr(binding_sinks, "CoreV1Api", lambda _api: core)
    monkeypatch.setattr(binding_sinks, "CustomObjectsApi", lambda _api: custom)
    return SimpleK8s(core=core, custom=custom)


class SimpleK8s:
    def __init__(self, core, custom):
        self.core, self.custom = core, custom


class TestKubernetesSecretSink:
    @pytest.mark.asyncio
    async def test_round_trip_is_base64(self, k8s):
        sink = KubernetesSecretSink(Mock(), "checkout")
        k8s.core.replace_namespaced_secret.side_effect = ApiException(status=404)

        assert await sink.write("config-checkout", {"A": "1"}) is True
        body = k8s.core.create_namespaced_secret.await_args.args[1]
        assert base64.b64decode(body.data["A"]).decode() == "1"
        assert body.metadata.labels == {"app.kubernetes.io/managed-by": "infrakitchen"}

        k8s.core.read_namespaced_secret.return_value = Mock(data=body.data)
        assert await sink.read("config-checkout") == {"A": "1"}

    @pytest.mark.asyncio
    async def test_missing_secret_reads_as_none(self, k8s):
        k8s.core.read_namespaced_secret.side_effect = ApiException(status=404)
        assert await KubernetesSecretSink(Mock(), "checkout").read("config-checkout") is None

    def test_invalid_namespace_rejected(self):
        with pytest.raises(ValueError, match="namespace"):
            KubernetesSecretSink(Mock(), "Bad_Namespace")


class TestSecretProviderClass:
    def test_body_maps_each_key_to_a_file(self):
        body = secret_provider_class_body("svc", "ns", "config-svc", ["A", "B"])
        [obj] = json.loads(body["spec"]["parameters"]["objects"])
        assert obj["objectName"] == "config-svc" and obj["objectType"] == "secretsmanager"
        assert [p["objectAlias"] for p in obj["jmesPath"]] == ["A", "B"]

    @pytest.mark.asyncio
    async def test_created_when_absent(self, k8s):
        k8s.custom.get_namespaced_custom_object.side_effect = ApiException(status=404)
        assert await ensure_secret_provider_class(Mock(), "ns", "svc", "config-svc", ["A"]) == "created"
        k8s.custom.create_namespaced_custom_object.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_hand_made_class_is_never_changed(self, k8s):
        k8s.custom.get_namespaced_custom_object.return_value = {"metadata": {"name": "svc", "resourceVersion": "1"}}
        assert await ensure_secret_provider_class(Mock(), "ns", "svc", "config-svc", ["A"]) == "existing"
        k8s.custom.replace_namespaced_custom_object.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_our_class_is_kept_in_sync(self, k8s):
        k8s.custom.get_namespaced_custom_object.return_value = {
            "metadata": {"resourceVersion": "7", "labels": {"app.kubernetes.io/managed-by": "infrakitchen"}}
        }
        assert await ensure_secret_provider_class(Mock(), "ns", "svc", "config-svc", ["A"]) == "updated"
        body = k8s.custom.replace_namespaced_custom_object.await_args.args[-1]
        assert body["metadata"]["resourceVersion"] == "7"


def test_sinks_are_registered():
    from core.adapters.provider_adapters import BindingSinkAdapter

    assert BindingSinkAdapter.adapters["aws_secrets_manager"] is AwsSecretsManagerSink
    assert BindingSinkAdapter.adapters["kubernetes_secret"] is KubernetesSecretSink
