import asyncio
import json
from datetime import datetime
from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse
from app.auth.jwt_manager import verify_session_token
from app.db.database import get_mongo_db
from app.github.client import RepoHealGitHubClient
from app.github.metadata_branch import MetadataBranchManager
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/sse", tags=["sse"])

async def status_event_generator(request: Request, repo_owner: str, repo_name: str):
    db = get_mongo_db()
    last_status = None
    last_migration_state = None
    last_pr_state = None
    manifest_poll_count = 0
    
    while True:
        if await request.is_disconnected():
            break
        
        repo_id = f"{repo_owner}/{repo_name}"
        
        # Analysis progress events
        status = db.repository_analysis_status.find_one({
            "repo_owner": repo_owner,
            "repo_name": repo_name
        })
        
        if status:
            message = status.get("message", "")
            progress = status.get("progress", 0)
            eta_seconds = None
            if "ETA:" in message:
                import re as _re
                total = 0
                for eta_match in _re.finditer(r"([\d]+)\s*([smh])", message.split("ETA:")[-1]):
                    val = int(eta_match.group(1))
                    unit = eta_match.group(2)
                    if unit == "s":
                        total += val
                    elif unit == "m":
                        total += val * 60
                    elif unit == "h":
                        total += val * 3600
                if total > 0:
                    eta_seconds = total

            def _to_str(val):
                if isinstance(val, datetime):
                    return val.isoformat()
                return str(val) if val is not None else None

            current_state = {
                "status": status.get("status"),
                "progress": progress,
                "message": message,
                "eta_seconds": eta_seconds,
                "job_id": status.get("job_id"),
                "analysis_id": status.get("analysis_id"),
                "repository_snapshot_id": status.get("repository_snapshot_id"),
                "job_type": status.get("job_type"),
                "selected_branch": status.get("selected_branch"),
                "target_commit_sha": status.get("target_commit_sha"),
                "current_head": status.get("current_head"),
                "last_commit_analyzed": status.get("last_commit_analyzed"),
                "last_analysis": _to_str(status.get("last_analysis")),
                "last_health_refresh": _to_str(status.get("last_health_refresh")),
                "code_state_status": status.get("code_state_status"),
            }
            
            if current_state != last_status:
                yield f"data: {json.dumps(current_state)}\n\n"
                last_status = current_state
        
        # Migration and PR status (check manifest every 10 iterations = ~20s)
        manifest_poll_count += 1
        if manifest_poll_count >= 10:
            manifest_poll_count = 0
            try:
                from app.routers.dependencies import ensure_repoheal_installed
                installation = ensure_repoheal_installed(repo_owner, repo_name)
                client = RepoHealGitHubClient(installation["id"])
                repo = client.get_repo(repo_id)
                metadata_manager = MetadataBranchManager(client)
                manifest = metadata_manager._load_manifest(repo)
                
                # Migration events
                migrations = manifest.get("migration_reports", [])
                if isinstance(migrations, list) and migrations:
                    latest_mig = migrations[-1]
                    mig_state = {
                        "migration_id": latest_mig.get("migration_id"),
                        "analysis_id": latest_mig.get("analysis_id"),
                        "timestamp": latest_mig.get("timestamp"),
                        "risk_score": latest_mig.get("risk_score"),
                        "status": latest_mig.get("status", "completed"),
                        "count": len(migrations),
                    }
                    if mig_state != last_migration_state:
                        yield f"event: migration\ndata: {json.dumps(mig_state)}\n\n"
                        last_migration_state = mig_state
                
                # PR events
                prs = manifest.get("pull_requests", [])
                if isinstance(prs, list) and prs:
                    latest_pr = prs[-1]
                    pr_state = {
                        "pr_number": latest_pr.get("pr_number"),
                        "pr_url": latest_pr.get("pr_url"),
                        "status": latest_pr.get("status", "open"),
                        "migration_id": latest_pr.get("migration_id"),
                        "analysis_id": latest_pr.get("analysis_id"),
                        "count": len(prs),
                    }
                    if pr_state != last_pr_state:
                        yield f"event: pr\ndata: {json.dumps(pr_state)}\n\n"
                        last_pr_state = pr_state
            except Exception as e:
                logger.debug(f"SSE manifest poll failed: {e}")
        
        await asyncio.sleep(2)

@router.get("/status/{repo_owner}/{repo_name}")
async def stream_status(repo_owner: str, repo_name: str, request: Request, user=Depends(verify_session_token)):
    return StreamingResponse(
        status_event_generator(request, repo_owner, repo_name),
        media_type="text/event-stream"
    )
