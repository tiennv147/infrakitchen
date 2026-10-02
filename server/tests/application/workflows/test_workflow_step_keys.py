"""Regression tests for step-keyed workflows: several steps may share one template.

Blueprint workflows carry no step keys and must keep resolving by template id.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest

from application.blueprints.service import BlueprintService
from application.workflows.functions import topological_levels
from application.workflows.model import WorkflowStep
from application.workflows.schema import WiringRule, WorkflowResponse, WorkflowStepResponse
from core.constants.model import ModelStatus, WorkflowAction
from core.errors import CannotProceed


def _step(
    template_id: UUID,
    *,
    step_key: str | None = None,
    status: str = ModelStatus.PENDING,
    resource_id: UUID | None = None,
    parent_step_keys: list[str] | None = None,
    storage_path: str | None = None,
    workspace_id: UUID | None = None,
    source_code_version_id: UUID | None = None,
    resolved_variables: dict | None = None,
) -> WorkflowStep:
    return WorkflowStep(
        id=uuid4(),
        workflow_id=uuid4(),
        template_id=template_id,
        resource_id=resource_id,
        source_code_version_id=source_code_version_id,
        parent_resource_ids=[],
        integration_ids=[],
        secret_ids=[],
        storage_id=None,
        position=0,
        status=status,
        resolved_variables=resolved_variables or {},
        step_key=step_key,
        parent_step_keys=parent_step_keys or [],
        storage_path=storage_path,
        workspace_id=workspace_id,
    )


def _task(steps: list[WorkflowStep], wiring: list[WiringRule]):
    from application.workflows.task import WorkflowTask

    task = WorkflowTask.__new__(WorkflowTask)
    task.workflow_instance = SimpleNamespace(steps=steps)
    task.workflow_pydantic = WorkflowResponse(
        id=uuid4(),
        action=WorkflowAction.CREATE,
        status=ModelStatus.IN_PROGRESS,
        steps=[
            WorkflowStepResponse(
                id=s.id,
                template_id=s.template_id,
                resource_id=s.resource_id,
                position=s.position,
                status=s.status,
                step_key=s.step_key,
            )
            for s in steps
        ],
        wiring_snapshot=wiring,
        created_at=datetime.now(),
    )
    task.resource_service = Mock()
    task.logger = Mock()
    task.user = Mock()
    return task


def _resource(outputs: dict[str, str]):
    return SimpleNamespace(outputs=[SimpleNamespace(name=k, value=v) for k, v in outputs.items()])


class TestResolveWiredVariablesByStepKey:
    @pytest.mark.asyncio
    async def test_two_steps_sharing_a_template_wire_independently(self):
        redis_tid, app_tid = uuid4(), uuid4()
        cache_rid, sessions_rid = uuid4(), uuid4()
        cache = _step(redis_tid, step_key="cache", status=ModelStatus.DONE, resource_id=cache_rid)
        sessions = _step(redis_tid, step_key="sessions", status=ModelStatus.DONE, resource_id=sessions_rid)
        consumer = _step(app_tid, step_key="app")
        wiring = [
            WiringRule(
                source_template_id=redis_tid,
                source_output="endpoint",
                target_template_id=app_tid,
                target_variable="cache_url",
                source_step_key="cache",
                target_step_key="app",
            ),
            WiringRule(
                source_template_id=redis_tid,
                source_output="endpoint",
                target_template_id=app_tid,
                target_variable="sessions_url",
                source_step_key="sessions",
                target_step_key="app",
            ),
        ]
        task = _task([cache, sessions, consumer], wiring)
        by_id = {cache_rid: _resource({"endpoint": "cache:6379"}), sessions_rid: _resource({"endpoint": "sess:6379"})}
        task.resource_service.get_by_id = AsyncMock(side_effect=lambda rid: by_id[rid])

        assert await task._resolve_wired_variables(consumer) == {
            "cache_url": "cache:6379",
            "sessions_url": "sess:6379",
        }

    @pytest.mark.asyncio
    async def test_keyed_rule_does_not_leak_to_sibling_with_same_template(self):
        redis_tid = uuid4()
        source_rid = uuid4()
        source = _step(uuid4(), step_key="net", status=ModelStatus.DONE, resource_id=source_rid)
        first = _step(redis_tid, step_key="cache")
        second = _step(redis_tid, step_key="sessions")
        wiring = [
            WiringRule(
                source_template_id=source.template_id,
                source_output="subnet",
                target_template_id=redis_tid,
                target_variable="subnet_id",
                source_step_key="net",
                target_step_key="cache",
            )
        ]
        task = _task([source, first, second], wiring)
        task.resource_service.get_by_id = AsyncMock(return_value=_resource({"subnet": "subnet-1"}))

        assert await task._resolve_wired_variables(first) == {"subnet_id": "subnet-1"}
        assert await task._resolve_wired_variables(second) == {}

    @pytest.mark.asyncio
    async def test_blueprint_workflow_without_keys_still_resolves_by_template(self):
        vpc_tid, db_tid = uuid4(), uuid4()
        vpc_rid = uuid4()
        vpc = _step(vpc_tid, status=ModelStatus.DONE, resource_id=vpc_rid)
        db = _step(db_tid)
        wiring = [
            WiringRule(
                source_template_id=vpc_tid, source_output="vpc_id", target_template_id=db_tid, target_variable="vpc"
            )
        ]
        task = _task([vpc, db], wiring)
        task.resource_service.get_by_id = AsyncMock(return_value=_resource({"vpc_id": "vpc-123"}))

        assert await task._resolve_wired_variables(db) == {"vpc": "vpc-123"}


class TestManageResourceKeyedSteps:
    def _prepared(self, step: WorkflowStep, steps: list[WorkflowStep]):
        task = _task(steps, [])
        template = SimpleNamespace(
            id=step.template_id,
            template="aws_redis",
            parents=[SimpleNamespace(id=uuid4())],
            configuration=SimpleNamespace(naming_convention="redis"),
        )
        task.template_service = Mock(get_by_id=AsyncMock(return_value=template))
        task.resource_service.create = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        task.change_step_status = AsyncMock()
        return task

    @pytest.mark.asyncio
    async def test_parent_step_keys_and_pinned_placement_are_applied(self):
        anchor_rid, workspace_id = uuid4(), uuid4()
        parent = _step(uuid4(), step_key="cluster", status=ModelStatus.DONE, resource_id=anchor_rid)
        child = _step(
            uuid4(),
            step_key="user",
            parent_step_keys=["cluster"],
            storage_path="services/dev/checkout/user/terraform.tfstate",
            workspace_id=workspace_id,
        )
        task = self._prepared(child, [parent, child])

        await task.manage_resource(child)

        created = task.resource_service.create.await_args.kwargs["resource"]
        assert created.parents == [anchor_rid]
        assert created.storage_path == "services/dev/checkout/user/terraform.tfstate"
        assert created.workspace_id == workspace_id

    @pytest.mark.asyncio
    async def test_parent_step_without_resource_fails_clearly(self):
        parent = _step(uuid4(), step_key="cluster")
        child = _step(uuid4(), step_key="user", parent_step_keys=["cluster"])
        task = self._prepared(child, [parent, child])
        task.change_step_status = AsyncMock()

        with pytest.raises(CannotProceed, match="Parent step 'cluster'"):
            await task.manage_resource(child)

    @pytest.mark.asyncio
    async def test_unkeyed_step_keeps_default_storage_path(self):
        step = _step(uuid4())
        task = self._prepared(step, [step])

        await task.manage_resource(step)

        created = task.resource_service.create.await_args.kwargs["resource"]
        assert created.storage_path == "service-catalog/aws_redis/redis/terraform.tfstate"
        assert created.workspace_id is None

    @pytest.mark.asyncio
    async def test_unset_optional_variables_take_the_version_default(self):
        step = _step(uuid4(), source_code_version_id=uuid4(), resolved_variables={"name": "app"})
        task = self._prepared(step, [step])

        def var(name: str, value, **flags):
            return SimpleNamespace(
                name=name,
                value=value,
                required=flags.get("required", False),
                sensitive=flags.get("sensitive", False),
                restricted=flags.get("restricted", False),
            )

        task.resource_service.get_variable_schema = AsyncMock(
            return_value=[
                var("name", "default-name", required=True),
                var("tags", {}),
                var("timeout", 300),
                var("region", None, required=True),
                var("password", None, sensitive=True),
                var("owner", "platform", restricted=True),
            ]
        )

        await task.manage_resource(step)

        created = task.resource_service.create.await_args.kwargs["resource"]
        assert {v.name: v.value for v in created.variables} == {"name": "app", "tags": {}, "timeout": 300}


class TestTopologicalLevels:
    def test_levels_group_independent_nodes(self):
        assert topological_levels(["a", "b", "c"], [("a", "c"), ("b", "c")]) == [("a", 0), ("b", 0), ("c", 1)]

    def test_cycle_is_rejected(self):
        with pytest.raises(ValueError, match="Circular"):
            topological_levels(["a", "b"], [("a", "b"), ("b", "a")])

    def test_blueprint_sort_keeps_its_error_message(self):
        a, b = uuid4(), uuid4()
        rules = [
            WiringRule(source_template_id=a, source_output="x", target_template_id=b, target_variable="y"),
            WiringRule(source_template_id=b, source_output="x", target_template_id=a, target_variable="y"),
        ]
        with pytest.raises(ValueError, match="blueprint wiring"):
            BlueprintService._topological_sort([a, b], rules)
