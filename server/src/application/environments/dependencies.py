from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit_logs.handler import AuditLogHandler
from core.dependencies import get_db_session
from core.permissions.dependencies import get_permission_service
from core.revisions.handler import RevisionHandler
from core.utils.event_sender import EventSender

from .crud import EnvironmentCRUD
from .service import EnvironmentService


def get_environment_service(
    session: AsyncSession = Depends(get_db_session),
) -> EnvironmentService:
    return EnvironmentService(
        crud=EnvironmentCRUD(session=session),
        permission_service=get_permission_service(session=session),
        revision_handler=RevisionHandler(session=session, entity_name="environment"),
        event_sender=EventSender(entity_name="environment"),
        audit_log_handler=AuditLogHandler(session=session, entity_name="environment"),
    )
