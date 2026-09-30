from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from application.service_instances import task as task_module
from application.service_instances.task import ServiceInstanceTask
from application.services.compiler import CompiledService, ServicePlan
from application.workflows.schema import WorkflowCreate, WorkflowStepCreate
from core.constants.model import ModelActions, ModelState, ModelStatus, WorkflowAction


def _link(alias, role="dependency", state=ModelState.PROVISIONED, parents=()):
    rid = uuid4()
    return SimpleNamespace(
        id=uuid4(),
        alias=alias,
        role=role,
        resource_id=rid,
        resource=SimpleNamespace(id=rid, state=state, template_id=uuid4(), parents=list(parents)),
    )


def _task(monkeypatch, *, state=ModelState.PROVISION, status=ModelStatus.QUEUED, links=(), workflow=None, spec=None):
    monkeypatch.setattr(task_module, "ServiceInstanceResponse", Mock(model_validate=Mock(return_value="resp")))
    instance = SimpleNamespace(
        id=uuid4(),
        service_id=uuid4(),
        environment_id=uuid4(),
        state=state,
        status=status,
        resources=list(links),
        workflow_id=workflow.id if workflow else None,
        spec_revision_applied=None,
        target_spec_revision=None,
        workload_version=None,
    )
    service_service = Mock()
    service_service.compile = AsyncMock()
    service_service.crud.get_by_id = AsyncMock(return_value=SimpleNamespace(spec_revision=7, spec=spec or {}))
    workflow_service = Mock()
    workflow_service.create = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    workflow_service.patch_action = AsyncMock()
    workflow_service.crud.get_by_id = AsyncMock(return_value=workflow)
    crud = Mock(refresh=AsyncMock(), add_links=AsyncMock(), remove_links=AsyncMock())
    return ServiceInstanceTask(
        session=Mock(commit=AsyncMock(), get=AsyncMock(return_value=SimpleNamespace(name="dev"))),
        crud=crud,
        service_service=service_service,
        workflow_service=workflow_service,
        instance=instance,  # type: ignore[arg-type]
        logger=Mock(save_log=AsyncMock()),
        user=SimpleNamespace(id=uuid4()),  # type: ignore[arg-type]
        event_sender=Mock(send_event=AsyncMock()),
        action=ModelActions.EXECUTE,
    )


def _compiled(*steps: WorkflowStepCreate, errors=()):
    plan = ServicePlan(service_id=uuid4(), environment_id=uuid4(), errors=list(errors))
    workflow = None if errors else WorkflowCreate(created_by=uuid4(), steps=list(steps))
    return CompiledService(plan=plan, workflow=workflow)


def _workflow(action=WorkflowAction.CREATE, status=ModelStatus.DONE, steps=()):
    return SimpleNamespace(id=uuid4(), action=action, status=status, steps=list(steps), error_message=None)


class TestExecute:
    @pytest.mark.asyncio
    async def test_starts_a_create_workflow_linked_back_to_the_instance(self, monkeypatch):
        task = _task(monkeypatch)
        task.service_service.compile.return_value = _compiled(
            WorkflowStepCreate(template_id=uuid4(), position=0, step_key="cache")
        )

        await task.start_pipeline()

        body = task.workflow_service.create.await_args.args[0]
        assert body["parent_entity_name"] == "service_instance"
        assert body["parent_entity_id"] == str(task.instance.id)
        task.workflow_service.patch_action.assert_awaited_once()
        assert task.instance.status == ModelStatus.IN_PROGRESS
        assert task.instance.target_spec_revision == 7
        assert task.instance.workflow_id == task.workflow_service.create.return_value.id

    @pytest.mark.asyncio
    async def test_all_no_op_plan_finishes_without_a_workflow(self, monkeypatch):
        task = _task(monkeypatch, spec={"claims": [{"alias": "cache", "template": "aws_redis"}]})
        task.instance.resources = [_link("cache")]
        task.service_service.compile.return_value = _compiled(
            WorkflowStepCreate(template_id=uuid4(), position=0, step_key="cache", status=ModelStatus.DONE)
        )

        await task.start_pipeline()

        task.workflow_service.create.assert_not_awaited()
        assert (task.instance.state, task.instance.status) == (ModelState.PROVISIONED, ModelStatus.DONE)
        assert task.instance.spec_revision_applied == 7

    @pytest.mark.asyncio
    async def test_plan_errors_fail_the_instance(self, monkeypatch):
        task = _task(monkeypatch)
        task.service_service.compile.return_value = _compiled(errors=["needs a parent"])

        await task.start_pipeline()

        task.logger.error.assert_called_with("needs a parent")
        assert task.instance.status == ModelStatus.ERROR

    @pytest.mark.asyncio
    async def test_workflow_done_links_new_resources_and_destroys_unclaimed_but_not_referenced(self, monkeypatch):
        created = uuid4()
        workflow = _workflow(steps=[SimpleNamespace(step_key="cache", resource_id=created)])
        old = _link("old_cache")
        shared = _link("shared", role="referenced")
        task = _task(
            monkeypatch,
            status=ModelStatus.IN_PROGRESS,
            links=[old, shared],
            workflow=workflow,
            spec={"claims": [{"alias": "cache", "template": "aws_redis"}]},
        )

        await task.start_pipeline()

        task.crud.add_links.assert_awaited_once_with(task.instance.id, [("cache", created, "dependency")])
        destroy = task.workflow_service.create.await_args.args[0]
        assert destroy["action"] == WorkflowAction.DESTROY
        assert [s["step_key"] for s in destroy["steps"]] == ["old_cache"]
        assert task.instance.status == ModelStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_destroy_of_unclaimed_done_finishes_reconcile(self, monkeypatch):
        gone = _link("old_cache", state=ModelState.DESTROYED)
        task = _task(
            monkeypatch,
            status=ModelStatus.IN_PROGRESS,
            links=[gone],
            workflow=_workflow(action=WorkflowAction.DESTROY),
        )
        task.instance.target_spec_revision = 4

        await task.start_pipeline()

        task.crud.remove_links.assert_awaited_once_with([gone.id])
        assert task.instance.spec_revision_applied == 4
        assert (task.instance.state, task.instance.status) == (ModelState.PROVISIONED, ModelStatus.DONE)

    @pytest.mark.asyncio
    async def test_running_workflow_callback_is_ignored(self, monkeypatch):
        task = _task(monkeypatch, status=ModelStatus.IN_PROGRESS, workflow=_workflow(status=ModelStatus.IN_PROGRESS))

        await task.start_pipeline()

        task.session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_workflow_marks_instance_failed(self, monkeypatch):
        task = _task(monkeypatch, status=ModelStatus.IN_PROGRESS, workflow=_workflow(status=ModelStatus.ERROR))

        await task.start_pipeline()

        assert task.instance.status == ModelStatus.ERROR
        task.workflow_service.patch_action.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retry_resumes_the_failed_workflow(self, monkeypatch):
        workflow = _workflow(status=ModelStatus.ERROR)
        task = _task(monkeypatch, status=ModelStatus.QUEUED, workflow=workflow)

        await task.start_pipeline()

        assert task.workflow_service.patch_action.await_args.args[0] == workflow.id
        task.workflow_service.create.assert_not_awaited()
        assert task.instance.status == ModelStatus.IN_PROGRESS


class TestDestroy:
    @pytest.mark.asyncio
    async def test_destroys_dependents_before_their_parents_and_skips_referenced(self, monkeypatch):
        cluster = _link("cluster")
        acl = _link("acl", parents=[cluster.resource])
        shared = _link("shared_kafka", role="referenced")
        task = _task(monkeypatch, state=ModelState.DESTROY, links=[cluster, acl, shared])

        await task.start_pipeline()

        body = task.workflow_service.create.await_args.args[0]
        assert body["action"] == WorkflowAction.DESTROY
        positions = {s["step_key"]: s["position"] for s in body["steps"]}
        assert positions == {"acl": 0, "cluster": 1}

    @pytest.mark.asyncio
    async def test_nothing_owned_is_destroyed_immediately(self, monkeypatch):
        task = _task(monkeypatch, state=ModelState.DESTROY, links=[_link("shared", role="referenced")])

        await task.start_pipeline()

        task.workflow_service.create.assert_not_awaited()
        assert (task.instance.state, task.instance.status) == (ModelState.DESTROYED, ModelStatus.DONE)

    @pytest.mark.asyncio
    async def test_destroy_done_unlinks_owned_but_keeps_referenced(self, monkeypatch):
        owned = _link("cache", state=ModelState.DESTROYED)
        shared = _link("shared", role="referenced", state=ModelState.DESTROYED)
        task = _task(
            monkeypatch,
            state=ModelState.DESTROY,
            status=ModelStatus.IN_PROGRESS,
            links=[owned, shared],
            workflow=_workflow(action=WorkflowAction.DESTROY),
        )
        task.instance.spec_revision_applied = 3

        await task.start_pipeline()

        task.crud.remove_links.assert_awaited_once_with([owned.id])
        assert task.instance.spec_revision_applied is None
        assert (task.instance.state, task.instance.status) == (ModelState.DESTROYED, ModelStatus.DONE)


class TestBindingsStep:
    def _with_delivery(self, task, *, apply=None, remove=None):
        delivery = Mock(apply=apply or AsyncMock(return_value=None), remove=remove or AsyncMock())
        task.binding_delivery = delivery
        task.session.get = AsyncMock(return_value=SimpleNamespace(name="dev"))
        return delivery

    @pytest.mark.asyncio
    async def test_bindings_are_written_before_the_instance_is_marked_done(self, monkeypatch):
        task = _task(monkeypatch, spec={"claims": []})
        task.service_service.compile.return_value = _compiled()
        state = {"sink": "aws_secrets_manager", "path": "config-svc", "keys": ["A"]}
        self._with_delivery(task, apply=AsyncMock(return_value=state))

        await task.start_pipeline()

        assert task.instance.binding_state == state
        assert (task.instance.state, task.instance.status) == (ModelState.PROVISIONED, ModelStatus.DONE)

    @pytest.mark.asyncio
    async def test_sink_failure_fails_the_instance_and_keeps_it_out_of_date(self, monkeypatch):
        task = _task(monkeypatch, spec={"claims": []})
        task.service_service.compile.return_value = _compiled()
        self._with_delivery(task, apply=AsyncMock(side_effect=RuntimeError("AccessDenied")))

        await task.start_pipeline()

        assert task.instance.status == ModelStatus.ERROR
        assert task.instance.spec_revision_applied is None
        task.logger.error.assert_called_with("Bindings failed: AccessDenied")

    @pytest.mark.asyncio
    async def test_destroy_removes_bindings(self, monkeypatch):
        task = _task(monkeypatch, state=ModelState.DESTROY, links=[_link("shared", role="referenced")])
        task.instance.binding_state = {"path": "config-svc"}
        delivery = self._with_delivery(task)

        await task.start_pipeline()

        delivery.remove.assert_awaited_once()
        assert task.instance.binding_state is None
        assert task.instance.state == ModelState.DESTROYED


MANAGED = {"claims": [], "workload": {"mode": "managed", "chart": "charts/app", "chart_version": "1.0.0"}}


def _workload_step(status=ModelStatus.PENDING):
    return WorkflowStepCreate(template_id=uuid4(), position=0, step_key="workload", status=status)


class TestWorkloadStep:
    def _deployments(self, task, active=None):
        deployments = Mock(active_for=AsyncMock(return_value=active), finish=AsyncMock())
        task.deployments = deployments
        task.service_service.compile_workload = AsyncMock(return_value=_compiled(_workload_step()))
        return deployments

    @pytest.mark.asyncio
    async def test_workload_is_applied_after_claims_and_bindings(self, monkeypatch):
        task = _task(monkeypatch, spec=MANAGED)
        task.instance.workload_version = "1.2.3"
        task.service_service.compile.return_value = _compiled()
        self._deployments(task)

        await task.start_pipeline()

        task.service_service.compile_workload.assert_awaited_once()
        assert task.service_service.compile_workload.await_args.args[2] == "1.2.3"
        created = task.workflow_service.create.await_args.args[0]
        assert [s["step_key"] for s in created["steps"]] == ["workload"]
        assert task.instance.status == ModelStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_no_version_yet_finishes_without_the_workload(self, monkeypatch):
        task = _task(monkeypatch, spec=MANAGED)
        task.service_service.compile.return_value = _compiled()
        self._deployments(task)

        await task.start_pipeline()

        task.service_service.compile_workload.assert_not_awaited()
        assert (task.instance.status, task.instance.spec_revision_applied) == (ModelStatus.DONE, 7)

    @pytest.mark.asyncio
    async def test_external_workload_is_never_applied(self, monkeypatch):
        task = _task(monkeypatch, spec={**MANAGED, "workload": {**MANAGED["workload"], "mode": "external"}})
        task.instance.workload_version = "1.2.3"
        task.service_service.compile.return_value = _compiled()
        self._deployments(task)

        await task.start_pipeline()

        task.service_service.compile_workload.assert_not_awaited()
        assert task.instance.status == ModelStatus.DONE

    @pytest.mark.asyncio
    async def test_deployment_runs_only_the_workload(self, monkeypatch):
        task = _task(monkeypatch, spec=MANAGED, state=ModelState.PROVISIONED)
        self._deployments(task, active=SimpleNamespace(version="2.0.0"))

        await task.start_pipeline()

        task.service_service.compile.assert_not_awaited()
        assert task.service_service.compile_workload.await_args.args[2] == "2.0.0"
        assert task.instance.status == ModelStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_finished_deployment_records_the_version_but_not_a_spec_revision(self, monkeypatch):
        workflow = _workflow(steps=[SimpleNamespace(step_key="workload", resource_id=uuid4())])
        task = _task(monkeypatch, spec=MANAGED, workflow=workflow, status=ModelStatus.IN_PROGRESS)
        task.instance.spec_revision_applied = 5
        task.instance.target_spec_revision = 6
        deployments = self._deployments(task, active=SimpleNamespace(version="2.0.0"))

        await task.start_pipeline()

        assert task.instance.workload_version == "2.0.0"
        assert task.instance.spec_revision_applied == 5
        assert task.instance.status == ModelStatus.DONE
        deployments.finish.assert_awaited_once()
        assert deployments.finish.await_args.kwargs["ok"] is True
        link = task.crud.add_links.await_args.args[1][0]
        assert (link[0], link[2]) == ("workload", "workload")

    @pytest.mark.asyncio
    async def test_values_failure_fails_the_deployment(self, monkeypatch):
        task = _task(monkeypatch, spec=MANAGED, state=ModelState.PROVISIONED)
        deployments = self._deployments(task, active=SimpleNamespace(version="2.0.0"))
        task.workload_values = Mock(resolve=AsyncMock(side_effect=ValueError("Values file x.yaml not found at main")))

        await task.start_pipeline()

        assert task.instance.status == ModelStatus.ERROR
        assert deployments.finish.await_args.kwargs == {
            "ok": False,
            "message": "Workload values failed: Values file x.yaml not found at main",
            "requester": task.user,
        }

    @pytest.mark.asyncio
    async def test_destroy_takes_the_workload_down_first(self, monkeypatch):
        db = _link("db")
        app = _link("workload", role="workload")
        task = _task(monkeypatch, state=ModelState.DESTROY, links=[db, app])

        await task.start_pipeline()

        steps = {s["step_key"]: s["position"] for s in task.workflow_service.create.await_args.args[0]["steps"]}
        assert steps["workload"] < steps["db"]
