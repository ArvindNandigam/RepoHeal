"""Scheduled re-analysis worker.

This module provides functions to check monitoring schedules and
queue analyses for repositories whose next_run is due.
Designed to be called from a cron job or APScheduler.
"""

from datetime import datetime, timezone, timedelta
from app.db.database import get_mongo_db
from app.worker.task_registry import create_job
from app.utils.logger import get_logger

logger = get_logger(__name__)

FREQUENCY_DELTAS = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "biweekly": timedelta(weeks=2),
    "monthly": timedelta(days=30),
}


def compute_next_run(frequency: str) -> str:
    if frequency.isdigit():
        delta = timedelta(days=int(frequency))
    else:
        delta = FREQUENCY_DELTAS.get(frequency, timedelta(weeks=1))
    return (datetime.now(timezone.utc) + delta).isoformat()


def check_due_repositories() -> list[dict]:
    """Find all repositories whose next_run <= now and queue analysis."""
    db = get_mongo_db()
    now = datetime.now(timezone.utc).isoformat()
    due = list(db.monitoring_config.find({
        "frequency": {"$ne": "manual"},
        "next_run": {"$lte": now}
    }))

    queued = []
    for config in due:
        repo_id = config.get("repository", "")
        if "/" not in repo_id:
            continue
        repo_owner, repo_name = repo_id.split("/", 1)
        branches = config.get("branches", ["main"])

        for branch in branches:
            job_id = create_job(
                repo_owner, repo_name,
                force=True,
                job_type="scheduled",
                target_branch=branch
            )
            if job_id:
                queued.append({"repository": repo_id, "branch": branch, "job_id": job_id})
                logger.info(f"Scheduled analysis queued for {repo_id} @ {branch}")

        # Update next_run
        db.monitoring_config.update_one(
            {"repository": repo_id},
            {"$set": {
                "last_run": now,
                "next_run": compute_next_run(config.get("frequency", "weekly"))
            }}
        )

    return queued


def update_all_next_runs() -> int:
    """Set initial next_run for any schedule that lacks one."""
    db = get_mongo_db()
    now = datetime.now(timezone.utc)
    result = db.monitoring_config.update_many(
        {"next_run": {"$exists": False}, "frequency": {"$ne": "manual"}},
        {"$set": {"next_run": (now + timedelta(hours=1)).isoformat()}}
    )
    return getattr(result, "modified_count", 0)
