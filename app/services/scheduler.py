from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.knowledge.repository import KnowledgeRepository
from app.observability.repository import OperationalRepository
from app.services.report_service import send_daily_report

logger = logging.getLogger(__name__)


def run_daily_report_scheduler(
    knowledge_repo: KnowledgeRepository,
    operational_repo: OperationalRepository,
    settings: Settings,
) -> None:
    if not settings.report_recipient:
        logger.info("REPORT_RECIPIENT not set — daily report scheduler disabled")
        return

    logger.info(
        "Daily report scheduler started — will send at %02d:00 UTC daily to %s",
        settings.report_hour, settings.report_recipient,
    )

    while True:
        now = datetime.now(timezone.utc)
        target = now.replace(
            hour=settings.report_hour, minute=0, second=0, microsecond=0
        )
        if now >= target:
            target += timedelta(days=1)

        sleep_seconds = (target - now).total_seconds()
        logger.debug("Next report in %.1f hours", sleep_seconds / 3600)
        time.sleep(sleep_seconds)

        try:
            result = send_daily_report(knowledge_repo, operational_repo, settings)
            logger.info("Daily report sent: %s", result)
        except Exception as e:
            logger.error("Daily report failed: %s", e)
