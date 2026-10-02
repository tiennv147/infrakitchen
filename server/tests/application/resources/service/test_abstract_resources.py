from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from application.resources import functions as resource_functions
from application.resources.functions import get_resource_actions
from application.resources.task import ResourceTask
from core.base_models import PatchBodyModel
from core.constants.model import ModelActions, ModelState, ModelStatus
from core.errors import CannotProceed, EntityWrongState


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setattr(resource_functions, "user_entity_permissions", AsyncMock(return_value=["admin"]))
    return SimpleNamespace(id=uuid4())


class TestAbstractResourceActions:
    @pytest.mark.asyncio
    async def test_abstract_resource_has_no_plan_or_cascade_destroy(self, admin):
        actions = await get_resource_actions(
            admin,
            uuid4(),
            ModelStatus.DONE,
            ModelState.PROVISIONED,
            True,
            abstract=True,  # type: ignore[arg-type]
        )
        assert ModelActions.DESTROY in actions and ModelActions.EDIT in actions
        assert not {ModelActions.DRYRUN, ModelActions.CASCADE_DESTROY, "dryrun_with_temp_state"} & set(actions)

    @pytest.mark.asyncio
    async def test_managed_resource_keeps_every_action(self, admin):
        actions = await get_resource_actions(
            admin,
            uuid4(),
            ModelStatus.DONE,
            ModelState.PROVISIONED,
            False,  # type: ignore[arg-type]
        )
        assert {ModelActions.DRYRUN, ModelActions.CASCADE_DESTROY, ModelActions.EXECUTE} <= set(actions)


class TestAbstractResourcePatch:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("state", "status", "expected_state"),
        [
            (ModelState.PROVISION, ModelStatus.READY, ModelState.PROVISIONED),
            (ModelState.PROVISIONED, ModelStatus.DONE, ModelState.PROVISIONED),
            (ModelState.DESTROY, ModelStatus.READY, ModelState.DESTROYED),
        ],
    )
    async def test_execute_updates_the_record_without_a_task(
        self,
        state,
        status,
        expected_state,
        mock_resource_service,
        mock_resource_crud,
        mocked_resource,
        mock_event_sender,
        mocked_user,
    ):
        mocked_resource.abstract = True
        mocked_resource.state = state
        mocked_resource.status = status
        mock_resource_crud.get_by_id.return_value = mocked_resource

        result = await mock_resource_service.patch_action(
            resource_id=mocked_resource.id, body=PatchBodyModel(action=ModelActions.EXECUTE), requester=mocked_user
        )

        mock_event_sender.send_task.assert_not_awaited()
        assert (result.state, result.status) == (expected_state, ModelStatus.DONE)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", [ModelActions.DRYRUN, ModelActions.DRYRUN_WITH_TEMP_STATE])
    async def test_plan_is_refused(
        self, action, mock_resource_service, mock_resource_crud, mocked_resource, mock_event_sender, mocked_user
    ):
        mocked_resource.abstract = True
        mocked_resource.state = ModelState.PROVISIONED
        mocked_resource.status = ModelStatus.DONE
        mock_resource_crud.get_by_id.return_value = mocked_resource

        with pytest.raises(EntityWrongState, match="nothing to plan"):
            await mock_resource_service.patch_action(
                resource_id=mocked_resource.id, body=PatchBodyModel(action=action), requester=mocked_user
            )
        mock_event_sender.send_task.assert_not_awaited()


class TestWorkerBackstop:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", [ModelActions.EXECUTE, ModelActions.DRYRUN])
    async def test_worker_never_runs_opentofu_for_abstract_resources(self, action):
        task = ResourceTask.__new__(ResourceTask)
        task.logger = Mock()
        task.user = None
        task.action = action
        task.resource_instance = SimpleNamespace(id=uuid4(), abstract=True)  # type: ignore[assignment]

        with pytest.raises(CannotProceed, match="refusing to run OpenTofu"):
            await task.start_pipeline()
