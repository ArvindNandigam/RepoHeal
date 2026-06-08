from pathlib import Path
from app.models.schemas import DashboardResponse
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from app.auth.jwt_manager import verify_session_token
from app.auth.session_store import session_store
from app.routers.dependencies import get_session_data, build_dashboard_repositories

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

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
    session_data = get_session_data(user)
    html = (
        Path(__file__).resolve().parent.parent
        / "visualization"
        / "templates"
        / "dashboard.html"
    ).read_text(encoding="utf-8")
    html = html.replace("{{ github_user }}", user["github_login"])
    return HTMLResponse(html)
