from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from app.errors.exceptions import RepoHealError, repoheal_error_handler
from app.auth.jwt_manager import SessionExpired

async def session_expired_handler(request: Request, exc: SessionExpired):
    return RedirectResponse(url=exc.redirect_url)

def register_error_handlers(app: FastAPI):
    app.add_exception_handler(RepoHealError, repoheal_error_handler)
    app.add_exception_handler(SessionExpired, session_expired_handler)
