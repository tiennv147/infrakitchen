from uuid import uuid4

import pytest
from pydantic import ValidationError

from application.services.compiler import (
    Catalog,
    CatalogTemplate,
    CatalogVersion,
    EnvironmentTarget,
    OwnedResource,
    PlanAction,
    compile_service_spec,
    compile_workload,
    validate_spec_against_catalog,
)
from application.services.schema import ServiceSpec, WorkloadSpec, validate_image_tag
from core.constants.model import ModelStatus

SERVICE_ID = uuid4()
USER_ID = uuid4()
HELM = CatalogTemplate(
    id=uuid4(),
    key="helm_workload",
    name="Helm Workload",
    enabled=True,
    abstract=False,
    claimable=False,
    naming_convention="workload-{release_name}-{environment_name}",
)
CATALOG = Catalog(templates_by_key={HELM.key: HELM}, latest_version_by_template={HELM.id: uuid4()})
ENV = EnvironmentTarget(
    id=uuid4(),
    name="shop-dev-eu-west-1",
    integration_ids=(uuid4(),),
    storage_id=uuid4(),
    storage_path_prefix="state",
    tier="dev",
    region="eu-west-1",
    cluster_name="shop-dev",
)


def _workload(**overrides) -> WorkloadSpec:
    values = {
        "mode": "managed",
        "chart": "oci://registry.example.com/charts/app",
        "chart_version": "1.4.0",
        "values_files": ["helm-values/values.yaml", "helm-values/{environment}/values.yaml?"],
    }
    values.update(overrides)
    return WorkloadSpec.model_validate(values)


def _compile(workload: WorkloadSpec, *, owned=(), version="1.2.3", values=None, commit=None, environment=ENV):
    return compile_workload(
        service_id=SERVICE_ID,
        service_name="checkout",
        workload=workload,
        catalog=CATALOG,
        environment=environment,
        owned=list(owned),
        created_by=USER_ID,
        version=version,
        values=values,
        values_commit=commit,
    )


def _existing(variables: dict, **overrides) -> OwnedResource:
    values = dict(
        alias="workload",
        role="workload",
        id=uuid4(),
        template_id=HELM.id,
        name="workload-checkout-shop-dev-eu-west-1",
        source_code_version_id=uuid4(),
        variables=variables,
        storage_path="state/shop-dev-eu-west-1/checkout/workload/terraform.tfstate",
    )
    values.update(overrides)
    return OwnedResource(**values)


class TestWorkloadSpec:
    def test_defaults_to_external_and_service_name(self):
        spec = WorkloadSpec(chart="charts/app", chart_version="1.0.0")
        assert spec.mode == "external"
        assert (spec.release_name, spec.namespace, spec.template) == (None, None, "helm_workload")

    def test_values_paths_render_placeholders_and_optional_marker(self):
        spec = _workload(values_files=["v/values.yaml", "v/{tier}/{environment}.yaml?", "v/{region}.yaml"])
        assert spec.values_paths("checkout", "shop-dev", "eu-west-1", "dev") == [
            ("v/values.yaml", False),
            ("v/dev/shop-dev.yaml", True),
            ("v/eu-west-1.yaml", False),
        ]

    @pytest.mark.parametrize("path", ["/etc/passwd", "../secrets.yaml", "a/../../b.yaml", "-x.yaml", "v/{team}.yaml"])
    def test_values_paths_must_stay_in_the_repository(self, path):
        with pytest.raises(ValidationError):
            _workload(values_files=[path])

    @pytest.mark.parametrize("ref", ["--upload-pack=x", "a..b", "has space"])
    def test_values_ref_must_be_a_plain_ref(self, ref):
        with pytest.raises(ValidationError):
            _workload(values_ref=ref)

    def test_names_must_be_dns_labels(self):
        with pytest.raises(ValidationError):
            _workload(namespace="Checkout_API")
        assert _workload(release_name="").release_name is None

    def test_workload_alias_is_reserved(self):
        with pytest.raises(ValidationError, match="reserved"):
            ServiceSpec.model_validate(
                {
                    "claims": [{"alias": "workload", "template": "aws_redis"}],
                    "workload": {"chart": "c", "chart_version": "1"},
                }
            )

    def test_managed_workload_is_only_returned_for_managed_mode(self):
        external = ServiceSpec(workload=_workload(mode="external"))
        assert external.managed_workload is None
        assert ServiceSpec(workload=_workload()).managed_workload is not None

    @pytest.mark.parametrize("tag", ["1.2.3", "sha-4f2a9c1", "v2_rc.1"])
    def test_image_tags(self, tag):
        assert validate_image_tag(tag) == tag

    @pytest.mark.parametrize("tag", ["", "-rc", "has space", "a/b", "x" * 129])
    def test_invalid_image_tags(self, tag):
        with pytest.raises(ValueError):
            validate_image_tag(tag)


class TestCatalogValidation:
    def test_managed_workload_needs_its_template(self):
        errors = validate_spec_against_catalog(ServiceSpec(workload=_workload()), Catalog(templates_by_key={}))
        assert errors == ["Workload: template 'helm_workload' does not exist"]

    def test_external_workload_is_not_checked(self):
        spec = ServiceSpec(workload=_workload(mode="external"))
        assert validate_spec_against_catalog(spec, Catalog(templates_by_key={})) == []

    def test_disabled_template_is_rejected(self):
        disabled = CatalogTemplate(**{**HELM.__dict__, "enabled": False})
        errors = validate_spec_against_catalog(
            ServiceSpec(workload=_workload()), Catalog(templates_by_key={HELM.key: disabled})
        )
        assert errors == ["Workload: template 'helm_workload' is abstract or disabled"]

    def test_pinned_version_must_belong_to_the_template(self):
        other = CatalogVersion(id=uuid4(), template_id=uuid4())
        catalog = Catalog(templates_by_key={HELM.key: HELM}, versions={other.id: other})
        errors = validate_spec_against_catalog(
            ServiceSpec(workload=_workload(source_code_version_id=other.id)), catalog
        )
        assert errors and "is not a version of 'helm_workload'" in errors[0]


class TestCompileWorkload:
    def test_first_apply_creates_the_release_after_nothing_else(self):
        compiled = _compile(_workload(), values=["a: 1", "b: 2"], commit="abc123")
        assert compiled.plan.errors == [] and compiled.workflow is not None
        (step,) = compiled.workflow.steps
        assert (step.step_key, step.position, step.template_id) == ("workload", 0, HELM.id)
        assert step.storage_path == "state/shop-dev-eu-west-1/checkout/workload/terraform.tfstate"
        assert step.resolved_variables["image_tag"] == "1.2.3"
        assert step.resolved_variables["values"] == ["a: 1", "b: 2"]
        assert step.resolved_variables["values_commit"] == "abc123"
        assert step.resolved_variables["release_name"] == "checkout"
        assert step.resolved_variables["namespace"] == "checkout"
        assert (step.resolved_variables["cluster_name"], step.resolved_variables["region"]) == (
            "shop-dev",
            "eu-west-1",
        )
        (item,) = compiled.plan.items
        assert (item.action, item.role) == (PlanAction.CREATE, "workload")
        assert {c.field: c.after for c in item.changes}["values"] == "2 values files"

    def test_same_version_and_values_is_a_no_op(self):
        applied = _compile(_workload(), values=["a: 1"], commit="abc").workflow
        assert applied is not None
        existing = _existing(applied.steps[0].resolved_variables)
        compiled = _compile(_workload(), owned=[existing], values=["a: 1"], commit="abc")
        assert compiled.plan.items[0].action == PlanAction.NO_OP
        assert compiled.workflow is not None and compiled.workflow.steps[0].status == ModelStatus.DONE

    def test_new_version_updates_only_the_image_tag(self):
        applied = _compile(_workload(), values=["a: 1"], commit="abc").workflow
        assert applied is not None
        existing = _existing(applied.steps[0].resolved_variables)
        compiled = _compile(_workload(), owned=[existing], version="1.2.4", values=["a: 1"], commit="abc")
        item = compiled.plan.items[0]
        assert item.action == PlanAction.UPDATE
        assert [(c.field, c.before, c.after) for c in item.changes] == [("image_tag", "1.2.3", "1.2.4")]
        step = compiled.workflow.steps[0] if compiled.workflow else None
        assert step is not None and step.resource_id == existing.id and step.status == ModelStatus.PENDING

    def test_plan_preview_keeps_applied_values(self):
        applied = _compile(_workload(), values=["a: 1"], commit="abc").workflow
        assert applied is not None
        existing = _existing(applied.steps[0].resolved_variables)
        compiled = _compile(_workload(), owned=[existing], values=None)
        assert compiled.plan.items[0].action == PlanAction.NO_OP

    def test_changed_values_file_content_is_an_update(self):
        applied = _compile(_workload(), values=["a: 1"], commit="abc").workflow
        assert applied is not None
        existing = _existing(applied.steps[0].resolved_variables)
        item = _compile(_workload(), owned=[existing], values=["a: 2"], commit="def").plan.items[0]
        assert {c.field for c in item.changes} == {"values", "values_commit"}

    def test_environment_without_cluster_is_an_error(self):
        no_cluster = EnvironmentTarget(id=uuid4(), name="shop-dev", integration_ids=(), storage_id=uuid4())
        compiled = _compile(_workload(), environment=no_cluster)
        assert compiled.workflow is None
        assert compiled.plan.errors == ["Workload: environment 'shop-dev' has no cluster name"]

    def test_release_from_another_template_is_an_error(self):
        existing = _existing({}, template_id=uuid4())
        assert _compile(_workload(), owned=[existing]).plan.errors


class TestClaimsLeaveTheWorkloadAlone:
    def test_workload_link_is_not_destroyed_when_the_workload_becomes_external(self):
        existing = _existing({"image_tag": "1.2.3"})
        compiled = compile_service_spec(
            service_id=SERVICE_ID,
            service_name="checkout",
            spec=ServiceSpec(workload=_workload(mode="external")),
            catalog=CATALOG,
            environment=ENV,
            owned=[existing],
            created_by=USER_ID,
        )
        assert compiled.plan.errors == []
        assert all(item.action != PlanAction.DESTROY for item in compiled.plan.items)
