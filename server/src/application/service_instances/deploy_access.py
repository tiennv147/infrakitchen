"""Who may deploy a service's workload: its editors, its deploy tokens, and its own GitHub repository's Actions."""

from datetime import datetime
import re

from sqlalchemy.ext.asyncio import AsyncSession

from application.services.functions import get_service_actions
from application.services.model import Service
from core.casbin.enforcer import CasbinEnforcer
from core.constants.model import ModelActions
from core.errors import EntityExistsError
from core.permissions.dependencies import get_permission_service
from core.permissions.schema import EntityPolicyCreate
from core.personal_access_tokens.dependencies import get_personal_access_token_service
from core.personal_access_tokens.schema import PersonalAccessTokenCreate, PersonalAccessTokenCreateResponse
from core.sso.github_oidc import GITHUB_ACTIONS_PREFIX, GITHUB_OIDC_PROVIDER
from core.users.dependencies import get_user_service
from core.users.functions import user_has_access_to_entity
from core.users.model import UserDTO
from core.users.schema import UserCreateWithProvider

DEPLOYER_PREFIX = "service-deployer:"
_GITHUB_REPO = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", re.IGNORECASE)


def github_repository(url: str | None) -> str | None:
    """owner/name of a GitHub repository URL."""
    if not url:
        return None
    match = _GITHUB_REPO.match(url.strip())
    return match.group(1).lower() if match else None


def oidc_repository(user: UserDTO) -> str | None:
    if user.provider != GITHUB_OIDC_PROVIDER or not user.identifier.startswith(GITHUB_ACTIONS_PREFIX):
        return None
    return user.identifier.removeprefix(GITHUB_ACTIONS_PREFIX).lower()


async def can_deploy(user: UserDTO, service: Service) -> bool:
    repository = oidc_repository(user)
    if repository is not None:
        # A workflow token only ever deploys the service whose repository it runs in.
        return repository == github_repository(service.repository_url)
    if await user_has_access_to_entity(user, service.id, "write", "service"):
        return True
    return ModelActions.EDIT in await get_service_actions(user, service.id, service)


async def create_deploy_token(
    session: AsyncSession, service: Service, name: str, expires_at: datetime | None, requester: UserDTO
) -> PersonalAccessTokenCreateResponse:
    """A token for CI that can deploy this one service, held by a per-service service account."""
    deployer = await get_user_service(session=session).create_user_if_not_exists(
        UserCreateWithProvider(
            identifier=f"{DEPLOYER_PREFIX}{service.id}",
            provider="ik_service_account",
            display_name=f"Deployer: {service.name}",
            description=f"Deploys the workload of service {service.name}",
        )
    )
    permissions = get_permission_service(session=session)
    try:
        _ = await permissions.create_entity_policy(
            EntityPolicyCreate(user_id=deployer.id, entity_id=service.id, entity_name="service", action="write"),
            requester,
            reload_permission=False,
        )
    except EntityExistsError:
        pass
    token = await get_personal_access_token_service(session=session).create_token(
        deployer.id, PersonalAccessTokenCreate(name=name, expires_at=expires_at)
    )
    # Commit before other processes reload policies from the database.
    await session.commit()
    await CasbinEnforcer().send_reload_event()
    return token
