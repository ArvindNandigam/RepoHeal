from pathlib import Path
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from app.auth.jwt_manager import verify_session_token

router = APIRouter(prefix="/repos", tags=["repo_detail"])

@router.get("/{repo_owner}/{repo_name}", response_class=HTMLResponse)
async def repo_detail_page(repo_owner: str, repo_name: str, user=Depends(verify_session_token)):
    template = (
        Path(__file__).resolve().parent.parent
        / "visualization" / "templates" / "repo_detail.html"
    ).read_text(encoding="utf-8")
    html = template.replace("{{ owner }}", repo_owner).replace("{{ repo }}", repo_name)
    return HTMLResponse(html)
