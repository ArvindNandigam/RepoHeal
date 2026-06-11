from fastapi import APIRouter, Depends, HTTPException
from app.auth.jwt_manager import verify_session_token
from app.routers.dependencies import ensure_repoheal_installed
from app.github.client import RepoHealGitHubClient

router = APIRouter(prefix="/repos", tags=["repo_data"])

@router.get("/{repo_owner}/{repo_name}/branches")
async def list_branches(
    repo_owner: str,
    repo_name: str,
    user=Depends(verify_session_token)
):
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    client = RepoHealGitHubClient(installation["id"])
    try:
        repo = client.github.get_repo(f"{repo_owner}/{repo_name}")
        branches = [b.name for b in repo.get_branches()]
        return {"branches": branches}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{repo_owner}/{repo_name}/commits")
async def list_commits(
    repo_owner: str,
    repo_name: str,
    branch: str = "main",
    user=Depends(verify_session_token)
):
    from app.utils.logger import get_logger as _get_log
    _log = _get_log(__name__)
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    client = RepoHealGitHubClient(installation["id"])
    try:
        repo = client.github.get_repo(f"{repo_owner}/{repo_name}")
        try:
            commits = []
            for c in repo.get_commits(sha=branch)[:50]:
                commits.append({
                    "sha": c.sha,
                    "message": c.commit.message.split("\n")[0],
                    "date": c.commit.author.date.isoformat() if c.commit and c.commit.author else None,
                })
            return {"commits": commits}
        except Exception as gh_err:
            _log.warning("GitHub API error fetching commits for %s/%s branch=%s: %s", repo_owner, repo_name, branch, gh_err)
            return {"commits": [], "error": str(gh_err)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
