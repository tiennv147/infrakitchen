"""Binding sinks: AWS Secrets Manager (the shared chart's existing contract) and Kubernetes Secrets."""

import base64
import json
import re
from typing import Any, override

from botocore.exceptions import ClientError
from kubernetes_asyncio.client import ApiClient, Configuration, CoreV1Api, CustomObjectsApi, V1ObjectMeta, V1Secret
from kubernetes_asyncio.client.exceptions import ApiException

from application.providers.aws.aws_client import AwsSecretManagerClient
from core.adapters.provider_adapters import BindingSinkAdapter

MANAGED_BY = "infrakitchen"
_AWS_SECRET_NAME = re.compile(r"^[A-Za-z0-9/_+=.@-]{1,512}$")
_K8S_NAME = re.compile(r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$")

SPC_GROUP = "secrets-store.csi.x-k8s.io"
SPC_VERSION = "v1"
SPC_PLURAL = "secretproviderclasses"


def _check(pattern: re.Pattern[str], name: str, what: str) -> None:
    if not pattern.match(name):
        raise ValueError(f"'{name}' is not a valid {what} name")


class AwsSecretsManagerSink(BindingSinkAdapter):
    """One JSON secret per path; read by pods through the Secrets Store CSI driver."""

    __binding_sink_name__: str = "aws_secrets_manager"

    def __init__(self, environment_variables: dict[str, str], region: str) -> None:
        self.client_factory = AwsSecretManagerClient(environment_variables, region)

    @override
    async def read(self, path: str) -> dict[str, str] | None:
        _check(_AWS_SECRET_NAME, path, "AWS secret")
        async with self.client_factory.client as sm:
            try:
                result = await sm.get_secret_value(SecretId=path)
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                    return None
                raise
        document = json.loads(result.get("SecretString") or "{}")
        if not isinstance(document, dict):
            raise ValueError(f"Secret {path} is not a JSON object; refusing to overwrite it")
        return {str(k): v if isinstance(v, str) else json.dumps(v) for k, v in document.items()}

    @override
    async def write(self, path: str, payload: dict[str, str]) -> bool:
        _check(_AWS_SECRET_NAME, path, "AWS secret")
        body = json.dumps(payload, sort_keys=True)
        async with self.client_factory.client as sm:
            try:
                await sm.put_secret_value(SecretId=path, SecretString=body)
                return False
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                    raise
            await sm.create_secret(
                Name=path,
                SecretString=body,
                Description="Service bindings managed by InfraKitchen",
                Tags=[{"Key": "managed-by", "Value": MANAGED_BY}],
            )
            return True

    @override
    async def delete(self, path: str) -> None:
        _check(_AWS_SECRET_NAME, path, "AWS secret")
        async with self.client_factory.client as sm:
            try:
                # Recoverable for 7 days in case a binding is removed by mistake.
                await sm.delete_secret(SecretId=path, RecoveryWindowInDays=7)
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                    raise


class KubernetesSecretSink(BindingSinkAdapter):
    """One Opaque Secret per path in the service's namespace."""

    __binding_sink_name__: str = "kubernetes_secret"

    def __init__(self, configuration: Configuration, namespace: str) -> None:
        _check(_K8S_NAME, namespace, "Kubernetes namespace")
        self.configuration = configuration
        self.namespace = namespace

    @override
    async def read(self, path: str) -> dict[str, str] | None:
        _check(_K8S_NAME, path, "Kubernetes secret")
        async with ApiClient(self.configuration) as api:
            try:
                secret = await CoreV1Api(api).read_namespaced_secret(path, self.namespace)
            except ApiException as e:
                if e.status == 404:
                    return None
                raise
        return {k: base64.b64decode(v).decode() for k, v in (secret.data or {}).items()}

    @override
    async def write(self, path: str, payload: dict[str, str]) -> bool:
        _check(_K8S_NAME, path, "Kubernetes secret")
        body = V1Secret(
            metadata=V1ObjectMeta(
                name=path, namespace=self.namespace, labels={"app.kubernetes.io/managed-by": MANAGED_BY}
            ),
            type="Opaque",
            data={k: base64.b64encode(v.encode()).decode() for k, v in payload.items()},
        )
        async with ApiClient(self.configuration) as api:
            core = CoreV1Api(api)
            try:
                await core.replace_namespaced_secret(path, self.namespace, body)
                return False
            except ApiException as e:
                if e.status != 404:
                    raise
            await core.create_namespaced_secret(self.namespace, body)
            return True

    @override
    async def delete(self, path: str) -> None:
        _check(_K8S_NAME, path, "Kubernetes secret")
        async with ApiClient(self.configuration) as api:
            try:
                await CoreV1Api(api).delete_namespaced_secret(path, self.namespace)
            except ApiException as e:
                if e.status != 404:
                    raise


def secret_provider_class_body(name: str, namespace: str, secret_path: str, keys: list[str]) -> dict[str, Any]:
    """AWS provider class exposing each binding key as a file under the pod's mount path."""
    objects = [
        {
            "objectName": secret_path,
            "objectType": "secretsmanager",
            "jmesPath": [{"path": key, "objectAlias": key} for key in keys],
        }
    ]
    return {
        "apiVersion": f"{SPC_GROUP}/{SPC_VERSION}",
        "kind": "SecretProviderClass",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {"app.kubernetes.io/managed-by": MANAGED_BY},
        },
        "spec": {"provider": "aws", "parameters": {"objects": json.dumps(objects)}},
    }


async def ensure_secret_provider_class(
    configuration: Configuration, namespace: str, name: str, secret_path: str, keys: list[str]
) -> str:
    """Create the class when absent. Returns 'created', 'updated' (ours) or 'existing' (someone else's)."""
    _check(_K8S_NAME, name, "SecretProviderClass")
    body = secret_provider_class_body(name, namespace, secret_path, keys)
    async with ApiClient(configuration) as api:
        custom = CustomObjectsApi(api)
        try:
            current = await custom.get_namespaced_custom_object(SPC_GROUP, SPC_VERSION, namespace, SPC_PLURAL, name)
        except ApiException as e:
            if e.status != 404:
                raise
            await custom.create_namespaced_custom_object(SPC_GROUP, SPC_VERSION, namespace, SPC_PLURAL, body)
            return "created"
        labels = (current.get("metadata") or {}).get("labels") or {}
        if labels.get("app.kubernetes.io/managed-by") != MANAGED_BY:
            return "existing"
        body["metadata"]["resourceVersion"] = current["metadata"]["resourceVersion"]
        await custom.replace_namespaced_custom_object(SPC_GROUP, SPC_VERSION, namespace, SPC_PLURAL, name, body)
        return "updated"


async def delete_secret_provider_class(configuration: Configuration, namespace: str, name: str) -> None:
    async with ApiClient(configuration) as api:
        try:
            await CustomObjectsApi(api).delete_namespaced_custom_object(
                SPC_GROUP, SPC_VERSION, namespace, SPC_PLURAL, name
            )
        except ApiException as e:
            if e.status != 404:
                raise
