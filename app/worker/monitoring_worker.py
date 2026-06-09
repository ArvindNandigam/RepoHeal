import uuid
from datetime import datetime, timezone
from typing import Dict, Any

from app.db.database import get_mongo_db
from app.models.monitoring_models import (
    Alert, AlertCategory, AlertSeverity, WatchlistEntry,
    HealthScoreSnapshot, RepositoryRiskIndex
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def record_health_snapshot(
    repository: str,
    analysis_id: str,
    health_report: Dict[str, Any]
) -> None:
    """Persist a health score snapshot after each analysis completion."""
    db = get_mongo_db()

    summary = health_report.get("executive_summary", {})
    inventory = health_report.get("dependency_inventory", [])
    risks = health_report.get("risk_assessment", [])

    fresh_count = sum(1 for d in inventory if d.get("status") == "up_to_date")
    total_deps = len(inventory)
    freshness = (fresh_count / max(total_deps, 1)) * 100.0

    security_count = sum(
        1 for r in risks
        if r.get("factors", {}).get("breaking_severity") in ("high", "critical")
    )

    snapshot = HealthScoreSnapshot(
        repository=repository,
        analysis_id=analysis_id,
        health_score=health_report.get("overall_health_score", 0),
        risk_level=health_report.get("overall_risk_level", "unknown"),
        critical_findings=summary.get("critical_findings_count", 0),
        deprecated_count=summary.get("deprecated_count", 0),
        breaking_count=summary.get("breaking_count", 0),
        dependency_count=total_deps,
        dependency_freshness=freshness,
        security_count=security_count,
        recorded_at=datetime.now(timezone.utc).isoformat()
    )

    db.health_scores.insert_one(snapshot.model_dump(mode="json"))

    # Update watchlist entries from inventory
    for dep in inventory:
        if dep.get("status") in ("outdated", "critical"):
            risk = "critical" if dep.get("status") == "critical" else "high"
            db.dependency_watchlist.update_one(
                {"repository": repository, "package_name": dep.get("name")},
                {"$set": WatchlistEntry(
                    repository=repository,
                    package_name=dep.get("name", "unknown"),
                    installed_version=dep.get("installed_version", "unknown"),
                    latest_version=dep.get("latest_version", "unknown"),
                    risk_level=risk,
                    monitored_since=datetime.now(timezone.utc).isoformat(),
                    last_checked=datetime.now(timezone.utc).isoformat()
                ).model_dump(mode="json")},
                upsert=True
            )

    logger.info(f"Health snapshot recorded for {repository}")


def generate_alerts_from_report(
    repository: str,
    health_report: Dict[str, Any],
    previous_score: int | None = None
) -> int:
    """Create alerts from a health report, respecting snooze/ignore rules."""
    db = get_mongo_db()
    rules = list(db.alert_rules.find({"repository": repository}))
    count = 0

    current_score = health_report.get("overall_health_score", 0)

    # Health degradation alert
    if previous_score is not None and current_score < previous_score - 10:
        _create_alert_if_allowed(db, repository, rules, Alert(
            id=str(uuid.uuid4()),
            repository=repository,
            category=AlertCategory.HEALTH_DEGRADATION,
            severity=AlertSeverity.HIGH,
            title="Repository health score dropped",
            description=f"Health score decreased from {previous_score} to {current_score}",
            created_at=datetime.now(timezone.utc).isoformat()
        ))
        count += 1

    # Breaking changes alerts
    for assessment in health_report.get("breaking_changes", []):
        _create_alert_if_allowed(db, repository, rules, Alert(
            id=str(uuid.uuid4()),
            repository=repository,
            category=AlertCategory.BREAKING,
            severity=AlertSeverity.HIGH,
            title=f"Breaking: {assessment.get('symbol', 'unknown')}",
            description=f"{assessment.get('symbol')} in {assessment.get('library')} will break",
            package_name=assessment.get("library"),
            symbol=assessment.get("symbol"),
            affected_files=assessment.get("files_using", []),
            confidence=assessment.get("confidence"),
            created_at=datetime.now(timezone.utc).isoformat()
        ))
        count += 1

    # Deprecation alerts
    for assessment in health_report.get("deprecated_apis", []):
        _create_alert_if_allowed(db, repository, rules, Alert(
            id=str(uuid.uuid4()),
            repository=repository,
            category=AlertCategory.DEPRECATION,
            severity=AlertSeverity.MEDIUM,
            title=f"Deprecated: {assessment.get('symbol', 'unknown')}",
            description=f"{assessment.get('symbol')} in {assessment.get('library')} is deprecated",
            package_name=assessment.get("library"),
            symbol=assessment.get("symbol"),
            affected_files=assessment.get("files_using", []),
            confidence=assessment.get("confidence"),
            created_at=datetime.now(timezone.utc).isoformat()
        ))
        count += 1

    # Security risk alerts
    for risk in health_report.get("risk_assessment", []):
        factors = risk.get("factors", {})
        if factors.get("breaking_severity") == "high":
            _create_alert_if_allowed(db, repository, rules, Alert(
                id=str(uuid.uuid4()),
                repository=repository,
                category=AlertCategory.SECURITY,
                severity=AlertSeverity.HIGH,
                title=f"High risk: {risk.get('symbol', 'unknown')}",
                description=(
                    f"Risk score {risk.get('risk_score')}/100, "
                    f"{factors.get('affected_file_count')} files affected"
                ),
                symbol=risk.get("symbol"),
                affected_files=[],
                confidence=risk.get("factors", {}).get("replacement_confidence"),
                created_at=datetime.now(timezone.utc).isoformat()
            ))
            count += 1

    return count


def _create_alert_if_allowed(
    db, repository: str, rules: list, alert: Alert
) -> None:
    """Check rules before inserting alert (snooze/ignore dedup)."""
    now = datetime.now(timezone.utc).isoformat()

    for rule in rules:
        if rule.get("ignored"):
            package_match = (
                not rule.get("package_name")
                or rule["package_name"] == alert.package_name
            )
            category_match = (
                not rule.get("category")
                or rule["category"] == alert.category.value
            )
            if package_match and category_match:
                return

        snoozed_until = rule.get("snoozed_until")
        if snoozed_until and snoozed_until > now:
            package_match = (
                not rule.get("package_name")
                or rule["package_name"] == alert.package_name
            )
            if package_match:
                return

    existing = db.alerts.find_one({
        "repository": repository,
        "category": alert.category.value,
        "symbol": alert.symbol,
        "dismissed": False
    })
    if existing:
        return

    db.alerts.insert_one(alert.model_dump(mode="json"))


def generate_weekly_digest(repository: str) -> Dict[str, Any]:
    """Aggregate weekly alert and health data for digest report."""
    db = get_mongo_db()
    now = datetime.now(timezone.utc)

    scores = list(db.health_scores.find(
        {"repository": repository},
        {"_id": 0}
    ).sort("recorded_at", -1).limit(2))
    health_trend = None
    if len(scores) >= 2:
        health_trend = scores[0].get("health_score", 0) - scores[1].get("health_score", 0)

    watchlist = list(db.dependency_watchlist.find(
        {"repository": repository},
        {"_id": 0}
    ))

    from datetime import timedelta
    week_ago = (now - timedelta(days=7)).isoformat()
    new_alerts = db.alerts.count_documents({
        "repository": repository,
        "created_at": {"$gte": week_ago}
    })
    dep_updates = [
        {
            "package": e.get("package_name"),
            "installed": e.get("installed_version"),
            "latest": e.get("latest_version"),
            "risk": e.get("risk_level")
        }
        for e in watchlist if e.get("risk_level") in ("high", "critical")
    ]

    return {
        "repository": repository,
        "generated_at": now.isoformat(),
        "period_start": week_ago,
        "period_end": now.isoformat(),
        "new_alerts": new_alerts,
        "health_trend": health_trend,
        "dependency_updates": dep_updates,
        "recommendations": _generate_recommendations(db, repository)
    }


def _generate_recommendations(db, repository: str) -> list:
    """Generate natural-language recommendations from current state."""
    recs = []
    critical_alerts = db.alerts.count_documents({
        "repository": repository,
        "severity": "critical",
        "dismissed": False
    })
    if critical_alerts:
        recs.append(f"Address {critical_alerts} critical alert(s) requiring immediate attention")

    outdated = db.dependency_watchlist.count_documents({
        "repository": repository,
        "risk_level": {"$in": ["high", "critical"]}
    })
    if outdated:
        recs.append(f"Review {outdated} outdated high-risk dependencies")

    last_snapshot = db.health_scores.find_one(
        {"repository": repository},
        sort=[("recorded_at", -1)]
    )
    if last_snapshot and last_snapshot.get("health_score", 0) < 60:
        recs.append("Repository health score is below 60 — consider a maintenance sprint")

    return recs
