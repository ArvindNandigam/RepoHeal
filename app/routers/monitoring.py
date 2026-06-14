from datetime import datetime, timezone, timedelta
from typing import List, Optional
from pathlib import Path
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from app.auth.jwt_manager import verify_session_token
from app.auth.authorization import verify_repository_access
from app.routers.dependencies import get_session_data, ensure_repoheal_installed
from app.db.database import get_mongo_db
from app.models.monitoring_models import (
    HealthScoreSnapshot, WatchlistEntry, Alert, AlertRule,
    MonitorSchedule, RepositoryRiskIndex, DigestReport,
    AlertCategory, AlertSeverity
)
from app.utils.logger import get_logger
from app.utils.rate_limit import limiter

logger = get_logger(__name__)

router = APIRouter(prefix="/monitor", tags=["monitoring"])


# --- Health Score History ---

@router.get("/health-history/{repo_owner}/{repo_name}")
async def get_health_history(
    repo_owner: str,
    repo_name: str,
    limit: int = Query(30, le=365),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )
    repo_id = f"{repo_owner}/{repo_name}"
    db = get_mongo_db()
    docs = list(db.health_scores.find(
        {"repository": repo_id},
        {"_id": 0}
    ).sort("recorded_at", -1).limit(limit))
    return {"repository": repo_id, "snapshots": docs}


# --- Dependency Watchlist ---

@router.get("/watchlist/{repo_owner}/{repo_name}")
async def list_watchlist(
    repo_owner: str,
    repo_name: str,
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )
    repo_id = f"{repo_owner}/{repo_name}"
    db = get_mongo_db()
    docs = list(db.dependency_watchlist.find(
        {"repository": repo_id},
        {"_id": 0}
    ).sort("risk_level", -1))
    return {"repository": repo_id, "entries": docs}


@router.post("/watchlist/{repo_owner}/{repo_name}")
async def add_watchlist_entry(
    repo_owner: str,
    repo_name: str,
    entry: WatchlistEntry,
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )
    repo_id = f"{repo_owner}/{repo_name}"
    entry.repository = repo_id
    db = get_mongo_db()
    db.dependency_watchlist.update_one(
        {"repository": repo_id, "package_name": entry.package_name},
        {"$set": entry.model_dump(mode="json")},
        upsert=True
    )
    return {"status": "added", "package": entry.package_name}


@router.delete("/watchlist/{repo_owner}/{repo_name}/{package}")
async def remove_watchlist_entry(
    repo_owner: str,
    repo_name: str,
    package: str,
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )
    repo_id = f"{repo_owner}/{repo_name}"
    db = get_mongo_db()
    db.dependency_watchlist.delete_one(
        {"repository": repo_id, "package_name": package}
    )
    return {"status": "removed", "package": package}


# --- Alerts ---

@router.get("/alerts/{repo_owner}/{repo_name}")
async def list_alerts(
    repo_owner: str,
    repo_name: str,
    category: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    active_only: bool = Query(True),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )
    repo_id = f"{repo_owner}/{repo_name}"
    db = get_mongo_db()
    filt = {"repository": repo_id}
    if active_only:
        filt["dismissed"] = False
    if category:
        filt["category"] = category
    if severity:
        filt["severity"] = severity
    docs = list(db.alerts.find(filt, {"_id": 0}).sort("created_at", -1).limit(100))
    return {"repository": repo_id, "alerts": docs}


@router.post("/alerts/{alert_id}/dismiss")
async def dismiss_alert(
    alert_id: str,
    user=Depends(verify_session_token)
):
    db = get_mongo_db()
    db.alerts.update_one({"id": alert_id}, {"$set": {"dismissed": True}})
    return {"status": "dismissed"}


@router.post("/alerts/{alert_id}/snooze")
async def snooze_alert(
    alert_id: str,
    snooze_until: str,
    user=Depends(verify_session_token)
):
    db = get_mongo_db()
    db.alerts.update_one({"id": alert_id}, {"$set": {"snoozed_until": snooze_until}})
    return {"status": "snoozed", "until": snooze_until}


# --- Alert Rules (Ignore/Snooze) ---

@router.get("/rules/{repo_owner}/{repo_name}")
async def list_alert_rules(
    repo_owner: str,
    repo_name: str,
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )
    repo_id = f"{repo_owner}/{repo_name}"
    db = get_mongo_db()
    docs = list(db.alert_rules.find({"repository": repo_id}, {"_id": 0}))
    return {"repository": repo_id, "rules": docs}


@router.post("/rules/{repo_owner}/{repo_name}")
async def create_alert_rule(
    repo_owner: str,
    repo_name: str,
    rule: AlertRule,
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )
    repo_id = f"{repo_owner}/{repo_name}"
    rule.repository = repo_id
    rule.created_at = datetime.now(timezone.utc).isoformat()
    db = get_mongo_db()
    db.alert_rules.insert_one(rule.model_dump(mode="json"))
    return {"status": "created"}


@router.delete("/rules/{rule_id}")
async def delete_alert_rule(
    rule_id: str,
    user=Depends(verify_session_token)
):
    from bson.objectid import ObjectId
    db = get_mongo_db()
    db.alert_rules.delete_one({"_id": ObjectId(rule_id)})
    return {"status": "deleted"}


# --- Monitoring Schedule ---

@router.get("/schedule/{repo_owner}/{repo_name}")
async def get_schedule(
    repo_owner: str,
    repo_name: str,
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )
    repo_id = f"{repo_owner}/{repo_name}"
    db = get_mongo_db()
    doc = db.monitoring_config.find_one({"repository": repo_id}, {"_id": 0})
    if not doc:
        now = datetime.now(timezone.utc)
        doc = {
            "repository": repo_id,
            "frequency": "monthly",
            "branches": ["main"],
            "watch_dependencies": True,
            "auto_remediate": False,
            "notify_on": [c.value for c in AlertCategory],
            "digest_enabled": True,
            "next_run": (now + timedelta(days=30)).isoformat(),
            "updated_at": now.isoformat()
        }
    return doc


@router.post("/schedule/{repo_owner}/{repo_name}")
async def update_schedule(
    repo_owner: str,
    repo_name: str,
    schedule: MonitorSchedule,
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )
    repo_id = f"{repo_owner}/{repo_name}"
    schedule.repository = repo_id
    now = datetime.now(timezone.utc)
    schedule.updated_at = now.isoformat()
    # Preserve last_run from DB if incoming request doesn't include it
    db = get_mongo_db()
    existing = db.monitoring_config.find_one({"repository": repo_id}, {"_id": 0, "last_run": 1})
    if schedule.last_run is None and existing and existing.get("last_run"):
        schedule.last_run = existing["last_run"]
    # Compute next_run based on last_run if available, otherwise now
    from app.worker.scheduler import compute_next_run
    if schedule.frequency == "manual":
        schedule.next_run = None
    else:
        base = datetime.fromisoformat(schedule.last_run) if schedule.last_run else now
        schedule.next_run = compute_next_run(schedule.frequency, last_run=base)
    db.monitoring_config.update_one(
        {"repository": repo_id},
        {"$set": schedule.model_dump(mode="json")},
        upsert=True
    )
    return {"status": "updated"}


# --- Dashboard Monitoring Data ---

@router.get("/dashboard/{repo_owner}/{repo_name}")
async def monitoring_dashboard_data(
    repo_owner: str,
    repo_name: str,
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )
    repo_id = f"{repo_owner}/{repo_name}"
    db = get_mongo_db()

    health_scores = list(db.health_scores.find(
        {"repository": repo_id}, {"_id": 0}
    ).sort("recorded_at", -1).limit(10))

    watchlist = list(db.dependency_watchlist.find(
        {"repository": repo_id}, {"_id": 0}
    ).sort("risk_level", -1))

    alerts = list(db.alerts.find(
        {"repository": repo_id, "dismissed": False}, {"_id": 0}
    ).sort("created_at", -1).limit(50))

    schedule = db.monitoring_config.find_one({"repository": repo_id}, {"_id": 0})

    return {
        "repository": repo_id,
        "health_history": health_scores,
        "watchlist": watchlist,
        "active_alerts": alerts,
        "schedule": schedule or {"frequency": "weekly"}
    }


@router.get("/dashboard/{repo_owner}/{repo_name}/view", response_class=HTMLResponse)
async def monitoring_dashboard_view(
    repo_owner: str,
    repo_name: str,
    user=Depends(verify_session_token),
):
    html = (
        Path(__file__).resolve().parent.parent
        / "visualization" / "templates" / "monitoring_dashboard.html"
    ).read_text(encoding="utf-8")
    return HTMLResponse(html)


@router.post("/digest/{repo_owner}/{repo_name}/send")
async def send_digest(
    repo_owner: str,
    repo_name: str,
    user=Depends(verify_session_token),
):
    repo_id = f"{repo_owner}/{repo_name}"
    from app.worker.monitoring_worker import generate_weekly_digest
    from app.notifications.email_sender import send_digest_email

    digest = generate_weekly_digest(repo_id)
    session_data = get_session_data(user)
    to_email = session_data.get("github_email") or f"{user.get('github_login', 'user')}@users.noreply.github.com"
    sent = send_digest_email(to_email, repo_id, digest)
    return {"sent": sent, "to": to_email, "repository": repo_id, "digest": digest}
