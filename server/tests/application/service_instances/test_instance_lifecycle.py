from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from application.service_instances import service as service_module
from application.service_instances.schema import AdoptResourceItem, AdoptResources
from application.service_instances.service import ServiceInstanceService
from application.services.compiler import CompiledService, ServicePlan
from core.base_models import PatchBodyModel
from core.constants.model import ModelActions, ModelState, ModelStatus
from core.errors import DependencyError, EntityWrongState


def _instance(state=ModelState.PROVISIONED, status=ModelStatus.DONE, links=(), applied=3):
    return SimpleNamespace(
        id=uuid4(),
        service_id=uuid4(),
        environment_id=uuid4(),
        state=state,
        status=status,
        resources=list(links),
        workflow_id=uuid4(),
        spec_revision_applied=applied,
        anchor_resource_id=None,
    )


@pytest.fixture
def svc(monkeypatch, mock_event_sender, mock_audit_log_handler):
    monkeypatch.setattr(service_module, "ServiceInstanceResponse", Mock(model_validate=Mock(return_value="resp")))
    crud = Mock()
    for name in (
        "get_for_update",
        "get_by_id",
        "refresh",
        "add_links",
        "owned_resource_ids",
        "get_by_service_environment",
    ):
        setattr(crud, name, AsyncMock())
    crud.session = Mock(get=AsyncMock(return_value=SimpleNamespace(approval_required=False)), execute=AsyncMock())
    services = Mock()
    services.get_actions = AsyncMock(return_value=[ModelActions.EDIT, ModelActions.DELETE])
    services.compile = AsyncMock(
        return_value=CompiledService(plan=ServicePlan(service_id=uuid4(), environment_id=uuid4()), workflow=None)
    )
    services.update_service = AsyncMock()
    services.crud.get_by_id = AsyncMock()
    services.crud.refresh = AsyncMock()
    return ServiceInstanceService(
        crud=crud, event_sender=mock_event_sender, audit_log_handler=mock_audit_log_handler, service_service=services
    )


def _use(svc, instance):
    svc.crud.get_for_update.return_value = instance
    svc.crud.get_by_id.return_value = instance


class TestLifecycleActions:
    @pytest.mark.asyncio
    async def test_execute_queues_a_task_and_starts_fresh(self, svc):
        instance = _instance()
        _use(svc, instance)

        await svc.patch_action(instance.id, PatchBodyModel(action=ModelActions.EXECUTE), Mock(id=uuid4()))

        assert instance.status == ModelStatus.QUEUED and instance.workflow_id is None
        svc.event_sender.send_task.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_with_plan_errors_is_refused(self, svc):
        instance = _instance()
        _use(svc, instance)
        svc.services.compile.return_value = CompiledService(
            plan=ServicePlan(service_id=uuid4(), environment_id=uuid4(), errors=["needs a parent"]), workflow=None
        )

        with pytest.raises(ValueError, match="needs a parent"):
            await svc.patch_action(instance.id, PatchBodyModel(action=ModelActions.EXECUTE), Mock(id=uuid4()))
        svc.event_sender.send_task.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_environment_requiring_approval_waits(self, svc):
        instance = _instance(links=[SimpleNamespace(role="dependency")])
        _use(svc, instance)
        svc.crud.session.get.return_value = SimpleNamespace(approval_required=True)

        await svc.patch_action(instance.id, PatchBodyModel(action=ModelActions.DESTROY), Mock(id=uuid4()))

        assert (instance.state, instance.status) == (ModelState.DESTROY, ModelStatus.APPROVAL_PENDING)
        svc.event_sender.send_task.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_approve_queues_the_pending_run(self, svc):
        instance = _instance(state=ModelState.DESTROY, status=ModelStatus.APPROVAL_PENDING)
        _use(svc, instance)
        svc.crud.session.get.return_value = SimpleNamespace(approval_required=True)

        await svc.patch_action(instance.id, PatchBodyModel(action=ModelActions.APPROVE), Mock(id=uuid4()))

        assert instance.status == ModelStatus.QUEUED
        svc.event_sender.send_task.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reject_restores_the_previous_state(self, svc):
        instance = _instance(state=ModelState.DESTROY, status=ModelStatus.APPROVAL_PENDING, applied=3)
        _use(svc, instance)

        await svc.patch_action(instance.id, PatchBodyModel(action=ModelActions.REJECT), Mock(id=uuid4()))

        assert (instance.state, instance.status) == (ModelState.PROVISIONED, ModelStatus.DONE)

    @pytest.mark.asyncio
    async def test_running_instance_rejects_a_second_run(self, svc):
        instance = _instance(status=ModelStatus.IN_PROGRESS)
        _use(svc, instance)

        with pytest.raises(EntityWrongState, match="not allowed"):
            await svc.patch_action(instance.id, PatchBodyModel(action=ModelActions.EXECUTE), Mock(id=uuid4()))

    @pytest.mark.asyncio
    async def test_non_owner_cannot_deploy(self, svc):
        instance = _instance()
        _use(svc, instance)
        svc.services.get_actions.return_value = []

        with pytest.raises(EntityWrongState):
            await svc.patch_action(instance.id, PatchBodyModel(action=ModelActions.EXECUTE), Mock(id=uuid4()))


def _resource(rid, *, abstract=False, state=ModelState.PROVISIONED, template="aws_redis"):
    return SimpleNamespace(
        id=rid,
        name=f"res-{str(rid)[:4]}",
        abstract=abstract,
        state=state,
        template=SimpleNamespace(template=template),
        source_code_version_id=None,
        variables=[{"name": "node_type", "value": "small"}],
        parents=[],
        project=None,
    )


class TestAdopt:
    def _prepare(self, svc, instance, resources, owners=None, spec=None, spec_revision=3):
        svc.crud.get_by_service_environment.return_value = instance
        svc.crud.get_for_update.return_value = instance
        rows = Mock()
        rows.scalars.return_value.unique.return_value = resources
        svc.crud.session.execute.return_value = rows
        svc.crud.owned_resource_ids.return_value = owners or {}
        service = SimpleNamespace(id=instance.service_id, spec=spec or {}, spec_revision=spec_revision)

        async def bump(*_args, **_kwargs):
            service.spec_revision += 1

        svc.services.crud.get_by_id.return_value = service
        svc.services.update_service = AsyncMock(side_effect=bump)
        return service

    @pytest.mark.asyncio
    async def test_resource_owned_elsewhere_cannot_be_owned_again(self, svc):
        instance = _instance()
        rid = uuid4()
        self._prepare(svc, instance, [_resource(rid)], owners={rid: uuid4()})

        with pytest.raises(DependencyError, match="already owned"):
            await svc.adopt_resources(
                AdoptResources(
                    service_id=instance.service_id,
                    environment_id=instance.environment_id,
                    resources=[AdoptResourceItem(alias="cache", resource_id=rid)],
                ),
                Mock(id=uuid4()),
            )
        svc.crud.add_links.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_owned_resource_may_still_be_referenced(self, svc):
        instance = _instance()
        rid = uuid4()
        self._prepare(svc, instance, [_resource(rid)], owners={rid: uuid4()})

        await svc.adopt_resources(
            AdoptResources(
                service_id=instance.service_id,
                environment_id=instance.environment_id,
                resources=[AdoptResourceItem(alias="shared", resource_id=rid, role="referenced")],
            ),
            Mock(id=uuid4()),
        )

        svc.crud.add_links.assert_awaited_once_with(instance.id, [("shared", rid, "referenced")])
        svc.services.update_service.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_adopted_resources_are_folded_into_the_spec_and_instance_stays_current(self, svc):
        instance = _instance(applied=3)
        rid = uuid4()
        service = self._prepare(svc, instance, [_resource(rid)], spec_revision=3)

        await svc.adopt_resources(
            AdoptResources(
                service_id=instance.service_id,
                environment_id=instance.environment_id,
                resources=[AdoptResourceItem(alias="cache", resource_id=rid)],
            ),
            Mock(id=uuid4()),
        )

        spec = svc.services.update_service.await_args.args[1].spec
        assert [(c.alias, c.template, c.adopted, c.variables) for c in spec.claims] == [
            ("cache", "aws_redis", True, {"node_type": "small"})
        ]
        assert instance.spec_revision_applied == service.spec_revision == 4
        assert (instance.state, instance.status) == (ModelState.PROVISIONED, ModelStatus.DONE)

    @pytest.mark.asyncio
    async def test_out_of_date_instance_stays_out_of_date(self, svc):
        instance = _instance(applied=2)
        rid = uuid4()
        self._prepare(svc, instance, [_resource(rid)], spec_revision=3)

        await svc.adopt_resources(
            AdoptResources(
                service_id=instance.service_id,
                environment_id=instance.environment_id,
                resources=[AdoptResourceItem(alias="cache", resource_id=rid)],
            ),
            Mock(id=uuid4()),
        )

        assert instance.spec_revision_applied == 2

    @pytest.mark.asyncio
    async def test_busy_instance_refuses_adoption(self, svc):
        instance = _instance(status=ModelStatus.IN_PROGRESS)
        self._prepare(svc, instance, [])

        with pytest.raises(EntityWrongState, match="in progress"):
            await svc.adopt_resources(
                AdoptResources(
                    service_id=instance.service_id,
                    environment_id=instance.environment_id,
                    resources=[AdoptResourceItem(alias="cache", resource_id=uuid4())],
                ),
                Mock(id=uuid4()),
            )

    @pytest.mark.asyncio
    async def test_abstract_resource_cannot_be_owned(self, svc):
        instance = _instance()
        rid = uuid4()
        self._prepare(svc, instance, [_resource(rid, abstract=True)])

        with pytest.raises(ValueError, match="abstract"):
            await svc.adopt_resources(
                AdoptResources(
                    service_id=instance.service_id,
                    environment_id=instance.environment_id,
                    resources=[AdoptResourceItem(alias="anchor", resource_id=rid)],
                ),
                Mock(id=uuid4()),
            )
