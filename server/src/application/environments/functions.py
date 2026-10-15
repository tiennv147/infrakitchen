from uuid import UUID

from core.constants.model import ModelActions, ModelStatus
from core.users.functions import user_api_permission, user_entity_permissions, user_is_super_admin
from core.users.model import UserDTO


async def _is_environment_admin(requester: UserDTO, environment_id: str | UUID) -> bool:
    """Environments are platform configuration: only admins of the API or the entity may change them."""
    if await user_is_super_admin(requester):
        return True
    if "admin" in await user_entity_permissions(requester, environment_id, "environment"):
        return True
    apis = await user_api_permission(requester, "environment")
    return bool(apis and apis.get("api:environment") == "admin")


async def get_environment_actions(requester: UserDTO, environment_id: str | UUID, status: ModelStatus) -> list[str]:
    if not await _is_environment_admin(requester, environment_id):
        return []
    if status == ModelStatus.DISABLED:
        return [ModelActions.EDIT, ModelActions.ENABLE, ModelActions.DELETE]
    return [ModelActions.EDIT, ModelActions.DISABLE]
