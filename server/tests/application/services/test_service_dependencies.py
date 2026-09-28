from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from application.services.crud import ServiceCRUD
from application.services.model import Service
from application.services.schema import ServiceUpdate
from core.errors import DependencyError


def _load_depends_on(service, deps):
    """Simulate session.refresh(service, ["depends_on"]) loading the current links."""

    async def refresh(obj, attrs=None):
        if attrs == ["depends_on"]:
            obj.depends_on = deps

    return refresh


class TestDependsOnUpdate:
    @pytest.mark.asyncio
    async def test_clearing_existing_dependencies_is_a_change(
        self, mock_service_service, mock_service_crud, mocked_service, mocked_user
    ):
        # Regression: without loading current links first, clearing them looked like a no-op.
        mock_service_crud.get_by_id.return_value = mocked_service
        mock_service_crud.session.refresh = AsyncMock(
            side_effect=_load_depends_on(mocked_service, [Service(id=uuid4())])
        )

        await mock_service_service.update_service(str(mocked_service.id), ServiceUpdate(depends_on=[]), mocked_user)

        mock_service_crud.update.assert_awaited_once_with(mocked_service, {"depends_on": []})

    @pytest.mark.asyncio
    async def test_same_dependencies_are_not_a_change(
        self, mock_service_service, mock_service_crud, mocked_service, mocked_user
    ):
        dep = Service(id=uuid4())
        mock_service_crud.get_by_id.return_value = mocked_service
        mock_service_crud.session.refresh = AsyncMock(side_effect=_load_depends_on(mocked_service, [dep]))

        with pytest.raises(ValueError, match="No changes"):
            await mock_service_service.update_service(
                str(mocked_service.id), ServiceUpdate(depends_on=[dep.id]), mocked_user
            )
        mock_service_crud.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_other_fields_do_not_touch_dependencies(
        self, mock_service_service, mock_service_crud, mocked_service, mocked_user
    ):
        mock_service_crud.get_by_id.return_value = mocked_service
        mock_service_crud.session.refresh = AsyncMock()

        await mock_service_service.update_service(str(mocked_service.id), ServiceUpdate(description="new"), mocked_user)

        mock_service_crud.update.assert_awaited_once_with(mocked_service, {"description": "new"})


class TestResolveServices:
    @pytest.mark.asyncio
    async def test_self_dependency_is_rejected(self):
        crud = ServiceCRUD(session=Mock())
        service_id = uuid4()

        with pytest.raises(ValueError, match="itself"):
            await crud._resolve_services([service_id], self_id=service_id)

    @pytest.mark.asyncio
    async def test_unknown_dependency_is_rejected(self):
        session = Mock()
        result = Mock()
        result.scalars.return_value.unique.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result)

        with pytest.raises(ValueError, match="not found"):
            await ServiceCRUD(session=session)._resolve_services([uuid4()])


class TestDeleteDeployedService:
    @pytest.mark.asyncio
    async def test_service_deployed_to_an_environment_cannot_be_deleted(
        self, mock_service_service, mock_service_crud, mocked_service, mocked_user
    ):
        mock_service_crud.get_by_id.return_value = mocked_service
        env_id = uuid4()
        rows = Mock()
        rows.all.return_value = [(env_id, "app-dev")]
        mock_service_crud.session.execute.return_value = rows

        with pytest.raises(DependencyError) as exc:
            await mock_service_service.delete(str(mocked_service.id), mocked_user)

        assert exc.value.metadata == [{"id": str(env_id), "name": "app-dev", "entityName": "environment"}]
        mock_service_crud.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_undeployed_service_is_deleted_as_before(
        self, mock_service_service, mock_service_crud, mocked_service, mocked_user
    ):
        mock_service_crud.get_by_id.return_value = mocked_service
        rows = Mock()
        rows.all.return_value = []
        mock_service_crud.session.execute.return_value = rows

        await mock_service_service.delete(str(mocked_service.id), mocked_user)

        mock_service_crud.delete.assert_awaited_once_with(mocked_service)
