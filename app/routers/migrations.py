from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from app.auth.jwt_manager import verify_session_token
from app.auth.authorization import verify_repository_access
from app.routers.dependencies import get_session_data, ensure_repoheal_installed
from app.github.client import RepoHealGitHubClient
from app.github.metadata_branch import MetadataBranchManager
from app.remediation.orchestrator import RemediationOrchestrator
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/migrations", tags=["migrations"])


@router.get("/{repo_owner}/{repo_name}")
async def list_migrations(
    repo_owner: str,
    repo_name: str,
    status: Optional[str] = Query(None),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    client = RepoHealGitHubClient(installation["id"])
    repo = client.get_repo(f"{repo_owner}/{repo_name}")
    metadata_manager = MetadataBranchManager(client)
    manifest = metadata_manager._load_manifest(repo)

    migrations = manifest.get("migration_reports", [])
    if isinstance(migrations, list):
        if status:
            migrations = [m for m in migrations if m.get("status", "completed") == status]
        return {"migrations": migrations, "repository": f"{repo_owner}/{repo_name}"}
    return {"migrations": [], "repository": f"{repo_owner}/{repo_name}"}


@router.get("/detail/{migration_id}")
async def get_migration(
    migration_id: str,
    repo_owner: str = Query(...),
    repo_name: str = Query(...),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    client = RepoHealGitHubClient(installation["id"])
    repo = client.get_repo(f"{repo_owner}/{repo_name}")
    metadata_manager = MetadataBranchManager(client)
    manifest = metadata_manager._load_manifest(repo)

    for mig in manifest.get("migration_reports", []):
        if mig.get("migration_id") == migration_id or mig.get("analysis_id") == migration_id:
            try:
                content = repo.get_contents(mig["path"], ref=metadata_manager.branch_name)
                return {
                    "migration_id": mig.get("migration_id"),
                    "analysis_id": mig.get("analysis_id"),
                    "timestamp": mig.get("timestamp"),
                    "risk_score": mig.get("risk_score"),
                    "status": mig.get("status", "completed"),
                    "path": mig["path"],
                    "content": content.decoded_content.decode("utf-8")
                }
            except Exception as e:
                return {
                    "migration_id": mig.get("migration_id"),
                    "analysis_id": mig.get("analysis_id"),
                    "timestamp": mig.get("timestamp"),
                    "risk_score": mig.get("risk_score"),
                    "status": mig.get("status", "completed"),
                    "path": mig["path"]
                }

    raise HTTPException(status_code=404, detail="Migration not found")


@router.post("/{migration_id}/approve")
async def approve_migration(
    migration_id: str,
    repo_owner: str = Query(...),
    repo_name: str = Query(...),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    repo_id = f"{repo_owner}/{repo_name}"
    client = RepoHealGitHubClient(installation["id"])
    repo = client.get_repo(repo_id)
    metadata_manager = MetadataBranchManager(client)
    manifest = metadata_manager._load_manifest(repo)

    mig_meta = None
    for mig in manifest.get("migration_reports", []):
        if mig.get("migration_id") == migration_id or mig.get("analysis_id") == migration_id:
            mig_meta = mig
            break

    if not mig_meta:
        raise HTTPException(status_code=404, detail="Migration not found")

    mig_meta["status"] = "approved"
    mig_meta["approved_at"] = datetime.now(timezone.utc).isoformat()

    files = {"repoheal.meta/metadata.json": metadata_manager._json(manifest)}
    client.batch_upsert_files(repo, metadata_manager.branch_name, files, f"Approve {migration_id}")

    risk_score = mig_meta.get("risk_score", 50)
    try:
        orchestrator = RemediationOrchestrator(client)
        import asyncio
        result = asyncio.run(orchestrator.process_migration(
            repo_id=repo_id,
            analysis_id=mig_meta.get("analysis_id", ""),
            migration_id=migration_id,
            risk_score=risk_score,
            patches=[]
        ))
        return {"status": "approved", "migration_id": migration_id, "pr_created": result is not None, "pr": str(result) if result else None}
    except Exception as e:
        logger.error(f"PR creation failed for approved migration {migration_id}: {e}")
        return {"status": "approved", "migration_id": migration_id, "pr_created": False, "error": str(e)}


@router.post("/{migration_id}/reject")
async def reject_migration(
    migration_id: str,
    repo_owner: str = Query(...),
    repo_name: str = Query(...),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    client = RepoHealGitHubClient(installation["id"])
    repo = client.get_repo(f"{repo_owner}/{repo_name}")
    metadata_manager = MetadataBranchManager(client)
    manifest = metadata_manager._load_manifest(repo)

    for mig in manifest.get("migration_reports", []):
        if mig.get("migration_id") == migration_id or mig.get("analysis_id") == migration_id:
            mig["status"] = "rejected"
            mig["rejected_at"] = datetime.now(timezone.utc).isoformat()
            files = {"repoheal.meta/metadata.json": metadata_manager._json(manifest)}
            client.batch_upsert_files(repo, metadata_manager.branch_name, files, f"Reject {migration_id}")
            return {"status": "rejected", "migration_id": migration_id}

    raise HTTPException(status_code=404, detail="Migration not found")


@router.post("/{migration_id}/defer")
async def defer_migration(
    migration_id: str,
    repo_owner: str = Query(...),
    repo_name: str = Query(...),
    user=Depends(verify_session_token)
):
    session_data = get_session_data(user)
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name
    )

    client = RepoHealGitHubClient(installation["id"])
    repo = client.get_repo(f"{repo_owner}/{repo_name}")
    metadata_manager = MetadataBranchManager(client)
    manifest = metadata_manager._load_manifest(repo)

    for mig in manifest.get("migration_reports", []):
        if mig.get("migration_id") == migration_id or mig.get("analysis_id") == migration_id:
            mig["status"] = "deferred"
            mig["deferred_at"] = datetime.now(timezone.utc).isoformat()
        files = {"repoheal.meta/metadata.json": metadata_manager._json(manifest)}
        client.batch_upsert_files(repo, metadata_manager.branch_name, files, f"Defer {migration_id}")
        return {"status": "deferred", "migration_id": migration_id}

    raise HTTPException(status_code=404, detail="Migration not found")


@router.get("/review", response_class=HTMLResponse)
async def migration_review_page(user=Depends(verify_session_token)):
    html = (
        Path(__file__).resolve().parent.parent
        / "visualization" / "templates" / "migration_review.html"
    ).read_text(encoding="utf-8")
    return HTMLResponse(html)
