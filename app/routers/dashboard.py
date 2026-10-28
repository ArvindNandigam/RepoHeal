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
    return {
        "user": user["github_login"],
        "repositories": dashboard_repositories,
        "timezone": user.get("timezone", "UTC")
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
