from datetime import datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from application.environments.model import Environment
from application.environments.service import EnvironmentService
from application.service_instances.model import ServiceInstance
from application.service_instances.service import ServiceInstanceService
from core.constants.model import ModelState, ModelStatus


def _mock_crud():
    crud = Mock()
    for method in ("get_by_id", "get_all", "count", "create", "update", "delete", "refresh"):
        setattr(crud, method, AsyncMock())
    crud.session = Mock()
    crud.session.execute = AsyncMock()
    return crud


@pytest.fixture
def mock_environment_crud():
    return _mock_crud()


@pytest.fixture
def mock_environment_service(
    mock_environment_crud,
    mock_permission_service,
    mock_revision_handler,
    mock_event_sender,
    mock_audit_log_handler,
):
    return EnvironmentService(
        crud=mock_environment_crud,
        permission_service=mock_permission_service,
        revision_handler=mock_revision_handler,
        event_sender=mock_event_sender,
        audit_log_handler=mock_audit_log_handler,
    )


@pytest.fixture
def mocked_environment(mocked_user):
    return Environment(
        id=uuid4(),
        name="app-staging-eu-central-1",
        display_name="App Staging EU",
        description="",
        tier="staging",
        rank=1,
        region="eu-central-1",
        account_id="123456789012",
        cluster_name="staging-eu-central-1-eks",
        approval_required=False,
        labels=[],
        status=ModelStatus.ENABLED,
        integration_ids=[],
        parent_resources=[],
        creator=mocked_user,
        created_by=mocked_user.id,
        revision_number=1,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@pytest.fixture
def mock_service_instance_crud():
    return _mock_crud()


@pytest.fixture
def mock_service_instance_service(mock_service_instance_crud, mock_event_sender, mock_audit_log_handler):
    return ServiceInstanceService(
        crud=mock_service_instance_crud,
        event_sender=mock_event_sender,
        audit_log_handler=mock_audit_log_handler,
    )


@pytest.fixture
def mocked_service_instance(mocked_user, mocked_service, mocked_environment):
    return ServiceInstance(
        id=uuid4(),
        service_id=mocked_service.id,
        service=mocked_service,
        environment_id=mocked_environment.id,
        environment=mocked_environment,
        state=ModelState.PROVISION,
        status=ModelStatus.READY,
        resources=[],
        creator=mocked_user,
        created_by=mocked_user.id,
        revision_number=1,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
