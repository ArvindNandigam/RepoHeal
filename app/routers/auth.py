from pathlib import Path
import jwt
from fastapi import APIRouter, Request, Body, Depends, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from app.auth.session_store import session_store
from app.auth.github_oauth import router as github_oauth_router
from app.auth.jwt_manager import verify_session_token
from app.utils.logger import get_logger
from app.config import settings

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

router.include_router(github_oauth_router, prefix="/github")

LOGIN_PAGE = None

def _login_template() -> str:
    global LOGIN_PAGE
    if LOGIN_PAGE is None:
        LOGIN_PAGE = (
            Path(__file__).resolve().parent.parent
            / "visualization" / "templates" / "login.html"
        ).read_text(encoding="utf-8")
    return LOGIN_PAGE

@router.get("/login-page", response_class=HTMLResponse)
async def login_page(reason: str = Query("login")):
    html = _login_template()
    status_map = {
        "logout": ("success", "Logged Out", "You have been successfully logged out."),
        "expired": ("warning", "Session Expired", "Your session has expired. Please sign in again."),
        "login": ("", "", "Sign in with GitHub to manage your repositories."),
    }
    cls, badge, msg = status_map.get(reason, status_map["login"])
    html = html.replace("{{ status_class }}", cls)
    html = html.replace("{{ status_badge }}", badge)
    html = html.replace("{{ status_message }}", msg)
    return HTMLResponse(html)

@router.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("repoheal_session")
    if token:
        try:
            decoded = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
            session_id = decoded.get("session_id")
            if session_id:
                session_store.delete_session(session_id)
        except Exception:
            pass
    response = RedirectResponse(url="/auth/login-page?reason=logout")
    response.delete_cookie("repoheal_session")
    logger.info("User logged out")
    return response

@router.get("/switch-account")
async def switch_account(request: Request):
    token = request.cookies.get("repoheal_session")
    if token:
        try:
            decoded = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
            session_id = decoded.get("session_id")
            if session_id:
                session_store.delete_session(session_id)
        except Exception:
            pass
    response = RedirectResponse(
        url=f"https://github.com/login/oauth/authorize"
             f"?client_id={settings.GITHUB_OAUTH_CLIENT_ID}"
             f"&scope=repo%20read:user%20read:org"
             f"&redirect_uri=https://repoheal.onrender.com/auth/github/callback"
             f"&force_login=true"
    )
    response.delete_cookie("repoheal_session")
    logger.info("User switching account")
    return response

@router.post("/timezone")
async def update_timezone(timezone: str = Body(..., embed=True), user=Depends(verify_session_token)):
    session_store.update_timezone(user["session_id"], timezone)
    return {"status": "ok", "timezone": timezone}
