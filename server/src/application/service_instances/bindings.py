"""Render a service's bindings from resource outputs and merge them into a sink document.

Pure functions only; loading resources and talking to sinks happens in the reconciler and query layers.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from application.environments.schema import BindingSinkConfig
from application.services.schema import BINDING_REF, BindingSpec

MASK = "********"


@dataclass(frozen=True)
class BoundOutput:
    value: Any
    sensitive: bool = False


@dataclass(frozen=True)
class BoundResource:
    alias: str
    role: str
    name: str
    template_key: str
    # Outputs the template publishes for binding; empty means the template does not restrict them.
    binding_outputs: tuple[str, ...] = ()
    outputs: dict[str, BoundOutput] = field(default_factory=dict)


@dataclass
class RenderedBinding:
    key: str
    scope: str
    value: str
    sensitive: bool
    sources: list[str]


@dataclass
class RenderedBindings:
    items: list[RenderedBinding] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)  # (scope, message)

    @property
    def errors(self) -> list[str]:
        return [message for _, message in self.failures]

    def errors_for(self, scope: str) -> list[str]:
        return [message for failed_scope, message in self.failures if failed_scope == scope]

    def payload(self, scope: str) -> dict[str, str]:
        return {item.key: item.value for item in self.items if item.scope == scope}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def _resolve(binding: BindingSpec, alias: str, output: str, resources: dict[str, BoundResource]) -> BoundOutput | str:
    """The output to substitute, or an error message."""
    resource = resources.get(alias)
    if resource is None:
        return f"{binding.key}: '{alias}' is neither a claim nor a referenced resource here"
    if resource.binding_outputs and output not in resource.binding_outputs:
        return (
            f"{binding.key}: output '{output}' of {resource.template_key} is not published for binding "
            f"(allowed: {', '.join(resource.binding_outputs)})"
        )
    found = resource.outputs.get(output)
    if found is None:
        return f"{binding.key}: {resource.name} has no output '{output}' yet"
    if found.sensitive and binding.scope == "build":
        return f"{binding.key}: sensitive output '{alias}.{output}' cannot be a build binding"
    return found


def render_bindings(bindings: list[BindingSpec], resources: dict[str, BoundResource]) -> RenderedBindings:
    rendered = RenderedBindings()
    for binding in bindings:
        errors: list[str] = []
        sources: list[str] = []
        parts: list[str] = []
        sensitive = False
        cursor = 0
        for match in BINDING_REF.finditer(binding.value):
            alias, output = match.group(1), match.group(2)
            sources.append(f"{alias}.outputs.{output}")
            parts.append(binding.value[cursor : match.start()])
            cursor = match.end()
            found = _resolve(binding, alias, output, resources)
            if isinstance(found, str):
                errors.append(found)
                continue
            sensitive = sensitive or found.sensitive
            parts.append(_text(found.value))
        parts.append(binding.value[cursor:])

        if errors:
            rendered.failures.extend((binding.scope, error) for error in errors)
            continue
        rendered.items.append(
            RenderedBinding(
                key=binding.key, scope=binding.scope, value="".join(parts), sensitive=sensitive, sources=sources
            )
        )
    return rendered


def merge_managed(existing: dict[str, str], payload: dict[str, str], managed_before: set[str]) -> dict[str, str]:
    """Overwrite managed keys only; keys written by anyone else in the same document are preserved."""
    merged = {key: value for key, value in existing.items() if key not in managed_before or key in payload}
    merged.update(payload)
    return merged


def resolve_config(raw: dict[str, Any] | None) -> BindingSinkConfig:
    return BindingSinkConfig.model_validate(raw or {})


def render_name(template: str, *, service_name: str, environment: str, region: str | None) -> str:
    return template.format(service_name=service_name, environment=environment, region=region or "")
