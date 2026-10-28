from pathlib import Path
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from app.auth.jwt_manager import verify_session_token
from app.config import settings
from app.auth.authorization import verify_repository_access
from app.routers.dependencies import get_session_data, ensure_repoheal_installed, load_cached_analysis
from app.github.client import RepoHealGitHubClient
from app.worker.task_registry import get_repository_status

router = APIRouter(prefix="/repos", tags=["repo_detail"])

@router.get("/{repo_owner}/{repo_name}/overview")
async def repo_overview(repo_owner: str, repo_name: str, user=Depends(verify_session_token)):
    session_data = get_session_data(user)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name,
    )
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    repo_id = f"{repo_owner}/{repo_name}"
    status = get_repository_status(repo_owner, repo_name) or {}
    analysis = load_cached_analysis(repo_owner, repo_name) or {}
    try:
        client = RepoHealGitHubClient(installation["id"])
        repo = client.get_repo(repo_id)
        metadata = {
            "description": repo.description,
            "private": repo.private,
            "language": repo.language,
            "default_branch": repo.default_branch,
            "updated_at": repo.updated_at.isoformat() if repo.updated_at else None,
            "html_url": repo.html_url,
            "stars": repo.stargazers_count,
            "open_issues": repo.open_issues_count,
        }
    except Exception:
        metadata = {
            "description": None,
            "private": None,
            "language": None,
            "default_branch": status.get("selected_branch"),
            "updated_at": None,
            "html_url": f"https://github.com/{repo_id}",
            "stars": None,
            "open_issues": None,
        }
    report = analysis.get("report", {}) if isinstance(analysis, dict) else {}
    summary = report.get("executive_summary", {}) if isinstance(report, dict) else {}
    graph = analysis.get("graph", {}) if isinstance(analysis, dict) else {}
    return {
        "repository": repo_id,
        "metadata": metadata,
        "status": status,
        "health": {
            "score": summary.get("overall_health_score", report.get("overall_health_score")),
            "risk_score": report.get("overall_risk_score"),
            "issues": analysis.get("issues", {}),
        },
        "graph": {
            "files": len(analysis.get("imports", {}).get("files", {})),
            "packages": len(analysis.get("dependency_graph", {})),
            "statistics": graph.get("statistics", {}),
        },
        "available": bool(analysis or status),
    }

@router.get("/{repo_owner}/{repo_name}", response_class=HTMLResponse)
async def repo_detail_page(repo_owner: str, repo_name: str, user=Depends(verify_session_token)):
    template = (
        Path(__file__).resolve().parent.parent
        / "visualization" / "templates" / "repo_detail.html"
    ).read_text(encoding="utf-8")
    html = template.replace("{{ owner }}", repo_owner).replace("{{ repo }}", repo_name)
    html = html.replace("{{ feedback_link }}", settings.FEEDBACK_LINK)
    return HTMLResponse(html)
