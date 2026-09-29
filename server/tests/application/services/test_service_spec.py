from unittest.mock import Mock
from uuid import uuid4

import pytest

from application.services.compiler import Catalog, CatalogTemplate, EnvironmentTarget, PlacedResource, PlanAction
from application.services.schema import ServiceCreate, ServiceUpdate
from core.errors import EntityNotFound

LZ_TID = uuid4()


def _catalog(claimable: bool = True) -> Catalog:
    redis = CatalogTemplate(
        id=uuid4(),
        key="aws_redis",
        name="Redis",
        enabled=True,
        abstract=False,
        claimable=claimable,
        naming_convention="redis-{service_name}",
        parent_template_ids=(LZ_TID,),
    )
    return Catalog(templates_by_key={"aws_redis": redis}, latest_version_by_template={redis.id: uuid4()})


SPEC = {"claims": [{"alias": "cache", "template": "aws_redis", "variables": {"node_type": "cache.t4g.small"}}]}


class TestSpecOnSave:
    @pytest.mark.asyncio
    async def test_create_rejects_non_claimable_template(self, mock_service_service, mock_service_crud, mocked_user):
        mock_service_crud.session.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=uuid4()))
        mock_service_crud.load_catalog.return_value = _catalog(claimable=False)

        with pytest.raises(ValueError, match="not in the offering catalog"):
            await mock_service_service.create_service(
                ServiceCreate(name="checkout", project_id=uuid4(), spec=SPEC), mocked_user
            )
        mock_service_crud.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_stores_full_spec(self, mock_service_service, mock_service_crud, mocked_service, mocked_user):
        mock_service_crud.session.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=uuid4()))
        mock_service_crud.load_catalog.return_value = _catalog()
        mock_service_crud.create.return_value = mocked_service
        mock_service_crud.get_by_id.return_value = mocked_service

        await mock_service_service.create_service(
            ServiceCreate(name="checkout", project_id=uuid4(), spec=SPEC), mocked_user
        )

        body = mock_service_crud.create.await_args.args[0]
        assert body["spec"] == {
            "claims": [
                {
                    "alias": "cache",
                    "template": "aws_redis",
                    "source_code_version_id": None,
                    "variables": {"node_type": "cache.t4g.small"},
                    "parents": [],
                    "adopted": False,
                }
            ],
            "bindings": [],
        }

    @pytest.mark.asyncio
    async def test_create_without_spec_skips_catalog(
        self, mock_service_service, mock_service_crud, mocked_service, mocked_user
    ):
        mock_service_crud.session.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=uuid4()))
        mock_service_crud.create.return_value = mocked_service
        mock_service_crud.get_by_id.return_value = mocked_service

        await mock_service_service.create_service(ServiceCreate(name="checkout", project_id=uuid4()), mocked_user)

        mock_service_crud.load_catalog.assert_not_awaited()
        assert mock_service_crud.create.await_args.args[0]["spec"] == {"claims": [], "bindings": []}

    @pytest.mark.asyncio
    async def test_update_with_new_spec_is_a_change(
        self, mock_service_service, mock_service_crud, mocked_service, mocked_user
    ):
        mock_service_crud.get_by_id.return_value = mocked_service
        mock_service_crud.load_catalog.return_value = _catalog()

        await mock_service_service.update_service(str(mocked_service.id), ServiceUpdate(spec=SPEC), mocked_user)

        body = mock_service_crud.update.await_args.args[1]
        assert body["spec"]["claims"][0]["alias"] == "cache"

    @pytest.mark.asyncio
    async def test_update_with_identical_spec_is_not_a_change(
        self, mock_service_service, mock_service_crud, mocked_service, mocked_user
    ):
        mocked_service.spec = ServiceUpdate(spec=SPEC).spec.model_dump(mode="json")  # type: ignore[union-attr]
        mock_service_crud.get_by_id.return_value = mocked_service
        mock_service_crud.load_catalog.return_value = _catalog()

        with pytest.raises(ValueError, match="No changes"):
            await mock_service_service.update_service(str(mocked_service.id), ServiceUpdate(spec=SPEC), mocked_user)

    @pytest.mark.asyncio
    async def test_update_without_spec_leaves_it_alone(
        self, mock_service_service, mock_service_crud, mocked_service, mocked_user
    ):
        mock_service_crud.get_by_id.return_value = mocked_service

        await mock_service_service.update_service(str(mocked_service.id), ServiceUpdate(description="x"), mocked_user)

        assert "spec" not in mock_service_crud.update.await_args.args[1]
        mock_service_crud.load_catalog.assert_not_awaited()


class TestPlan:
    @pytest.mark.asyncio
    async def test_plan_compiles_against_environment(
        self, mock_service_service, mock_service_crud, mocked_service, mocked_user
    ):
        mocked_service.spec = SPEC
        mock_service_crud.get_by_id.return_value = mocked_service
        mock_service_crud.load_catalog.return_value = _catalog()
        env = EnvironmentTarget(
            id=uuid4(), name="dev", landing_zone=(PlacedResource(id=uuid4(), template_id=LZ_TID, name="eks"),)
        )
        mock_service_crud.load_environment_target.return_value = env

        plan = await mock_service_service.plan(mocked_service.id, env.id, mocked_user)

        assert plan.errors == []
        assert [(i.alias, i.action) for i in plan.items] == [("cache", PlanAction.CREATE)]
        mock_service_crud.load_instance.assert_awaited_once_with(mocked_service.id, env.id)

    @pytest.mark.asyncio
    async def test_plan_for_unknown_environment(
        self, mock_service_service, mock_service_crud, mocked_service, mocked_user
    ):
        mock_service_crud.get_by_id.return_value = mocked_service
        mock_service_crud.load_environment_target.return_value = None

        with pytest.raises(EntityNotFound, match="Environment"):
            await mock_service_service.plan(mocked_service.id, uuid4(), mocked_user)

    @pytest.mark.asyncio
    async def test_plan_for_spec_less_service_is_empty(
        self, mock_service_service, mock_service_crud, mocked_service, mocked_user
    ):
        mocked_service.spec = None
        mock_service_crud.get_by_id.return_value = mocked_service
        mock_service_crud.load_catalog.return_value = Catalog(templates_by_key={})
        mock_service_crud.load_environment_target.return_value = EnvironmentTarget(id=uuid4(), name="dev")

        plan = await mock_service_service.plan(mocked_service.id, uuid4(), mocked_user)

        assert plan.items == [] and plan.errors == []
