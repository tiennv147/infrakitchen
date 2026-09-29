"""Reconciler: drives a service instance to its spec by compiling it into workflows and following them to completion."""

from sqlalchemy.ext.asyncio import AsyncSession

from application.environments.model import Environment
from application.services.compiler import PlanAction
from application.services.schema import ServiceSpec
from application.services.service import ServiceService
from application.workflows.functions import topological_levels
from application.workflows.model import Workflow
from application.workflows.schema import WorkflowCreate, WorkflowStepCreate
from application.workflows.service import WorkflowService
from core.base_models import PatchBodyModel
from core.constants.model import ModelActions, ModelState, ModelStatus, WorkflowAction
from core.custom_entity_log_controller import EntityLogger
from core.errors import CannotProceed
from core.users.model import UserDTO
from core.utils.event_sender import EventSender

from .binding_delivery import BindingDelivery
from .crud import ServiceInstanceCRUD
from .model import ServiceInstance, ServiceInstanceResource, ServiceResourceRole
from .schema import ServiceInstanceResponse

RUNNING = (ModelStatus.PENDING, ModelStatus.QUEUED, ModelStatus.IN_PROGRESS)


class ServiceInstanceTask:
    def __init__(
        self,
        session: AsyncSession,
        crud: ServiceInstanceCRUD,
        service_service: ServiceService,
        workflow_service: WorkflowService,
        instance: ServiceInstance,
        logger: EntityLogger,
        user: UserDTO,
        event_sender: EventSender,
        action: ModelActions,
        binding_delivery: BindingDelivery | None = None,
    ) -> None:
        self.session: AsyncSession = session
        self.crud: ServiceInstanceCRUD = crud
        self.service_service: ServiceService = service_service
        self.workflow_service: WorkflowService = workflow_service
        self.instance: ServiceInstance = instance
        self.logger: EntityLogger = logger
        self.user: UserDTO = user
        self.event_sender: EventSender = event_sender
        self.action: ModelActions = action
        self.binding_delivery: BindingDelivery | None = binding_delivery

    async def start_pipeline(self) -> None:
        match self.action:
            case ModelActions.EXECUTE:
                if self.instance.state == ModelState.DESTROY:
                    await self.destroy_entity()
                else:
                    await self.execute_entity()
            case _:
                raise CannotProceed(f"Unknown action: {self.action}")

    async def make_failed(self) -> None:
        await self.change_entity_status(status=ModelStatus.ERROR)

    async def change_entity_status(self, status: ModelStatus | None = None, state: ModelState | None = None) -> None:
        if status is not None:
            self.instance.status = status
        if state is not None:
            self.instance.state = state
        await self.session.commit()
        await self.crud.refresh(self.instance)
        await self.event_sender.send_event(ServiceInstanceResponse.model_validate(self.instance), ModelActions.EXECUTE)
        await self.logger.save_log()

    async def _current_workflow(self) -> Workflow | None:
        if self.instance.workflow_id is None:
            return None
        return await self.workflow_service.crud.get_by_id(self.instance.workflow_id)

    async def _start_workflow(self, workflow: WorkflowCreate) -> None:
        workflow.parent_entity_name = "service_instance"
        workflow.parent_entity_id = self.instance.id
        created = await self.workflow_service.create(workflow.model_dump(mode="json"), requester=self.user)
        self.instance.workflow_id = created.id
        await self.workflow_service.patch_action(
            created.id, PatchBodyModel(action=ModelActions.EXECUTE), requester=self.user
        )
        self.logger.info(f"Started {workflow.action} workflow {created.id} with {len(workflow.steps)} steps")
        await self.change_entity_status(status=ModelStatus.IN_PROGRESS)

    async def _follow(self, workflow: Workflow) -> bool:
        """Handle a running or failed workflow. Returns True when the caller should continue (workflow DONE)."""
        if workflow.status in RUNNING:
            self.logger.debug(f"Workflow {workflow.id} is still {workflow.status}")
            return False
        await self._sync_links(workflow)
        if workflow.status == ModelStatus.ERROR:
            if self.instance.status == ModelStatus.QUEUED:
                self.logger.info(f"Retrying workflow {workflow.id}")
                await self.workflow_service.patch_action(
                    workflow.id, PatchBodyModel(action=ModelActions.EXECUTE), requester=self.user
                )
                await self.change_entity_status(status=ModelStatus.IN_PROGRESS)
            else:
                self.logger.error(f"Workflow {workflow.id} failed: {workflow.error_message or 'see workflow steps'}")
                await self.change_entity_status(status=ModelStatus.ERROR)
            return False
        return True

    async def _sync_links(self, workflow: Workflow) -> None:
        """Record resources a create workflow provisioned so later runs treat them as owned."""
        if workflow.action != WorkflowAction.CREATE:
            return
        linked = {link.alias for link in self.instance.resources}
        new = [
            (step.step_key, step.resource_id, ServiceResourceRole.DEPENDENCY)
            for step in workflow.steps
            if step.step_key and step.resource_id and step.step_key not in linked
        ]
        if new:
            await self.crud.add_links(self.instance.id, [(a, r, str(role)) for a, r, role in new])
            await self.crud.refresh(self.instance)
            self.logger.info(f"Linked new resources: {', '.join(a for a, _, _ in new)}")

    def _owned(self) -> list[ServiceInstanceResource]:
        return [link for link in self.instance.resources if link.role != ServiceResourceRole.REFERENCED]

    def _destroy_workflow(self, links: list[ServiceInstanceResource]) -> WorkflowCreate:
        """Dependents are destroyed before the resources they depend on."""
        ids = {link.resource_id for link in links}
        edges = [
            (link.resource_id, parent.id) for link in links for parent in link.resource.parents if parent.id in ids
        ]
        levels = dict(topological_levels([link.resource_id for link in links], edges))
        return WorkflowCreate(
            action=WorkflowAction.DESTROY,
            created_by=self.user.id,
            steps=[
                WorkflowStepCreate(
                    template_id=link.resource.template_id,
                    position=levels[link.resource_id],
                    resource_id=link.resource_id,
                    step_key=link.alias,
                )
                for link in links
            ],
        )

    async def _unlink_destroyed(self, keep_referenced: bool = True) -> None:
        stale = [
            link.id
            for link in self.instance.resources
            if link.resource.state == ModelState.DESTROYED
            and not (keep_referenced and link.role == ServiceResourceRole.REFERENCED)
        ]
        await self.crud.remove_links(stale)
        await self.crud.refresh(self.instance)

    async def execute_entity(self) -> None:
        workflow = await self._current_workflow()
        if workflow is None:
            await self._start_reconcile()
            return
        if not await self._follow(workflow):
            return
        if workflow.action == WorkflowAction.CREATE:
            await self._remove_unclaimed()
        else:
            await self._finish_reconcile()

    async def _start_reconcile(self) -> None:
        compiled = await self.service_service.compile(self.instance.service_id, self.instance.environment_id, self.user)
        if compiled.plan.errors or compiled.workflow is None:
            for error in compiled.plan.errors:
                self.logger.error(error)
            await self.change_entity_status(status=ModelStatus.ERROR)
            return

        service = await self.service_service.crud.get_by_id(self.instance.service_id)
        if service is None:
            raise CannotProceed(f"Service {self.instance.service_id} not found")
        self.instance.target_spec_revision = service.spec_revision
        plan = compiled.plan
        self.logger.info(
            f"Reconciling spec revision {service.spec_revision}: "
            f"{plan.count(PlanAction.CREATE)} to create, {plan.count(PlanAction.UPDATE)} to update, "
            f"{plan.count(PlanAction.NO_OP)} unchanged, {plan.count(PlanAction.DESTROY)} to destroy"
        )

        if any(step.status != ModelStatus.DONE for step in compiled.workflow.steps):
            await self._start_workflow(compiled.workflow)
            return
        await self._remove_unclaimed()

    async def _remove_unclaimed(self) -> None:
        service = await self.service_service.crud.get_by_id(self.instance.service_id)
        claimed = {
            claim.alias for claim in ServiceSpec.model_validate((service.spec if service else None) or {}).claims
        }
        removed = [
            link for link in self._owned() if link.alias not in claimed and link.resource.state != ModelState.DESTROYED
        ]
        if removed:
            self.logger.info(f"Destroying resources no longer claimed: {', '.join(link.alias for link in removed)}")
            await self._start_workflow(self._destroy_workflow(removed))
            return
        await self._finish_reconcile()

    async def _finish_reconcile(self) -> None:
        await self._unlink_destroyed()
        if not await self._deliver_bindings(remove=False):
            return
        self.instance.spec_revision_applied = self.instance.target_spec_revision
        self.logger.info(f"Service is at spec revision {self.instance.spec_revision_applied}")
        await self.change_entity_status(status=ModelStatus.DONE, state=ModelState.PROVISIONED)

    async def _deliver_bindings(self, remove: bool) -> bool:
        """Write (or remove) the instance's bindings. Returns False when the instance was failed instead."""
        if self.binding_delivery is None:
            return True
        service = await self.service_service.crud.get_by_id(self.instance.service_id)
        environment = await self.session.get(Environment, self.instance.environment_id)
        if service is None or environment is None:
            raise CannotProceed("Service or environment not found for bindings")
        try:
            if remove:
                await self.binding_delivery.remove(self.instance, service, environment)
                self.instance.binding_state = None
                self.logger.info("Removed the bindings this service wrote")
            else:
                state = await self.binding_delivery.apply(self.instance, service, environment)
                self.instance.binding_state = state
                if state:
                    self.logger.info(f"Wrote {len(state['keys'])} runtime bindings to {state['sink']} {state['path']}")
        except Exception as exc:  # noqa: BLE001 - any sink failure fails the run with a readable reason
            self.logger.error(f"Bindings failed: {exc}")
            await self.change_entity_status(status=ModelStatus.ERROR)
            return False
        return True

    async def destroy_entity(self) -> None:
        workflow = await self._current_workflow()
        if workflow is None:
            owned = [link for link in self._owned() if link.resource.state != ModelState.DESTROYED]
            if owned:
                self.logger.info(f"Destroying {len(owned)} owned resources; referenced resources are left untouched")
                await self._start_workflow(self._destroy_workflow(owned))
                return
        elif not await self._follow(workflow):
            return

        await self._unlink_destroyed()
        if not await self._deliver_bindings(remove=True):
            return
        self.instance.spec_revision_applied = None
        self.instance.target_spec_revision = None
        self.logger.info("Service is destroyed in this environment")
        await self.change_entity_status(status=ModelStatus.DONE, state=ModelState.DESTROYED)
