"""Read a managed workload's Helm values files from the service repository, in order."""

from dataclasses import dataclass, field
import logging
import tempfile
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from application.environments.model import Environment
from application.integrations.model import Integration, IntegrationDTO
from application.services.model import Service
from application.services.schema import WorkloadSpec
from application.source_codes.model import SourceCode
from core.adapters.provider_adapters import IntegrationProvider

logger = logging.getLogger(__name__)


@dataclass
class ResolvedValues:
    values: list[str] = field(default_factory=list)
    commit: str | None = None
    files: list[str] = field(default_factory=list)


def normalize_repo_url(url: str) -> str:
    url = url.strip().rstrip("/").lower()
    return url.removesuffix(".git")


class WorkloadValuesResolver:
    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session

    async def _integration(self, repository_url: str, environment: Environment) -> Integration | None:
        """Credentials of a Source Code with the same repository, else the environment's git integration."""
        target = normalize_repo_url(repository_url)
        sources = await self.session.execute(select(SourceCode).where(SourceCode.integration_id.is_not(None)))
        for source in sources.scalars().unique():
            if normalize_repo_url(source.source_code_url) == target:
                return source.integration
        return next((i for i in environment.integration_ids if i.integration_type == "git"), None)

    async def _provider(self, integration: Integration | None, log: Any) -> IntegrationProvider:
        name = integration.integration_provider if integration is not None else "git_public"
        adapter: type[IntegrationProvider] | None = IntegrationProvider.adapters.get(name)
        if adapter is None:
            raise ValueError(f"Git provider {name} is not supported")
        if integration is None:
            return adapter(**{"logger": log})
        return adapter(**{"logger": log, "configuration": IntegrationDTO.model_validate(integration).configuration})

    async def resolve(
        self, service: Service, environment: Environment, workload: WorkloadSpec, log: Any = logger
    ) -> ResolvedValues:
        paths = workload.values_paths(service.name, environment.name, environment.region, environment.tier)
        if not paths:
            return ResolvedValues()
        if not service.repository_url:
            raise ValueError("The service has no repository URL to read its values files from")

        provider = await self._provider(await self._integration(service.repository_url, environment), log)
        with tempfile.TemporaryDirectory(prefix="ik-values-") as root:
            provider.workspace_root = root
            await provider.authenticate()
            client = await provider.get_git_client(
                git_url=service.repository_url, workspace_root=root, repo_name="service_repo"
            )
            await client.clone_branch(workload.values_ref)
            resolved = ResolvedValues(commit=await client.head_commit())
            for path, optional in paths:
                try:
                    content = await client.read_file_at_ref("HEAD", path)
                except Exception as e:  # noqa: BLE001 - git reports a missing path as a failed command
                    if optional:
                        continue
                    raise ValueError(f"Values file {path} not found at {workload.values_ref}") from e
                resolved.values.append(content)
                resolved.files.append(path)
            return resolved
