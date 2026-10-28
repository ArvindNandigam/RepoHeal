from pathlib import Path
from app.models.schemas import DashboardResponse
from app.config import settings
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, HTMLResponse
from app.auth.jwt_manager import verify_session_token
from app.auth.session_store import session_store
from app.routers.dependencies import get_session_data, build_dashboard_repositories

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "frontend"
FRONTEND_DIST = FRONTEND_ROOT / "dist"

@router.get("/data", response_model=DashboardResponse)
async def dashboard_data(user=Depends(verify_session_token)):
    session_data = get_session_data(user)
    dashboard_repositories = build_dashboard_repositories(session_data["github_token"])
    analyzed = [repo for repo in dashboard_repositories if repo.get("health_score") is not None]
    scores = [repo["health_score"] for repo in analyzed]
    metrics = {
        "active_repositories": len(dashboard_repositories),
        "analyzed_repositories": len(analyzed),
        "average_health_score": round(sum(scores) / len(scores)) if scores else None,
        "open_issues": sum(repo.get("issue_count", 0) for repo in dashboard_repositories),
        "critical_issues": sum(repo.get("critical_issue_count", 0) for repo in dashboard_repositories),
        "active_analyses": sum(
            repo.get("analysis_status") in {
                "queued", "running", "analyzing", "generating_graph",
                "generating_reports", "generating_migrations", "updating_metadata"
            }
            for repo in dashboard_repositories
        ),
    }
    return {
        "user": user["github_login"],
        "repositories": dashboard_repositories,
        "timezone": user.get("timezone", "UTC"),
        "metrics": metrics,
    }

@router.get("", response_class=HTMLResponse)
async def dashboard(user=Depends(verify_session_token)):
    frontend_index = FRONTEND_DIST / "index.html"
    if frontend_index.is_file():
        return FileResponse(frontend_index)

    session_data = get_session_data(user)
    html = (
        Path(__file__).resolve().parent.parent
        / "visualization"
        / "templates"
        / "dashboard.html"
    ).read_text(encoding="utf-8")
    html = html.replace("{{ github_user }}", user["github_login"])
    html = html.replace("{{ feedback_link }}", settings.FEEDBACK_LINK)
    return HTMLResponse(html)
