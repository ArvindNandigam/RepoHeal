"""Scheduled re-analysis worker.

This module provides functions to check monitoring schedules and
queue analyses for repositories whose next_run is due.
Designed to be called from a cron job or APScheduler.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
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


def compute_next_run(frequency: str, last_run: Optional[datetime] = None) -> str:
    if frequency.isdigit():
        delta = timedelta(days=int(frequency))
    else:
        delta = FREQUENCY_DELTAS.get(frequency, timedelta(weeks=1))
    base = last_run if last_run else datetime.now(timezone.utc)
    return (base + delta).isoformat()


def check_due_repositories() -> list[dict]:
    """Find all repositories whose next_run <= now and queue analysis."""
    db = get_mongo_db()
    now_dt = datetime.now(timezone.utc)
    now_str = now_dt.isoformat()
    due = list(db.monitoring_config.find({
        "frequency": {"$ne": "manual"},
        "next_run": {"$lte": now_str}
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

        # Update next_run based on last_run (not now) to prevent drift
        last_run_str = config.get("last_run")
        try:
            last_run_dt = datetime.fromisoformat(last_run_str) if last_run_str else now_dt
        except (TypeError, ValueError):
            last_run_dt = now_dt
        db.monitoring_config.update_one(
            {"repository": repo_id},
            {"$set": {
                "last_run": now_str,
                "next_run": compute_next_run(config.get("frequency", "weekly"), last_run=last_run_dt)
            }}
        )

    return queued


def update_all_next_runs() -> int:
    """Set initial next_run for any schedule that lacks one."""
    db = get_mongo_db()
    now = datetime.now(timezone.utc)
    configs = list(db.monitoring_config.find(
        {"next_run": {"$exists": False}, "frequency": {"$ne": "manual"}}
    ))
    for config in configs:
        freq = config.get("frequency", "weekly")
        last_run = config.get("last_run")
        try:
            base = datetime.fromisoformat(last_run) if last_run else now
        except (TypeError, ValueError):
            base = now
        delta = FREQUENCY_DELTAS.get(freq, timedelta(weeks=1))
        if freq.isdigit():
            delta = timedelta(days=int(freq))
        next_run = (base + delta).isoformat()
        db.monitoring_config.update_one(
            {"_id": config["_id"]},
            {"$set": {"next_run": next_run}}
        )
    return len(configs)
