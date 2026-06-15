from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["legal"])

_PRIVACY_PAGE = None
_TERMS_PAGE = None

def _privacy_template() -> str:
    global _PRIVACY_PAGE
    if _PRIVACY_PAGE is None:
        _PRIVACY_PAGE = (
            Path(__file__).resolve().parent.parent
            / "visualization" / "templates" / "privacy.html"
        ).read_text(encoding="utf-8")
    return _PRIVACY_PAGE

def _terms_template() -> str:
    global _TERMS_PAGE
    if _TERMS_PAGE is None:
        _TERMS_PAGE = (
            Path(__file__).resolve().parent.parent
            / "visualization" / "templates" / "terms.html"
        ).read_text(encoding="utf-8")
    return _TERMS_PAGE

@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    return HTMLResponse(_privacy_template())

@router.get("/terms-of-service", response_class=HTMLResponse)
async def terms_of_service():
    return HTMLResponse(_terms_template())
