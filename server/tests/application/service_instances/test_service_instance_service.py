from unittest.mock import ANY, Mock
from uuid import uuid4

import pytest

from application.service_instances.model import ServiceInstanceResource, ServiceResourceRole
from application.service_instances.schema import ServiceInstanceCreate
from core.constants.model import ModelActions, ModelState, ModelStatus
from core.errors import DependencyError, EntityExistsError, EntityNotFound, EntityWrongState


def _scalars(*values):
    """Queue successive scalar_one_or_none() results for session.execute()."""
    results = []
    for value in values:
        result = Mock()
        result.scalar_one_or_none.return_value = value
        results.append(result)
    return results


def _link(role: ServiceResourceRole, alias: str) -> ServiceInstanceResource:
    return ServiceInstanceResource(id=uuid4(), resource_id=uuid4(), alias=alias, role=role)


class TestCreate:
    @pytest.mark.asyncio
    async def test_creates_ready_instance_without_provisioning(
        self,
        mock_service_instance_service,
        mock_service_instance_crud,
        mock_audit_log_handler,
        mock_event_sender,
        mocked_service_instance,
        mocked_user,
    ):
        mock_service_instance_crud.session.execute.side_effect = _scalars(uuid4(), ModelStatus.ENABLED)
        mock_service_instance_crud.count.return_value = 0
        mock_service_instance_crud.create.return_value = mocked_service_instance
        mock_service_instance_crud.get_by_id.return_value = mocked_service_instance

        body = ServiceInstanceCreate(service_id=uuid4(), environment_id=uuid4())
        await mock_service_instance_service.create_service_instance(body, mocked_user)

        created = mock_service_instance_crud.create.await_args.args[0]
        assert created["state"] == ModelState.PROVISION
        assert created["status"] == ModelStatus.READY
        assert created["created_by"] == mocked_user.id
        mock_audit_log_handler.create_log.assert_awaited_once_with(
            mocked_service_instance.id, mocked_user.id, ModelActions.CREATE
        )
        mock_event_sender.send_event.assert_awaited_once_with(ANY, ModelActions.CREATE)

    @pytest.mark.asyncio
    async def test_disabled_environment_is_rejected(
        self, mock_service_instance_service, mock_service_instance_crud, mocked_user
    ):
        mock_service_instance_crud.session.execute.side_effect = _scalars(uuid4(), ModelStatus.DISABLED)

        with pytest.raises(EntityWrongState, match="disabled"):
            await mock_service_instance_service.create_service_instance(
                ServiceInstanceCreate(service_id=uuid4(), environment_id=uuid4()), mocked_user
            )
        mock_service_instance_crud.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_service_is_rejected(
        self, mock_service_instance_service, mock_service_instance_crud, mocked_user
    ):
        mock_service_instance_crud.session.execute.side_effect = _scalars(None)

        with pytest.raises(EntityNotFound, match="Service"):
            await mock_service_instance_service.create_service_instance(
                ServiceInstanceCreate(service_id=uuid4(), environment_id=uuid4()), mocked_user
            )

    @pytest.mark.asyncio
    async def test_unknown_anchor_resource_is_rejected(
        self, mock_service_instance_service, mock_service_instance_crud, mocked_user
    ):
        mock_service_instance_crud.session.execute.side_effect = _scalars(uuid4(), ModelStatus.ENABLED, None)

        with pytest.raises(EntityNotFound, match="Anchor resource"):
            await mock_service_instance_service.create_service_instance(
                ServiceInstanceCreate(service_id=uuid4(), environment_id=uuid4(), anchor_resource_id=uuid4()),
                mocked_user,
            )

    @pytest.mark.asyncio
    async def test_second_deploy_to_same_environment_is_rejected(
        self, mock_service_instance_service, mock_service_instance_crud, mocked_user
    ):
        mock_service_instance_crud.session.execute.side_effect = _scalars(uuid4(), ModelStatus.ENABLED)
        mock_service_instance_crud.count.return_value = 1

        with pytest.raises(EntityExistsError):
            await mock_service_instance_service.create_service_instance(
                ServiceInstanceCreate(service_id=uuid4(), environment_id=uuid4()), mocked_user
            )
        mock_service_instance_crud.create.assert_not_awaited()


class TestDelete:
    @pytest.mark.asyncio
    async def test_instance_owning_resources_cannot_be_removed(
        self, mock_service_instance_service, mock_service_instance_crud, mocked_service_instance, mocked_user
    ):
        owned = _link(ServiceResourceRole.DEPENDENCY, "db")
        mocked_service_instance.resources = [owned, _link(ServiceResourceRole.REFERENCED, "kafka")]
        mock_service_instance_crud.get_by_id.return_value = mocked_service_instance

        with pytest.raises(DependencyError) as exc:
            await mock_service_instance_service.delete(str(mocked_service_instance.id), mocked_user)

        assert exc.value.metadata == [{"id": str(owned.resource_id), "name": "db", "entityName": "resource"}]
        mock_service_instance_crud.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_referenced_only_instance_can_be_removed(
        self, mock_service_instance_service, mock_service_instance_crud, mocked_service_instance, mocked_user
    ):
        mocked_service_instance.resources = [_link(ServiceResourceRole.REFERENCED, "kafka")]
        mock_service_instance_crud.get_by_id.return_value = mocked_service_instance

        await mock_service_instance_service.delete(str(mocked_service_instance.id), mocked_user)

        mock_service_instance_crud.delete.assert_awaited_once_with(mocked_service_instance)

    @pytest.mark.asyncio
    async def test_missing_instance(self, mock_service_instance_service, mock_service_instance_crud, mocked_user):
        mock_service_instance_crud.get_by_id.return_value = None

        with pytest.raises(EntityNotFound):
            await mock_service_instance_service.delete(str(uuid4()), mocked_user)
