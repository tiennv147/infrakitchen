from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.service_instances.workload_values import WorkloadValuesResolver, normalize_repo_url
from application.services.schema import WorkloadSpec
from core.adapters.provider_adapters import IntegrationProvider

FILES = {
    "helm-values/values.yaml": "replicas: 2\n",
    "helm-values/shop-dev/values.yaml": "replicas: 1\n",
}


class FakeGit:
    def __init__(self) -> None:
        self.cloned: str | None = None

    async def clone_branch(self, branch: str) -> None:
        self.cloned = branch

    async def head_commit(self) -> str:
        return "abc123"

    async def read_file_at_ref(self, ref: str, path: str) -> str:
        if path not in FILES:
            raise RuntimeError(f"fatal: path '{path}' does not exist")
        return FILES[path]


class FakeProvider:
    git = FakeGit()

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.workspace_root: str | None = None

    async def authenticate(self) -> None:
        pass

    async def get_git_client(self, git_url: str, workspace_root: str, repo_name: str) -> FakeGit:
        return self.git


@pytest.fixture
def resolver(monkeypatch):
    r = WorkloadValuesResolver(session=None)  # type: ignore[arg-type]
    monkeypatch.setattr(r, "_integration", AsyncMock(return_value=SimpleNamespace(integration_provider="x")))
    monkeypatch.setattr(r, "_provider", AsyncMock(return_value=FakeProvider()))
    return r


SERVICE = SimpleNamespace(name="checkout", repository_url="https://github.com/shop/checkout-api")
ENVIRONMENT = SimpleNamespace(name="shop-dev", region="eu-west-1", tier="dev", integration_ids=[])


def _workload(*files: str) -> WorkloadSpec:
    return WorkloadSpec(mode="managed", chart="c", chart_version="1", values_files=list(files), values_ref="release")


class TestResolve:
    @pytest.mark.asyncio
    async def test_files_are_read_in_order_at_the_ref(self, resolver):
        result = await resolver.resolve(
            SERVICE, ENVIRONMENT, _workload("helm-values/values.yaml", "helm-values/{environment}/values.yaml")
        )
        assert result.values == ["replicas: 2\n", "replicas: 1\n"]
        assert result.commit == "abc123"
        assert FakeProvider.git.cloned == "release"

    @pytest.mark.asyncio
    async def test_optional_missing_file_is_skipped(self, resolver):
        result = await resolver.resolve(
            SERVICE, ENVIRONMENT, _workload("helm-values/values.yaml", "helm-values/{region}/values.yaml?")
        )
        assert result.files == ["helm-values/values.yaml"]

    @pytest.mark.asyncio
    async def test_required_missing_file_fails(self, resolver):
        with pytest.raises(ValueError, match="helm-values/eu-west-1/values.yaml not found at release"):
            await resolver.resolve(SERVICE, ENVIRONMENT, _workload("helm-values/{region}/values.yaml"))

    @pytest.mark.asyncio
    async def test_no_values_files_needs_no_repository(self, resolver):
        result = await resolver.resolve(SimpleNamespace(name="x", repository_url=None), ENVIRONMENT, _workload())
        assert result.values == [] and result.commit is None

    @pytest.mark.asyncio
    async def test_values_files_need_a_repository(self, resolver):
        with pytest.raises(ValueError, match="no repository URL"):
            await resolver.resolve(
                SimpleNamespace(name="x", repository_url=None), ENVIRONMENT, _workload("values.yaml")
            )


class TestIntegrationChoice:
    @pytest.mark.asyncio
    async def test_public_provider_when_no_integration(self, monkeypatch):
        monkeypatch.setitem(IntegrationProvider.adapters, "git_public", FakeProvider)
        provider = await WorkloadValuesResolver(session=None)._provider(None, log=None)  # type: ignore[arg-type]
        assert isinstance(provider, FakeProvider)

    def test_repository_urls_compare_loosely(self):
        assert normalize_repo_url("https://GitHub.com/Shop/App.git/") == normalize_repo_url(
            "https://github.com/shop/app"
        )
