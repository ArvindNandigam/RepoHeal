from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.config import Settings
from app.knowledge.repository import KnowledgeRepository
from app.observability.repository import OperationalRepository
from app.services.mail_service import send_email

logger = logging.getLogger(__name__)


def _fmt(val: Any) -> str:
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M UTC")
    return str(val)


def build_report(knowledge_repo: KnowledgeRepository) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rels = knowledge_repo.get_today_relationships()

    lines: list[str] = []
    lines.append(f"Daily Deprecation Report — {today}")
    lines.append("=" * 50)
    lines.append(f"Total new/candidate relationships today: {len(rels)}")
    lines.append("")

    if rels:
        lines.append(f"{'Library':<20} {'From':<40} {'Relation':<30} {'To':<40} {'Status':<12} {'Conf':<6}")
        lines.append("-" * 148)
        for r in rels:
            lib = r.get("library", "?")[:18]
            frm = r.get("from", "?")[:38]
            rel = r.get("relation", "?")[:28]
            to = r.get("to", "?")[:38]
            status = r.get("status", "?")[:10]
            conf = r.get("confidence", 0)
            lines.append(f"{lib:<20} {frm:<40} {rel:<30} {to:<40} {status:<12} {conf:<6}")
        lines.append("")
    else:
        lines.append("No new relationships found today.")

    lines.append("")
    lines.append("--- End of Report ---")
    return "\n".join(lines)


def send_daily_report(
    knowledge_repo: KnowledgeRepository,
    operational_repo: OperationalRepository,
    settings: Settings,
) -> dict[str, Any]:
    if not settings.report_recipient:
        logger.info("REPORT_RECIPIENT not set — skipping daily report")
        return {"sent": False, "reason": "no_recipient_configured"}

    report = build_report(knowledge_repo)

    subject = f"Daily Deprecation Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"

    ok = send_email(
        host=settings.smtp_host,
        port=settings.smtp_port,
        user=settings.smtp_user,
        password=settings.smtp_password,
        from_addr=settings.smtp_from,
        to_addr=settings.report_recipient,
        subject=subject,
        body=report,
    )

    if ok:
        cleared = knowledge_repo.clear_evidence_cache()
        logger.info("Daily report sent and evidence cache cleared (%d docs)", cleared)

    operational_repo.log_audit_event(
        event="daily_report",
        request_id="scheduler",
        details={"sent": ok, "relationships_found": len(knowledge_repo.get_today_relationships())},
    )

    return {"sent": ok, "relationships_found": len(knowledge_repo.get_today_relationships())}
