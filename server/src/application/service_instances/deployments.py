"""Workload deployments: fan a version out across a service's environments in tier/rank order, one run per instance."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
import uuid
from uuid import UUID

from sqlalchemy import select

from application.environments.model import Environment
from application.services.schema import ServiceSpec, validate_image_tag
from application.services.service import ServiceService
from core.constants.model import ModelActions, ModelState, ModelStatus
from core.errors import EntityNotFound
from core.users.model import UserDTO

from .crud import ServiceInstanceCRUD
from .model import DeploymentStatus, ServiceDeployment, ServiceInstance

TIER_ORDER = {"dev": 0, "staging": 1, "prod": 2}
BUSY = (ModelStatus.QUEUED, ModelStatus.IN_PROGRESS, ModelStatus.APPROVAL_PENDING)
_BLOCKING = (DeploymentStatus.ERROR, DeploymentStatus.CANCELLED, DeploymentStatus.SUPERSEDED)


class InstanceRunner(Protocol):
    """What deployments need from ServiceInstanceService (kept structural to avoid an import cycle)."""

    crud: ServiceInstanceCRUD

    @property
    def services(self) -> ServiceService: ...

    async def queue_run(self, instance: ServiceInstance, requester: UserDTO, approval_required: bool) -> None: ...

    async def send(self, instance: ServiceInstance, action: str) -> ServiceInstance: ...


def rollout_key(tier: str, rank: int, name: str) -> tuple[int, int, str]:
    return TIER_ORDER.get(tier, 1), rank, name


@dataclass(frozen=True)
class DeploymentView:
    id: UUID
    batch_id: UUID
    position: int
    instance_id: UUID
    status: str
    environment_name: str = ""


@dataclass
class Dispatch:
    start: list[UUID] = field(default_factory=list)
    cancel: list[tuple[UUID, str]] = field(default_factory=list)


def plan_dispatch(deployments: list[DeploymentView], busy: set[UUID], unavailable: dict[UUID, str]) -> Dispatch:
    """Which waiting deployments start now and which can never run.

    A batch advances one environment at a time. A failed, cancelled or superseded environment stops the rest of its
    batch. An instance runs one thing at a time: busy instances (or ones already running a deployment) wait.
    """
    result = Dispatch()
    running = set(busy) | {d.instance_id for d in deployments if d.status == DeploymentStatus.ACTIVE}
    batches: dict[UUID, list[DeploymentView]] = defaultdict(list)
    for deployment in deployments:
        batches[deployment.batch_id].append(deployment)

    for batch in batches.values():
        # Set once an earlier environment of the batch did not succeed: the rest is cancelled.
        stopped: str | None = None
        for deployment in sorted(batch, key=lambda d: d.position):
            if deployment.status in _BLOCKING:
                stopped = stopped or f"Stopped because {deployment.environment_name} is {deployment.status}"
            elif deployment.status == DeploymentStatus.ACTIVE:
                break
            elif deployment.status == DeploymentStatus.WAITING:
                if stopped is not None:
                    result.cancel.append((deployment.id, stopped))
                elif deployment.instance_id in unavailable:
                    reason = unavailable[deployment.instance_id]
                    result.cancel.append((deployment.id, reason))
                    stopped = f"Stopped because {deployment.environment_name}: {reason}"
                else:
                    if deployment.instance_id not in running:
                        result.start.append(deployment.id)
                        running.add(deployment.instance_id)
                    break
    return result


class DeploymentService:
    def __init__(self, instance_service: InstanceRunner) -> None:
        self.instances: InstanceRunner = instance_service
        self.session = instance_service.crud.session

    async def _instances(self, service_id: UUID) -> list[tuple[ServiceInstance, Environment]]:
        rows = await self.session.execute(
            select(ServiceInstance, Environment)
            .join(Environment, Environment.id == ServiceInstance.environment_id)
            .where(ServiceInstance.service_id == service_id)
            .execution_options(populate_existing=True)
        )
        pairs = [(row[0], row[1]) for row in rows.unique().all()]
        return sorted(pairs, key=lambda p: rollout_key(p[1].tier, p[1].rank, p[1].name))

    async def request(
        self,
        service_id: UUID,
        version: str,
        environment_ids: list[UUID] | None,
        requester: UserDTO,
        source: str = "api",
        message: str | None = None,
    ) -> list[ServiceDeployment]:
        """Record a rollout of ``version`` and start its first environment."""
        version = validate_image_tag(version)
        service = await self.instances.services.crud.get_by_id(service_id)
        if service is None:
            raise EntityNotFound("Service not found")
        if ServiceSpec.model_validate(service.spec or {}).managed_workload is None:
            raise ValueError("The workload of this service is not managed by InfraKitchen; its own pipeline deploys it")

        targets = await self._instances(service.id)
        if environment_ids is not None:
            wanted = set(environment_ids)
            missing = wanted - {env.id for _, env in targets}
            if missing:
                raise ValueError(f"The service is not deployed to {len(missing)} of the requested environments")
            targets = [(i, e) for i, e in targets if e.id in wanted]
        if not targets:
            raise ValueError("The service is not deployed to any environment yet")
        for instance, environment in targets:
            if instance.spec_revision_applied is None or instance.state in (ModelState.DESTROY, ModelState.DESTROYED):
                raise ValueError(f"Deploy the service's infrastructure to {environment.name} first")

        waiting = await self.session.execute(
            select(ServiceDeployment).where(
                ServiceDeployment.service_instance_id.in_([i.id for i, _ in targets]),
                ServiceDeployment.status == DeploymentStatus.WAITING,
            )
        )
        now = datetime.now(UTC)
        for old in waiting.scalars():
            old.status = DeploymentStatus.SUPERSEDED
            old.message = f"Superseded by {version}"
            old.finished_at = now

        batch_id = uuid.uuid4()
        created = [
            ServiceDeployment(
                service_id=service.id,
                service_instance_id=instance.id,
                environment_id=environment.id,
                batch_id=batch_id,
                position=position,
                version=version,
                previous_version=instance.workload_version,
                status=DeploymentStatus.WAITING,
                source=source,
                message=message,
                created_by=requester.id,
            )
            for position, (instance, environment) in enumerate(targets)
        ]
        self.session.add_all(created)
        await self.session.flush()
        await self.dispatch(service.id, requester)
        for deployment in created:
            await self.session.refresh(deployment)
        return created

    async def dispatch(self, service_id: UUID, requester: UserDTO) -> None:
        pending = await self.session.execute(
            select(ServiceDeployment.batch_id).where(
                ServiceDeployment.service_id == service_id, ServiceDeployment.status == DeploymentStatus.WAITING
            )
        )
        batch_ids = set(pending.scalars())
        if not batch_ids:
            return
        rows = list(
            (
                await self.session.execute(
                    select(ServiceDeployment)
                    .where(ServiceDeployment.batch_id.in_(batch_ids))
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .unique()
        )
        active = await self.session.execute(
            select(ServiceDeployment.service_instance_id).where(
                ServiceDeployment.service_id == service_id, ServiceDeployment.status == DeploymentStatus.ACTIVE
            )
        )
        instances = {i.id: i for i, _ in await self._instances(service_id)}
        busy = {i.id for i in instances.values() if i.status in BUSY} | set(active.scalars())
        unavailable = {
            i.id: f"the service is {str(i.state).lower()}"
            for i in instances.values()
            if i.state in (ModelState.DESTROY, ModelState.DESTROYED)
        }
        plan = plan_dispatch(
            [
                DeploymentView(
                    id=d.id,
                    batch_id=d.batch_id,
                    position=d.position,
                    instance_id=d.service_instance_id,
                    status=d.status,
                    environment_name=d.environment.name if d.environment else "",
                )
                for d in rows
            ],
            busy,
            unavailable,
        )
        by_id = {d.id: d for d in rows}
        now = datetime.now(UTC)
        for deployment_id, reason in plan.cancel:
            by_id[deployment_id].status = DeploymentStatus.CANCELLED
            by_id[deployment_id].message = reason
            by_id[deployment_id].finished_at = now
        for deployment_id in plan.start:
            await self._start(by_id[deployment_id], requester)
        await self.session.flush()

    async def _start(self, deployment: ServiceDeployment, requester: UserDTO) -> None:
        instance = await self.instances.crud.get_for_update(deployment.service_instance_id)
        if instance is None:
            return
        environment = await self.session.get(Environment, instance.environment_id)
        deployment.status = DeploymentStatus.ACTIVE
        deployment.started_at = datetime.now(UTC)
        instance.workflow_id = None
        await self.instances.queue_run(instance, requester, bool(environment and environment.approval_required))
        await self.instances.send(instance, ModelActions.EXECUTE)

    async def active_for(self, instance_id: UUID) -> ServiceDeployment | None:
        result = await self.session.execute(
            select(ServiceDeployment)
            .where(
                ServiceDeployment.service_instance_id == instance_id,
                ServiceDeployment.status == DeploymentStatus.ACTIVE,
            )
            .execution_options(populate_existing=True)
        )
        return result.scalars().first()

    async def finish(self, instance: ServiceInstance, ok: bool, message: str | None, requester: UserDTO) -> None:
        """Close the instance's running deployment (if any) and let the next ones start."""
        deployment = await self.active_for(instance.id)
        if deployment is not None:
            deployment.status = DeploymentStatus.DONE if ok else DeploymentStatus.ERROR
            deployment.message = message
            deployment.finished_at = datetime.now(UTC)
            await self.session.flush()
        await self.dispatch(instance.service_id, requester)

    async def cancel_active(self, instance: ServiceInstance, reason: str, requester: UserDTO) -> None:
        deployment = await self.active_for(instance.id)
        if deployment is None:
            return
        deployment.status = DeploymentStatus.CANCELLED
        deployment.message = reason
        deployment.finished_at = datetime.now(UTC)
        await self.session.flush()
        await self.dispatch(instance.service_id, requester)

    async def _instance(self, service_id: UUID, environment_id: UUID) -> tuple[ServiceInstance, Environment]:
        for instance, environment in await self._instances(service_id):
            if environment.id == environment_id:
                return instance, environment
        raise EntityNotFound("The service is not deployed to this environment")

    async def rollback(self, service_id: UUID, environment_id: UUID, requester: UserDTO) -> list[ServiceDeployment]:
        """Deploy the last successful version before the current one."""
        instance, environment = await self._instance(service_id, environment_id)
        done = await self.session.execute(
            select(ServiceDeployment.version)
            .where(
                ServiceDeployment.service_instance_id == instance.id,
                ServiceDeployment.status == DeploymentStatus.DONE,
            )
            .order_by(ServiceDeployment.finished_at.desc())
        )
        previous = next((v for v in done.scalars() if v != instance.workload_version), None)
        if previous is None:
            raise ValueError(f"There is no earlier successful version in {environment.name} to roll back to")
        return await self.request(
            service_id,
            previous,
            [environment_id],
            requester,
            source="rollback",
            message=f"Rollback from {instance.workload_version}",
        )

    async def promote(self, service_id: UUID, environment_id: UUID, requester: UserDTO) -> list[ServiceDeployment]:
        """Deploy the version running in one environment to every environment of the next tier."""
        instance, environment = await self._instance(service_id, environment_id)
        if instance.workload_version is None:
            raise ValueError(f"Nothing is deployed in {environment.name} yet")
        current = TIER_ORDER.get(environment.tier, 1)
        later = [(TIER_ORDER.get(e.tier, 1), e) for _, e in await self._instances(service_id)]
        later = [(order, e) for order, e in later if order > current]
        if not later:
            raise ValueError(f"{environment.name} is already in the last tier")
        next_tier = min(order for order, _ in later)
        return await self.request(
            service_id,
            instance.workload_version,
            [e.id for order, e in later if order == next_tier],
            requester,
            source="promote",
            message=f"Promoted from {environment.name}",
        )

    async def history(
        self, service_id: UUID, environment_id: UUID | None = None, limit: int = 50
    ) -> list[ServiceDeployment]:
        statement = select(ServiceDeployment).where(ServiceDeployment.service_id == service_id)
        if environment_id is not None:
            statement = statement.where(ServiceDeployment.environment_id == environment_id)
        statement = statement.order_by(ServiceDeployment.created_at.desc(), ServiceDeployment.position).limit(limit)
        return list((await self.session.execute(statement)).scalars().unique())
