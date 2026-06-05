from fastapi import APIRouter, Depends
from app.models.schemas import WorkspaceResponse
from app.auth.jwt_manager import verify_session_token
from app.auth.authorization import verify_repository_access
from app.routers.dependencies import get_session_data, ensure_repoheal_installed

router = APIRouter(prefix="/workspace", tags=["workspace"])

@router.get("/{repo_owner}/{repo_name}", response_model=WorkspaceResponse)
async def workspace_landing_page(
    repo_owner: str,
    repo_name: str,
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    return {
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "user": user["github_login"],
        "workspace_url": f"/workspace/{repo_owner}/{repo_name}",
        "status": "ready"
    }
