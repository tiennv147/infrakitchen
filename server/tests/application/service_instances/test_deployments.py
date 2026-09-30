from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from application.service_instances.deployments import (
    DeploymentService,
    DeploymentView,
    plan_dispatch,
    rollout_key,
)
from application.service_instances.model import DeploymentStatus as S


def _batch(*statuses: str, instances=None, batch=None):
    batch = batch or uuid4()
    instances = instances or [uuid4() for _ in statuses]
    return [
        DeploymentView(
            id=uuid4(), batch_id=batch, position=i, instance_id=instances[i], status=s, environment_name=f"env{i}"
        )
        for i, s in enumerate(statuses)
    ]


class TestRolloutOrder:
    def test_tier_then_rank_then_name(self):
        # Unknown tiers roll out with staging.
        envs = [("prod", 0, "p"), ("staging", 2, "s-us"), ("dev", 0, "d"), ("staging", 1, "s-eu"), ("qa", 0, "q")]
        ordered = sorted(envs, key=lambda e: rollout_key(*e))
        assert [e[2] for e in ordered] == ["d", "q", "s-eu", "s-us", "p"]


class TestPlanDispatch:
    def test_first_environment_starts_alone(self):
        batch = _batch(S.WAITING, S.WAITING, S.WAITING)
        plan = plan_dispatch(batch, busy=set(), unavailable={})
        assert plan.start == [batch[0].id] and plan.cancel == []

    def test_next_environment_starts_after_the_previous_is_done(self):
        batch = _batch(S.DONE, S.WAITING, S.WAITING)
        assert plan_dispatch(batch, busy=set(), unavailable={}).start == [batch[1].id]

    def test_nothing_starts_while_one_is_running(self):
        batch = _batch(S.DONE, S.ACTIVE, S.WAITING)
        plan = plan_dispatch(batch, busy=set(), unavailable={})
        assert plan.start == [] and plan.cancel == []

    def test_a_failure_cancels_the_rest_of_the_batch(self):
        batch = _batch(S.DONE, S.ERROR, S.WAITING, S.WAITING)
        plan = plan_dispatch(batch, busy=set(), unavailable={})
        assert plan.start == []
        assert [c[0] for c in plan.cancel] == [batch[2].id, batch[3].id]
        assert plan.cancel[0][1] == "Stopped because env1 is error"

    def test_busy_instance_waits_without_being_cancelled(self):
        batch = _batch(S.WAITING)
        plan = plan_dispatch(batch, busy={batch[0].instance_id}, unavailable={})
        assert plan.start == [] and plan.cancel == []

    def test_destroyed_instance_cancels_and_stops_the_batch(self):
        batch = _batch(S.WAITING, S.WAITING)
        plan = plan_dispatch(batch, busy=set(), unavailable={batch[0].instance_id: "the service is destroyed"})
        assert plan.cancel == [
            (batch[0].id, "the service is destroyed"),
            (batch[1].id, "Stopped because env0: the service is destroyed"),
        ]

    def test_two_batches_never_run_on_the_same_instance_at_once(self):
        shared = uuid4()
        first = _batch(S.WAITING, instances=[shared])
        second = _batch(S.WAITING, instances=[shared])
        plan = plan_dispatch(first + second, busy=set(), unavailable={})
        assert len(plan.start) == 1

    def test_independent_batches_run_in_parallel(self):
        plan = plan_dispatch(_batch(S.WAITING) + _batch(S.WAITING), busy=set(), unavailable={})
        assert len(plan.start) == 2


def _runner(service):
    crud = Mock(session=Mock(execute=AsyncMock()))
    services = Mock()
    services.crud.get_by_id = AsyncMock(return_value=service)
    return SimpleNamespace(crud=crud, services=services, queue_run=AsyncMock(), send=AsyncMock())


class TestRequest:
    @pytest.mark.asyncio
    async def test_external_workload_cannot_be_deployed_here(self):
        service = SimpleNamespace(id=uuid4(), spec={"workload": {"chart": "c", "chart_version": "1"}})
        deployments = DeploymentService(_runner(service))  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="not managed by InfraKitchen"):
            await deployments.request(service.id, "1.0.0", None, SimpleNamespace(id=uuid4()))  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_version_must_be_an_image_tag(self):
        deployments = DeploymentService(_runner(None))  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="not a valid image tag"):
            await deployments.request(uuid4(), "latest; rm -rf /", None, SimpleNamespace(id=uuid4()))  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_environment_without_infrastructure_is_rejected(self, monkeypatch):
        service = SimpleNamespace(
            id=uuid4(), spec={"workload": {"mode": "managed", "chart": "c", "chart_version": "1"}}
        )
        deployments = DeploymentService(_runner(service))  # type: ignore[arg-type]
        instance = SimpleNamespace(id=uuid4(), spec_revision_applied=None, state="provision")
        environment = SimpleNamespace(id=uuid4(), name="shop-dev", tier="dev", rank=0)
        monkeypatch.setattr(deployments, "_instances", AsyncMock(return_value=[(instance, environment)]))
        with pytest.raises(ValueError, match="to shop-dev first"):
            await deployments.request(service.id, "1.0.0", None, SimpleNamespace(id=uuid4()))  # type: ignore[arg-type]
