"""Deliver a service instance's bindings: preview (read-only), apply (reconciler) and remove (destroy)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from kubernetes_asyncio.client import Configuration
from sqlalchemy.ext.asyncio import AsyncSession

from application.environments.model import Environment
from application.environments.schema import BindingSinkConfig
from application.integrations.dependencies import get_integration_service
from application.providers.kubernetes.kubernetes_integration import build_kubernetes_client
from application.resources.dependencies import get_resource_service
from application.services.model import Service
from application.services.schema import ServiceSpec
from core.adapters.functions import get_integration_adapter
from core.adapters.provider_adapters import BindingSinkAdapter
from core.errors import CannotProceed

from .binding_sinks import (
    AwsSecretsManagerSink,
    KubernetesSecretSink,
    delete_secret_provider_class,
    ensure_secret_provider_class,
)
from .bindings import BoundOutput, BoundResource, RenderedBindings, merge_managed, render_bindings, render_name
from .model import ServiceInstance

# Where the shared chart mounts the Secrets Manager provider class (enable_secret_manager: true).
SECRETS_MOUNT_PATH = "/secrets"


@dataclass
class BindingTarget:
    config: BindingSinkConfig
    path: str | None
    namespace: str
    secret_provider_class: str | None
    mount_path: str | None


@dataclass
class BindingPreview:
    target: BindingTarget
    rendered: RenderedBindings
    applied: dict[str, Any] | None = field(default=None)


def bound_resources(instance: ServiceInstance) -> dict[str, BoundResource]:
    resources: dict[str, BoundResource] = {}
    for link in instance.resources:
        resource = link.resource
        configuration = (resource.template.configuration if resource.template else None) or {}
        outputs = {
            o["name"]: BoundOutput(value=o.get("value"), sensitive=bool(o.get("sensitive")))
            for o in resource.outputs or []
            if isinstance(o, dict) and "name" in o
        }
        resources[link.alias] = BoundResource(
            alias=link.alias,
            role=link.role,
            name=resource.name,
            template_key=resource.template.template if resource.template else "",
            binding_outputs=tuple(configuration.get("binding_outputs") or ()),
            outputs=outputs,
        )
    return resources


def target_for(environment: Environment, service: Service) -> BindingTarget:
    config = BindingSinkConfig.model_validate(environment.binding_sink or {})

    def name(template: str) -> str:
        return render_name(template, service_name=service.name, environment=environment.name, region=environment.region)

    if config.type == "none":
        return BindingTarget(config=config, path=None, namespace="", secret_provider_class=None, mount_path=None)
    return BindingTarget(
        config=config,
        path=name(config.path_template),
        namespace=config.namespace or service.name,
        secret_provider_class=name(config.secret_provider_class_name) if config.type == "aws_secrets_manager" else None,
        mount_path=SECRETS_MOUNT_PATH if config.type == "aws_secrets_manager" else None,
    )


def preview(instance: ServiceInstance, service: Service, environment: Environment) -> BindingPreview:
    spec = ServiceSpec.model_validate(service.spec or {})
    return BindingPreview(
        target=target_for(environment, service),
        rendered=render_bindings(spec.bindings, bound_resources(instance)),
        applied=instance.binding_state,
    )


class BindingDelivery:
    """Talks to the sink. Only the reconciler uses this; previews never touch external systems."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _credentials(self, environment: Environment, config: BindingSinkConfig) -> dict[str, str]:
        integration_id = config.integration_id or next(
            (i.id for i in environment.integration_ids if i.integration_provider == "aws"), None
        )
        if integration_id is None:
            raise CannotProceed(f"Environment {environment.name} has no AWS integration for its binding sink")
        integration = await get_integration_service(session=self.session).get_by_id(str(integration_id))
        if integration is None:
            raise CannotProceed(f"Integration {integration_id} not found")
        adapter = await get_integration_adapter(
            integration.integration_provider, integration.model_dump()["configuration"], integration_id=integration.id
        )
        await adapter.authenticate()
        return adapter.environment_variables

    async def _cluster(self, config: BindingSinkConfig) -> Configuration:
        if config.cluster_resource_id is None:
            raise CannotProceed("The binding sink needs cluster_resource_id for Kubernetes access")
        cluster = await get_resource_service(session=self.session).get_by_id(config.cluster_resource_id)
        if cluster is None:
            raise CannotProceed(f"Cluster resource {config.cluster_resource_id} not found")
        return (await build_kubernetes_client("aws_eks", cluster, self.session)).configuration

    async def _sink(self, environment: Environment, target: BindingTarget) -> BindingSinkAdapter:
        if target.config.type == "kubernetes_secret":
            return KubernetesSecretSink(await self._cluster(target.config), target.namespace)
        region = target.config.region or environment.region
        if not region:
            raise CannotProceed(f"Environment {environment.name} has no region for its binding sink")
        return AwsSecretsManagerSink(await self._credentials(environment, target.config), region)

    async def apply(
        self, instance: ServiceInstance, service: Service, environment: Environment
    ) -> dict[str, Any] | None:
        """Write runtime bindings and return the new binding_state."""
        result = preview(instance, service, environment)
        if result.rendered.errors:
            raise CannotProceed("Cannot render bindings: " + "; ".join(result.rendered.errors))
        payload = result.rendered.payload("runtime")
        previous = instance.binding_state or {}
        target = result.target
        if target.path is None:
            if previous:
                await self.remove(instance, service, environment)
            return None
        if not payload and not previous:
            return None

        sink = await self._sink(environment, target)
        created = bool(previous.get("created")) and previous.get("path") == target.path
        if previous.get("path") and previous.get("path") != target.path:
            await self._remove_keys(sink, previous["path"], set(previous.get("keys", [])), previous.get("created"))

        existing = await sink.read(target.path) or {}
        managed_before = set(previous.get("keys", [])) if previous.get("path") == target.path else set()
        merged = merge_managed(existing, payload, managed_before)
        if merged != existing or not existing:
            created = await sink.write(target.path, merged) or created

        spc = previous.get("spc")
        if target.config.secret_provider_class and target.secret_provider_class:
            outcome = await ensure_secret_provider_class(
                await self._cluster(target.config),
                target.namespace,
                target.secret_provider_class,
                target.path,
                sorted(merged),
            )
            spc = {
                "name": target.secret_provider_class,
                "namespace": target.namespace,
                "created": outcome in ("created", "updated") or bool(spc and spc.get("created")),
                "status": outcome,
            }

        return {
            "sink": target.config.type,
            "path": target.path,
            "keys": sorted(payload),
            "created": created,
            "spc": spc,
            "applied_at": datetime.now(UTC).isoformat(),
        }

    async def _remove_keys(self, sink: BindingSinkAdapter, path: str, keys: set[str], created: bool | None) -> None:
        existing = await sink.read(path)
        if existing is None:
            return
        remaining = {k: v for k, v in existing.items() if k not in keys}
        if not remaining and created:
            await sink.delete(path)
        elif remaining != existing:
            await sink.write(path, remaining)

    async def remove(self, instance: ServiceInstance, service: Service, environment: Environment) -> None:
        """Remove only what this instance wrote; other keys and hand-made objects are left in place."""
        previous = instance.binding_state or {}
        if not previous.get("path"):
            return
        target = target_for(environment, service)
        config = target.config
        if previous.get("sink") != config.type:
            config = config.model_copy(update={"type": previous.get("sink")})
            target = BindingTarget(
                config=config,
                path=previous["path"],
                namespace=target.namespace,
                secret_provider_class=None,
                mount_path=None,
            )
        sink = await self._sink(environment, target)
        await self._remove_keys(sink, previous["path"], set(previous.get("keys", [])), previous.get("created"))
        spc = previous.get("spc")
        if spc and spc.get("created"):
            await delete_secret_provider_class(await self._cluster(config), spc["namespace"], spc["name"])
