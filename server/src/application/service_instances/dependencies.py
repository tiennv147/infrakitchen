from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from application.services.dependencies import get_service_service
from core.audit_logs.handler import AuditLogHandler
from core.dependencies import get_db_session
from core.utils.event_sender import EventSender

from .crud import ServiceInstanceCRUD
from .service import ServiceInstanceService


def get_service_instance_service(
    session: AsyncSession = Depends(get_db_session),
) -> ServiceInstanceService:
    return ServiceInstanceService(
        crud=ServiceInstanceCRUD(session=session),
        event_sender=EventSender(entity_name="service_instance"),
        audit_log_handler=AuditLogHandler(session=session, entity_name="service_instance"),
        service_service=get_service_service(session=session),
    )
