import uuid
import asyncio
import traceback
from datetime import datetime, timedelta, timezone
from enum import Enum

from app.db.database import get_mongo_db
from app.utils.logger import get_logger

logger = get_logger(__name__)


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def create_job(repo_owner: str, repo_name: str) -> str:
    """Register a new job in MongoDB and return its ID."""
    job_id = str(uuid.uuid4())
    db = get_mongo_db()
    db.jobs.insert_one({
        "job_id": job_id,
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "status": JobStatus.QUEUED,
        "result": None,
        "error": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=24),
    })
    return job_id


def update_job(job_id: str, status: JobStatus, result=None, error=None):
    """Update job status in MongoDB."""
    db = get_mongo_db()
    update = {
        "status": status,
        "updated_at": datetime.now(timezone.utc),
    }
    if result is not None:
        update["result"] = result
    if error is not None:
        update["error"] = error
    db.jobs.update_one({"job_id": job_id}, {"$set": update})


def get_job(job_id: str):
    """Fetch a job by ID."""
    db = get_mongo_db()
    doc = db.jobs.find_one({"job_id": job_id}, {"_id": 0})
    if not doc:
        return None
    # Convert datetimes to ISO strings for JSON serialization
    for field in ("created_at", "updated_at", "expires_at"):
        if isinstance(doc.get(field), datetime):
            doc[field] = doc[field].isoformat()
    return doc


def run_analysis_in_background(job_id: str, repo_owner: str, repo_name: str):
    """
    Synchronous function that runs the full analysis pipeline.
    Called from FastAPI BackgroundTasks.
    """
    from app.analysis.repository_analyzer import analyze_repository
    from app.github.repository_fetcher import download_repository_snapshot, cleanup_repository
    from app.storage.metadata_store import save_analysis_to_metadata
    from app.routers.dependencies import get_repo_cache_path
    from app.graph.graph_builder import Neo4jGraphBuilder

    repo_id = f"{repo_owner}/{repo_name}"
    repo_path = None

    try:
        update_job(job_id, JobStatus.RUNNING)
        logger.info(f"Background analysis started for {repo_id} (job={job_id})")

        repo_path = download_repository_snapshot(repo_owner, repo_name)
        analysis = analyze_repository(repo_path)
        save_analysis_to_metadata(
            str(get_repo_cache_path(repo_owner, repo_name)),
            analysis
        )

        graph_builder = Neo4jGraphBuilder()
        graph_builder.build_graph(repo_id, analysis)

        update_job(job_id, JobStatus.COMPLETED, result={
            "repository": repo_id,
            "status": "analyzed",
        })
        logger.info(f"Background analysis completed for {repo_id} (job={job_id})")

    except Exception as e:
        error_msg = traceback.format_exc()
        update_job(job_id, JobStatus.FAILED, error=str(e))
        logger.error(f"Background analysis failed for {repo_id} (job={job_id}): {error_msg}")

    finally:
        if repo_path:
            cleanup_repository(repo_path)
