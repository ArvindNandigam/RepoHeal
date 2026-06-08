import jwt
from fastapi import APIRouter, Request, Body
from fastapi.responses import RedirectResponse, JSONResponse
from app.auth.session_store import session_store
from app.auth.github_oauth import router as github_oauth_router
from app.auth.jwt_manager import verify_session_token
from app.utils.logger import get_logger
from app.config import settings

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Include the GitHub OAuth routes
router.include_router(github_oauth_router, prefix="/github")

@router.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("repoheal_session")
    response = RedirectResponse(url="/")

    if token:
        try:
            decoded = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=["HS256"]
            )
            session_id = decoded.get("session_id")
            if session_id:
                session_store.delete_session(session_id)
        except Exception:
            pass

    response.delete_cookie("repoheal_session")
    logger.info("User logged out")
    return response

@router.post("/timezone")
async def update_timezone(timezone: str = Body(..., embed=True), user=Depends(verify_session_token)):
    session_store.update_timezone(user["session_id"], timezone)
    return {"status": "ok", "timezone": timezone}
