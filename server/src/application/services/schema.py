from datetime import datetime, UTC
import re
from typing import Any, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from application.projects.schema import ProjectShort
from core.users.schema import UserShort

ALIAS_PATTERN = r"[a-z][a-z0-9_]{0,62}"
BINDING_KEY_PATTERN = r"[A-Za-z_][A-Za-z0-9_.-]{0,127}"
# Reserved alias of the workload resource; claims cannot use it.
WORKLOAD_ALIAS = "workload"
WORKLOAD_MODES = ("external", "managed")
VALUES_PLACEHOLDERS = ("service_name", "environment", "region", "tier")
# Container image tag rules, so a version is always a valid tag.
IMAGE_TAG_PATTERN = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}"
_K8S_NAME = r"[a-z0-9]([-a-z0-9]{0,51}[a-z0-9])?"
_VALUES_PATH = re.compile(r"^[A-Za-z0-9_.{}/-]+\??$")
_GIT_REF = re.compile(r"^[A-Za-z0-9_./-]{1,200}$")
_HELM_KEY = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,200}$")
# image repository without tag or digest, e.g. 123456789012.dkr.ecr.eu-west-1.amazonaws.com/team/app
_IMAGE_REPOSITORY = re.compile(r"^[a-z0-9][a-z0-9.-]*(:[0-9]+)?(/[a-z0-9]([a-z0-9._-]*[a-z0-9])?)+$")
_CPU = re.compile(r"^([0-9]+m|[0-9]+(\.[0-9]{1,3})?)$")
_MEMORY = re.compile(r"^[0-9]+(Mi|Gi)$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_HTTP_PATH = re.compile(r"^/[A-Za-z0-9._~/-]{0,200}$")
# A variable value that is exactly "${alias.outputs.name}" is wired from another claim's output.
OUTPUT_REF = re.compile(rf"^\$\{{({ALIAS_PATTERN})\.outputs\.([A-Za-z_][A-Za-z0-9_]*)\}}$")
# Binding values may interpolate any number of references inside literal text.
BINDING_REF = re.compile(rf"\$\{{({ALIAS_PATTERN})\.outputs\.([A-Za-z_][A-Za-z0-9_]*)\}}")
_ANY_REF = re.compile(r"\$\{[^}]*\}")


class OutputRef(BaseModel):
    alias: str
    output: str


def parse_output_ref(value: Any) -> OutputRef | None:
    """Return the reference if ``value`` is a whole-value ``${alias.outputs.name}`` string."""
    if not isinstance(value, str):
        return None
    match = OUTPUT_REF.match(value.strip())
    if match:
        return OutputRef(alias=match.group(1), output=match.group(2))
    if _ANY_REF.search(value):
        raise ValueError(
            f"Unsupported reference in '{value}': use the whole value '${{alias.outputs.name}}', "
            "string interpolation is not supported"
        )
    return None


class ClaimSpec(BaseModel):
    """One piece of infrastructure the service needs, provisioned from a claimable template."""

    alias: str = Field(..., description="Unique name of the claim within the service")
    template: str = Field(..., description="Template key of a claimable template, e.g. aws_redis")
    source_code_version_id: uuid.UUID | None = Field(
        default=None, description="Pinned template version; the latest active version is used when empty"
    )
    variables: dict[str, Any] = Field(default_factory=dict)
    parents: list[str] = Field(
        default_factory=list, description="Aliases of claims whose resources are parents of this one"
    )
    adopted: bool = Field(
        default=False, description="Reverse-compiled from an adopted resource; may use a non-catalog template"
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("alias")
    @classmethod
    def validate_alias(cls, value: str) -> str:
        if not re.fullmatch(ALIAS_PATTERN, value):
            raise ValueError(f"alias '{value}' must match {ALIAS_PATTERN}")
        return value

    def output_refs(self) -> dict[str, OutputRef]:
        """Variables wired from other claims, keyed by target variable."""
        refs: dict[str, OutputRef] = {}
        for name, value in self.variables.items():
            ref = parse_output_ref(value)
            if ref is not None:
                refs[name] = ref
        return refs

    def literal_variables(self) -> dict[str, Any]:
        refs = self.output_refs()
        return {name: value for name, value in self.variables.items() if name not in refs}


class BindingSpec(BaseModel):
    """A key delivered to the workload; values may interpolate outputs of claims or referenced resources."""

    key: str = Field(..., description="Name the application reads, e.g. REDIS_URL")
    value: str = Field(..., description="Literal text with ${alias.outputs.name} references")
    scope: Literal["runtime", "build"] = Field(
        default="runtime", description="runtime goes to the environment's binding sink; build is read by CI"
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        if not re.fullmatch(BINDING_KEY_PATTERN, value):
            raise ValueError(f"binding key '{value}' must match {BINDING_KEY_PATTERN}")
        return value

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        leftover = BINDING_REF.sub("", value)
        if _ANY_REF.search(leftover):
            raise ValueError(f"Unsupported reference in '{value}': use ${{alias.outputs.name}}")
        return value

    def refs(self) -> list[OutputRef]:
        return [OutputRef(alias=m.group(1), output=m.group(2)) for m in BINDING_REF.finditer(self.value)]


class AppSpec(BaseModel):
    """A web service described by what is unique to it; the platform app chart supplies the rest."""

    image: str = Field(..., description="Image repository without tag; the deployed version is the tag")
    port: int = Field(default=8080, ge=1, le=65535, description="Port the container listens on")
    health_path: str | None = Field(default="/health", description="HTTP path for readiness and liveness probes")
    replicas: int = Field(default=2, ge=1, le=50)
    cpu: str = Field(default="100m", description="CPU request, e.g. 100m or 0.5")
    memory: str = Field(default="128Mi", description="Memory request and limit, e.g. 128Mi")
    env: dict[str, str] = Field(default_factory=dict, description="Plain environment variables; secrets use bindings")

    model_config = ConfigDict(extra="forbid")

    @field_validator("image")
    @classmethod
    def validate_image(cls, value: str) -> str:
        value = value.strip()
        if not _IMAGE_REPOSITORY.match(value):
            raise ValueError(f"'{value}' must be an image repository without tag or digest, e.g. registry/team/app")
        return value

    @field_validator("health_path")
    @classmethod
    def validate_health_path(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not _HTTP_PATH.match(value):
            raise ValueError(f"'{value}' must be an HTTP path starting with /")
        return value

    @field_validator("cpu")
    @classmethod
    def validate_cpu(cls, value: str) -> str:
        if not _CPU.match(value):
            raise ValueError(f"'{value}' is not a CPU quantity, e.g. 100m or 0.5")
        return value

    @field_validator("memory")
    @classmethod
    def validate_memory(cls, value: str) -> str:
        if not _MEMORY.match(value):
            raise ValueError(f"'{value}' is not a memory quantity, e.g. 128Mi or 1Gi")
        return value

    @field_validator("env")
    @classmethod
    def validate_env(cls, value: dict[str, str]) -> dict[str, str]:
        for name in value:
            if not _ENV_NAME.match(name):
                raise ValueError(f"'{name}' is not a valid environment variable name")
        return value

    def chart_values(self) -> dict[str, Any]:
        """Values of the platform app chart; its values contract is these keys."""
        values: dict[str, Any] = {
            "image": {"repository": self.image},
            "port": self.port,
            "replicas": self.replicas,
            "resources": {"cpu": self.cpu, "memory": self.memory},
            "env": dict(sorted(self.env.items())),
        }
        if self.health_path:
            values["health"] = {"path": self.health_path}
        return values


class WorkloadSpec(BaseModel):
    """The Helm release that runs the service.

    external: recorded only; CI deploys it. managed: InfraKitchen applies it after the claims and bindings.
    With ``app`` the platform app chart is used unless ``chart`` is set; values files then only override.
    """

    mode: Literal["external", "managed"] = Field(default="external")
    app: AppSpec | None = Field(default=None, description="Describe the service; the platform chart runs it")
    chart: str | None = Field(default=None, description="Chart reference, e.g. oci://registry/charts/app")
    chart_version: str | None = Field(default=None, description="Pinned chart version")
    release_name: str | None = Field(default=None, description="Defaults to the service name")
    namespace: str | None = Field(default=None, description="Defaults to the service name")
    values_files: list[str] = Field(
        default_factory=list,
        description="Paths in the service repository, applied in order. Placeholders: {service_name}, "
        "{environment}, {region}, {tier}; a trailing ? marks a file as optional",
    )
    values_ref: str = Field(default="main", description="Branch or tag of the service repository")
    template: str = Field(default="helm_workload", description="Template that applies the release (managed mode)")
    source_code_version_id: uuid.UUID | None = Field(default=None)
    image_tag_key: str = Field(default="image.tag", description="Chart value set to the deployed version")
    atomic: bool = Field(default=True, description="Roll back automatically when the release fails")
    wait: bool = Field(default=True)
    timeout: int = Field(default=300, ge=1, le=3600, description="Seconds")
    cleanup_on_fail: bool = Field(default=True)

    model_config = ConfigDict(extra="forbid")

    @field_validator("chart", "chart_version")
    @classmethod
    def validate_required(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if any(c.isspace() for c in value):
            raise ValueError("must contain no whitespace")
        return value

    @model_validator(mode="after")
    def validate_chart_source(self) -> "WorkloadSpec":
        if (self.chart is None) != (self.chart_version is None):
            raise ValueError("chart and chart_version are set together")
        if self.chart is None and self.app is None:
            raise ValueError("Describe the service under 'app', or set 'chart' and 'chart_version'")
        return self

    @field_validator("release_name", "namespace")
    @classmethod
    def validate_k8s_name(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not re.fullmatch(_K8S_NAME, value):
            raise ValueError(f"'{value}' must be a lowercase DNS label of at most 53 characters")
        return value

    @field_validator("values_files")
    @classmethod
    def validate_values_files(cls, value: list[str]) -> list[str]:
        for path in value:
            if not _VALUES_PATH.match(path) or path.startswith(("/", "-")) or ".." in path.split("/"):
                raise ValueError(f"values file '{path}' must be a relative path inside the repository")
            try:
                path.format(**{name: "x" for name in VALUES_PLACEHOLDERS})
            except (KeyError, IndexError, ValueError) as e:
                raise ValueError(f"Unknown placeholder in '{path}'; use {', '.join(VALUES_PLACEHOLDERS)}") from e
        return value

    @field_validator("values_ref")
    @classmethod
    def validate_values_ref(cls, value: str) -> str:
        if not _GIT_REF.match(value) or value.startswith("-") or ".." in value:
            raise ValueError(f"'{value}' is not a valid git ref")
        return value

    @field_validator("image_tag_key")
    @classmethod
    def validate_image_tag_key(cls, value: str) -> str:
        if not _HELM_KEY.match(value):
            raise ValueError(f"'{value}' is not a valid chart value path")
        return value

    def values_paths(
        self, service_name: str, environment: str, region: str | None, tier: str
    ) -> list[tuple[str, bool]]:
        """Rendered values file paths in order, with whether each one is optional."""
        context = {"service_name": service_name, "environment": environment, "region": region or "", "tier": tier}
        return [(path.rstrip("?").format(**context), path.endswith("?")) for path in self.values_files]


def validate_image_tag(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(IMAGE_TAG_PATTERN, value):
        raise ValueError(f"'{value}' is not a valid image tag")
    return value


class ServiceSpec(BaseModel):
    """Declarative description of the infrastructure a service claims in every environment."""

    claims: list[ClaimSpec] = Field(default_factory=list)
    bindings: list[BindingSpec] = Field(default_factory=list)
    workload: WorkloadSpec | None = Field(default=None)

    model_config = ConfigDict(extra="forbid")

    @property
    def managed_workload(self) -> WorkloadSpec | None:
        return self.workload if self.workload is not None and self.workload.mode == "managed" else None

    @model_validator(mode="after")
    def validate_references(self) -> "ServiceSpec":
        aliases = [claim.alias for claim in self.claims]
        duplicates = sorted({alias for alias in aliases if aliases.count(alias) > 1})
        if duplicates:
            raise ValueError(f"Duplicate claim aliases: {', '.join(duplicates)}")
        if self.workload is not None and WORKLOAD_ALIAS in aliases:
            raise ValueError(f"The alias '{WORKLOAD_ALIAS}' is reserved for the workload")

        keys = [binding.key for binding in self.bindings]
        duplicate_keys = sorted({key for key in keys if keys.count(key) > 1})
        if duplicate_keys:
            raise ValueError(f"Duplicate binding keys: {', '.join(duplicate_keys)}")

        known = set(aliases)
        for claim in self.claims:
            referenced = [ref.alias for ref in claim.output_refs().values()] + claim.parents
            for alias in referenced:
                if alias == claim.alias:
                    raise ValueError(f"Claim '{claim.alias}' cannot reference itself")
                if alias not in known:
                    raise ValueError(f"Claim '{claim.alias}' references unknown claim '{alias}'")
        return self


class ServiceShort(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str | None = Field(default=None)
    owners: list[UserShort] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    def _entity_name(self) -> str:
        return "service"


def _validate_repository_url(value: str | None) -> str | None:
    # An empty string is how clients clear the link on update.
    if value is None or value == "":
        return value
    value = value.strip()
    if not value.startswith(("https://", "http://")):
        raise ValueError("Repository URL must start with https:// or http://")
    return value


class ServiceCreate(BaseModel):
    name: str = Field(...)
    display_name: str | None = Field(default=None)
    description: str = Field(default="")
    project_id: uuid.UUID = Field(...)
    repository_url: str | None = Field(default=None)
    labels: list[str] = Field(default_factory=list)
    owners: list[uuid.UUID] = Field(default_factory=list)
    depends_on: list[uuid.UUID] = Field(default_factory=list)
    spec: ServiceSpec = Field(default_factory=ServiceSpec)

    model_config = ConfigDict(from_attributes=True)

    _check_repository_url = field_validator("repository_url")(_validate_repository_url)

    @field_validator("spec", mode="before")
    @classmethod
    def _empty_spec(cls, value: Any) -> Any:
        return value or {}


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None)
    display_name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    project_id: uuid.UUID | None = Field(default=None)
    repository_url: str | None = Field(default=None)
    labels: list[str] | None = Field(default=None)
    owners: list[uuid.UUID] | None = Field(default=None)
    depends_on: list[uuid.UUID] | None = Field(default=None)
    spec: ServiceSpec | None = Field(default=None)

    model_config = ConfigDict(from_attributes=True)

    _check_repository_url = field_validator("repository_url")(_validate_repository_url)


class ServiceResponse(BaseModel):
    id: uuid.UUID = Field(...)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), frozen=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    revision_number: int = Field(default=1)
    creator: UserShort | None = Field(default=None)

    name: str = Field(...)
    display_name: str | None = Field(default=None)
    description: str = Field(default="")
    project_id: uuid.UUID = Field(...)
    project: ProjectShort | None = Field(default=None)
    repository_url: str | None = Field(default=None)
    owners: list[UserShort] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    spec: ServiceSpec = Field(default_factory=ServiceSpec)
    spec_revision: int = Field(default=1)

    model_config = ConfigDict(from_attributes=True)

    @field_validator("spec", mode="before")
    @classmethod
    def _empty_spec(cls, value: Any) -> Any:
        return value or {}

    @field_validator("spec_revision", mode="before")
    @classmethod
    def _default_spec_revision(cls, value: Any) -> Any:
        return 1 if value is None else value

    @computed_field
    def _entity_name(self) -> str:
        return "service"
