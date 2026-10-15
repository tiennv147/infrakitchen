from unittest.mock import ANY, AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from application.environments.functions import get_environment_actions
from application.environments.schema import EnvironmentCreate, EnvironmentUpdate
from core.base_models import PatchBodyModel
from core.constants.model import ModelActions, ModelStatus
from core.errors import DependencyError, EntityNotFound, EntityWrongState

FUNCTIONS = "application.environments.functions"


def _rows(rows):
    result = Mock()
    result.all.return_value = rows
    return result


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_records_revision_audit_and_event(
        self,
        mock_environment_service,
        mock_environment_crud,
        mock_revision_handler,
        mock_audit_log_handler,
        mock_event_sender,
        mocked_environment,
        mocked_user,
    ):
        mock_environment_crud.create.return_value = mocked_environment
        mock_environment_crud.get_by_id.return_value = mocked_environment

        body = EnvironmentCreate(name="app-staging-eu-central-1", tier="staging", region="eu-central-1")
        result = await mock_environment_service.create_environment(body, mocked_user)

        created = mock_environment_crud.create.await_args.args[0]
        assert created["name"] == "app-staging-eu-central-1"
        assert created["created_by"] == mocked_user.id
        assert result is mocked_environment
        mock_revision_handler.handle_revision.assert_awaited_once_with(mocked_environment)
        mock_audit_log_handler.create_log.assert_awaited_once_with(
            mocked_environment.id, mocked_user.id, ModelActions.CREATE, revision_number=1
        )
        mock_event_sender.send_event.assert_awaited_once_with(ANY, ModelActions.CREATE)

    @pytest.mark.asyncio
    async def test_create_rejects_unknown_project(self, mock_environment_service, mock_environment_crud, mocked_user):
        missing = Mock()
        missing.scalar_one_or_none.return_value = None
        mock_environment_crud.session.execute.return_value = missing

        with pytest.raises(EntityNotFound, match="Project"):
            await mock_environment_service.create_environment(
                EnvironmentCreate(name="dev", project_id=uuid4()), mocked_user
            )
        mock_environment_crud.create.assert_not_awaited()

    def test_schema_rejects_unknown_tier_and_negative_rank(self):
        with pytest.raises(ValueError):
            EnvironmentCreate(name="x", tier="qa")  # pyright: ignore[reportArgumentType]
        with pytest.raises(ValueError):
            EnvironmentCreate(name="x", rank=-1)


class TestUpdate:
    @pytest.mark.asyncio
    async def test_unchanged_collection_is_not_a_change(
        self, mock_environment_service, mock_environment_crud, mocked_environment, mocked_user
    ):
        integration = Mock(id=uuid4())
        mocked_environment.integration_ids = [integration]
        mock_environment_crud.get_by_id.return_value = mocked_environment

        with pytest.raises(ValueError, match="No changes"):
            await mock_environment_service.update_environment(
                str(mocked_environment.id), EnvironmentUpdate(integration_ids=[integration.id]), mocked_user
            )
        mock_environment_crud.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_changed_field_is_applied(
        self, mock_environment_service, mock_environment_crud, mocked_environment, mocked_user
    ):
        mock_environment_crud.get_by_id.return_value = mocked_environment

        await mock_environment_service.update_environment(
            str(mocked_environment.id), EnvironmentUpdate(rank=5), mocked_user
        )

        mock_environment_crud.update.assert_awaited_once_with(mocked_environment, {"rank": 5})


class TestDelete:
    @pytest.mark.asyncio
    async def test_enabled_environment_cannot_be_deleted(
        self, mock_environment_service, mock_environment_crud, mocked_environment, mocked_user
    ):
        mock_environment_crud.get_by_id.return_value = mocked_environment

        with pytest.raises(EntityWrongState, match="disabled"):
            await mock_environment_service.delete(str(mocked_environment.id), mocked_user)
        mock_environment_crud.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_environment_with_deployed_services_cannot_be_deleted(
        self, mock_environment_service, mock_environment_crud, mocked_environment, mocked_user
    ):
        mocked_environment.status = ModelStatus.DISABLED
        mock_environment_crud.get_by_id.return_value = mocked_environment
        service_id = uuid4()
        mock_environment_crud.session.execute.return_value = _rows([(service_id, "order-api")])

        with pytest.raises(DependencyError) as exc:
            await mock_environment_service.delete(str(mocked_environment.id), mocked_user)

        assert exc.value.metadata == [{"id": str(service_id), "name": "order-api", "entityName": "service"}]
        mock_environment_crud.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disabled_unused_environment_is_deleted(
        self,
        mock_environment_service,
        mock_environment_crud,
        mock_revision_handler,
        mocked_environment,
        mocked_user,
    ):
        mocked_environment.status = ModelStatus.DISABLED
        mock_environment_crud.get_by_id.return_value = mocked_environment
        mock_environment_crud.session.execute.return_value = _rows([])

        await mock_environment_service.delete(str(mocked_environment.id), mocked_user)

        mock_revision_handler.delete_revisions.assert_awaited_once_with(str(mocked_environment.id))
        mock_environment_crud.delete.assert_awaited_once_with(mocked_environment)


class TestPatchAction:
    @pytest.mark.asyncio
    async def test_disable_then_enable(
        self, mock_environment_service, mock_environment_crud, mocked_environment, mocked_user
    ):
        mock_environment_crud.get_by_id.return_value = mocked_environment
        env_id = str(mocked_environment.id)

        await mock_environment_service.patch_action(env_id, PatchBodyModel(action=ModelActions.DISABLE), mocked_user)
        assert mocked_environment.status == ModelStatus.DISABLED

        await mock_environment_service.patch_action(env_id, PatchBodyModel(action=ModelActions.ENABLE), mocked_user)
        assert mocked_environment.status == ModelStatus.ENABLED

    @pytest.mark.asyncio
    async def test_repeated_action_is_rejected(
        self, mock_environment_service, mock_environment_crud, mocked_environment, mocked_user
    ):
        mock_environment_crud.get_by_id.return_value = mocked_environment

        with pytest.raises(EntityWrongState, match="already enabled"):
            await mock_environment_service.patch_action(
                str(mocked_environment.id), PatchBodyModel(action=ModelActions.ENABLE), mocked_user
            )


class TestActions:
    @pytest.mark.asyncio
    @patch(f"{FUNCTIONS}.user_api_permission", new_callable=AsyncMock, return_value=None)
    @patch(f"{FUNCTIONS}.user_entity_permissions", new_callable=AsyncMock, return_value=["read"])
    @patch(f"{FUNCTIONS}.user_is_super_admin", new_callable=AsyncMock, return_value=False)
    async def test_readers_get_no_actions(self, _super_admin, _entity, _api, mocked_user):
        assert await get_environment_actions(mocked_user, uuid4(), ModelStatus.ENABLED) == []

    @pytest.mark.asyncio
    @patch(f"{FUNCTIONS}.user_api_permission", new_callable=AsyncMock, return_value={"api:environment": "admin"})
    @patch(f"{FUNCTIONS}.user_entity_permissions", new_callable=AsyncMock, return_value=[])
    @patch(f"{FUNCTIONS}.user_is_super_admin", new_callable=AsyncMock, return_value=False)
    async def test_api_admin_actions_follow_status(self, _super_admin, _entity, _api, mocked_user):
        enabled = await get_environment_actions(mocked_user, uuid4(), ModelStatus.ENABLED)
        disabled = await get_environment_actions(mocked_user, uuid4(), ModelStatus.DISABLED)

        assert enabled == [ModelActions.EDIT, ModelActions.DISABLE]
        assert disabled == [ModelActions.EDIT, ModelActions.ENABLE, ModelActions.DELETE]

    @pytest.mark.asyncio
    @patch(f"{FUNCTIONS}.user_api_permission", new_callable=AsyncMock, return_value={"api:environment": "write"})
    @patch(f"{FUNCTIONS}.user_entity_permissions", new_callable=AsyncMock, return_value=["read", "write"])
    @patch(f"{FUNCTIONS}.user_is_super_admin", new_callable=AsyncMock, return_value=False)
    async def test_write_access_is_not_enough(self, _super_admin, _entity, _api, mocked_user):
        assert await get_environment_actions(mocked_user, uuid4(), ModelStatus.ENABLED) == []
