from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from app.config import Settings, get_settings
from app.dependencies import get_knowledge_repository, get_operational_repository
from app.knowledge.repository import KnowledgeRepository
from app.observability.repository import OperationalRepository
from app.services.report_service import send_daily_report

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["report"])


@router.get("/daily-report")
def trigger_daily_report(
    knowledge_repo: KnowledgeRepository = Depends(get_knowledge_repository),
    operational_repo: OperationalRepository = Depends(get_operational_repository),
    settings: Settings = Depends(get_settings),
):
    if not settings.report_recipient:
        return {"sent": False, "reason": "REPORT_RECIPIENT not configured — set REPORT_RECIPIENT env var"}

    result = send_daily_report(knowledge_repo, operational_repo, settings)

    return {
        "status": "ok",
        "sent": result["sent"],
        "relationships_found_today": result["relationships_found"],
        "report_date": datetime.now(timezone.utc).date().isoformat(),
    }
