from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from app.auth.jwt_manager import verify_session_token
from app.worker.metrics import get_all_metrics
from app.db.database import get_mongo_db
from app.worker.task_registry import get_active_jobs

router = APIRouter(tags=["admin"])

ADMIN_USERS = {"ArvindNandigam"}


def require_admin(user=Depends(verify_session_token)):
    login = user.get("github_login")
    if not login or login not in ADMIN_USERS:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@router.get("/admin/metrics")
async def admin_metrics_json(user=Depends(require_admin)):
    return get_all_metrics()


@router.get("/admin/observability")
async def admin_observability(user=Depends(require_admin)):
    """Phase 9: Observability metrics — memory, storage, performance, reliability."""
    db = get_mongo_db()
    metrics = get_all_metrics()

    # Active jobs
    active_jobs = get_active_jobs()
    orphaned_jobs = list(
        db.jobs.find({"status": "orphaned"}, {"_id": 0}).sort("updated_at", -1).limit(20)
    )

    # Storage
    cache_size_mb = 0
    from app.routers.dependencies import REPO_CACHE_ROOT
    import shutil
    import os as _os
    cache_root = str(REPO_CACHE_ROOT)
    if _os.path.exists(cache_root):
        for dirpath, dirnames, filenames in _os.walk(cache_root):
            for f in filenames:
                fp = _os.path.join(dirpath, f)
                try:
                    cache_size_mb += _os.path.getsize(fp)
                except OSError:
                    pass
        cache_size_mb = cache_size_mb / 1024 / 1024

    # Free disk space
    free_disk_mb = 0
    try:
        du = shutil.disk_usage(cache_root if _os.path.exists(cache_root) else "/")
        free_disk_mb = du.free / 1024 / 1024
    except Exception:
        pass

    # Performance
    avg_time = metrics.get("average_analysis_time", 0)
    success_rate = metrics.get("success_rate", 0)
    total_analyses = metrics.get("analysis_count", 0)

    # Cache governance status
    config = __import__("app.config", fromlist=["settings"]).settings
    limits = {
        "max_cache_size_mb": getattr(config, "MAX_CACHE_SIZE_MB", 50),
        "max_analysis_history": getattr(config, "MAX_ANALYSIS_HISTORY", 2),
        "cache_retention_days": getattr(config, "CACHE_RETENTION_DAYS", 7),
        "max_zip_size_mb": getattr(config, "MAX_ZIP_SIZE_MB", 50),
        "max_extracted_size_mb": getattr(config, "MAX_EXTRACTED_SIZE_MB", 100),
        "max_file_count": getattr(config, "MAX_FILE_COUNT", 5000),
        "max_python_file_count": getattr(config, "MAX_PYTHON_FILE_COUNT", 2000),
        "orphan_timeout_minutes": getattr(config, "JOB_ORPHAN_TIMEOUT_MINUTES", 15),
        "min_free_disk_mb": getattr(config, "MIN_FREE_DISK_MB", 50),
        "use_disk_extraction": getattr(config, "USE_DISK_EXTRACTION", False),
    }

    return {
        "free_disk_mb": round(free_disk_mb, 1),
        "cache_size_mb": round(cache_size_mb, 1),
        "active_jobs_count": len(active_jobs),
        "active_jobs": active_jobs,
        "orphaned_jobs": orphaned_jobs,
        "orphaned_count": len(orphaned_jobs),
        "average_analysis_time_s": avg_time,
        "success_rate_pct": success_rate,
        "total_analyses": total_analyses,
        "limits": limits,
        "platform_metrics": metrics,
    }


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard_page(user=Depends(require_admin)):
    import os
    html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "visualization", "templates", "admin_metrics.html")
    if not os.path.exists(html_path):
        html_path = __file__.replace("routers\\admin.py", "visualization\\templates\\admin_metrics.html")
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    return html.replace("{{ github_user }}", user.get("github_login", ""))
