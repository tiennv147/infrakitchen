from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from application.resources.schema import Variables
from application.workflows.model import WorkflowStep
from application.workflows.schema import WorkflowResponse, WorkflowStepResponse
from core.constants.model import ModelActions, ModelState, ModelStatus, WorkflowAction
from core.errors import CannotProceed


def _task(step: WorkflowStep, parent=(None, None)):
    from application.workflows.task import WorkflowTask

    task = WorkflowTask.__new__(WorkflowTask)
    task.workflow_instance = SimpleNamespace(
        steps=[step], status=ModelStatus.IN_PROGRESS, parent_entity_name=parent[0], parent_entity_id=parent[1]
    )
    task.workflow_pydantic = WorkflowResponse(
        id=uuid4(),
        action=WorkflowAction.CREATE,
        status=ModelStatus.IN_PROGRESS,
        steps=[
            WorkflowStepResponse(
                id=step.id, template_id=step.template_id, resource_id=step.resource_id, position=0, status=step.status
            )
        ],
        created_at=datetime.now(),
    )
    task.resource_service = Mock(update_resource=AsyncMock(), patch_action=AsyncMock())
    task.logger = Mock()
    task.user = SimpleNamespace(id=uuid4())
    task.change_step_status = AsyncMock(side_effect=lambda s, new_status=None, **_: setattr(s, "status", new_status))
    return task


def _step(resource_id=None, variables=None, version=None):
    return WorkflowStep(
        id=uuid4(),
        workflow_id=uuid4(),
        template_id=uuid4(),
        resource_id=resource_id,
        parent_resource_ids=[],
        integration_ids=[],
        secret_ids=[],
        position=0,
        status=ModelStatus.PENDING,
        resolved_variables=variables or {},
        step_key="cache",
        parent_step_keys=[],
        source_code_version_id=version,
    )


def _resource(state=ModelState.PROVISIONED, status=ModelStatus.DONE, variables=None, version=None):
    return SimpleNamespace(
        id=uuid4(),
        state=state,
        status=status,
        variables=[Variables(name=k, value=v) for k, v in (variables or {}).items()],
        source_code_version=SimpleNamespace(id=version) if version else None,
    )


class TestReconcileExistingResource:
    @pytest.mark.asyncio
    async def test_unchanged_provisioned_resource_completes_the_step(self):
        resource = _resource(variables={"node_type": "small"})
        step = _step(resource.id, {"node_type": "small"})
        task = _task(step)
        task.resource_service.get_by_id = AsyncMock(return_value=resource)

        await task.reconcile_existing_resource(step)

        task.resource_service.update_resource.assert_not_awaited()
        task.resource_service.patch_action.assert_not_awaited()
        assert step.status == ModelStatus.DONE

    @pytest.mark.asyncio
    async def test_changed_variables_update_approve_and_execute_with_trace(self):
        before = _resource(variables={"node_type": "small", "engine": "7"})
        after = _resource(status=ModelStatus.READY, variables={"node_type": "large", "engine": "7"})
        step = _step(before.id, {"node_type": "large", "engine": "7"})
        task = _task(step)
        task.resource_service.get_by_id = AsyncMock(side_effect=[before, after])
        task.resource_service.patch_action = AsyncMock(
            side_effect=[SimpleNamespace(status=ModelStatus.READY), SimpleNamespace(status=ModelStatus.QUEUED)]
        )

        await task.reconcile_existing_resource(step)

        update = task.resource_service.update_resource.await_args.args[1]
        assert {v.name: v.value for v in update.variables} == {"node_type": "large", "engine": "7"}
        assert update.source_code_version_id is None
        actions = [c.args[1].action for c in task.resource_service.patch_action.await_args_list]
        assert actions == [ModelActions.APPROVE, ModelActions.EXECUTE]
        assert task.resource_service.patch_action.await_args_list[1].kwargs["trace_id"] == str(
            task.workflow_pydantic.id
        )
        assert step.status == ModelStatus.QUEUED

    @pytest.mark.asyncio
    async def test_version_bump_is_sent(self):
        old, new = uuid4(), uuid4()
        before = _resource(variables={}, version=old)
        step = _step(before.id, {}, version=new)
        task = _task(step)
        task.resource_service.get_by_id = AsyncMock(side_effect=[before, _resource(status=ModelStatus.READY)])
        task.resource_service.patch_action = AsyncMock(return_value=SimpleNamespace(status=ModelStatus.QUEUED))

        await task.reconcile_existing_resource(step)

        assert task.resource_service.update_resource.await_args.args[1].source_code_version_id == new

    @pytest.mark.asyncio
    async def test_failed_resource_without_changes_is_re_executed(self):
        resource = _resource(state=ModelState.PROVISION, status=ModelStatus.ERROR)
        step = _step(resource.id)
        task = _task(step)
        task.resource_service.get_by_id = AsyncMock(return_value=resource)
        task.resource_service.patch_action = AsyncMock(return_value=SimpleNamespace(status=ModelStatus.QUEUED))

        await task.reconcile_existing_resource(step)

        task.resource_service.update_resource.assert_not_awaited()
        assert task.resource_service.patch_action.await_args.args[1].action == ModelActions.EXECUTE

    @pytest.mark.asyncio
    async def test_destroyed_resource_cannot_be_reconciled(self):
        resource = _resource(state=ModelState.DESTROYED)
        step = _step(resource.id)
        task = _task(step)
        task.resource_service.get_by_id = AsyncMock(return_value=resource)

        with pytest.raises(CannotProceed, match="destroyed"):
            await task.reconcile_existing_resource(step)


class TestNotifyParent:
    @pytest.mark.asyncio
    async def test_parent_gets_an_execute_task(self):
        parent_id = uuid4()
        task = _task(_step(), parent=("service_instance", parent_id))
        with patch("application.workflows.task.EventSender") as sender_cls:
            sender_cls.return_value.send_task = AsyncMock()
            await task._notify_parent()

        sender_cls.assert_called_once_with(entity_name="service_instance")
        kwargs = sender_cls.return_value.send_task.await_args.kwargs
        assert sender_cls.return_value.send_task.await_args.args[0] == parent_id
        assert kwargs["action"] == ModelActions.EXECUTE
        assert kwargs["extra_metadata"] == {"workflow_id": str(task.workflow_pydantic.id)}

    @pytest.mark.asyncio
    async def test_workflow_without_parent_notifies_nobody(self):
        task = _task(_step())
        with patch("application.workflows.task.EventSender") as sender_cls:
            await task._notify_parent()
        sender_cls.assert_not_called()
