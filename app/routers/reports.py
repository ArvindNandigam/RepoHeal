from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from app.auth.jwt_manager import verify_session_token
from app.errors.exceptions import AnalysisError
from app.github.client import RepoHealGitHubClient
from app.github.metadata_branch import MetadataBranchManager
from app.routers.dependencies import ensure_repoheal_installed
from pathlib import Path
from typing import Dict, Any, Optional, List

router = APIRouter(prefix="/reports", tags=["reports"])

def get_template(name: str) -> str:
    template_path = Path(__file__).parent.parent / "visualization" / "templates" / name
    return template_path.read_text(encoding="utf-8")

@router.get("/{repo_owner}/{repo_name}/health-page", response_class=HTMLResponse)
async def health_report_page(repo_owner: str, repo_name: str, user=Depends(verify_session_token)):
    return HTMLResponse(get_template("health_report.html"))

@router.get("/{repo_owner}/{repo_name}/migration-page", response_class=HTMLResponse)
async def migration_center_page(repo_owner: str, repo_name: str, user=Depends(verify_session_token)):
    return HTMLResponse(get_template("migration_center.html"))

@router.get("/{repo_owner}/{repo_name}/health")
async def get_health_report_data(
    repo_owner: str, 
    repo_name: str, 
    analysis_id: Optional[str] = Query(None),
    user=Depends(verify_session_token)
):
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    client = RepoHealGitHubClient(installation["id"])
    repo = client.get_repo(f"{repo_owner}/{repo_name}")
    metadata_manager = MetadataBranchManager(client)

    manifest = metadata_manager._load_manifest(repo)

    if analysis_id:
        report_meta = next((r for r in manifest.get("health_reports", []) if r["analysis_id"] == analysis_id), None)
        if not report_meta:
            raise HTTPException(status_code=404, detail="Health report not found for this analysis")
        path = report_meta["path"]
    else:
        path = manifest.get("latest_health_report")

    if not path:
        raise HTTPException(status_code=404, detail="No health report found")

    try:
        content = repo.get_contents(path, ref=metadata_manager.branch_name)
        import json
        data = json.loads(content.decoded_content.decode("utf-8"))
        report = data.get("report", {})
        return {
            **report,
            "generated_at": data.get("generated_at"),
            "analysis_id": data.get("analysis_id"),
            "repository_snapshot_id": data.get("repository_snapshot_id")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{repo_owner}/{repo_name}/migration")
async def get_migration_doc_data(
    repo_owner: str, 
    repo_name: str, 
    analysis_id: Optional[str] = Query(None),
    user=Depends(verify_session_token)
):
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    client = RepoHealGitHubClient(installation["id"])
    repo = client.get_repo(f"{repo_owner}/{repo_name}")
    metadata_manager = MetadataBranchManager(client)
    
    manifest = metadata_manager._load_manifest(repo)
    
    if analysis_id:
        doc_meta = next((r for r in manifest.get("migration_reports", []) if r["analysis_id"] == analysis_id), None)
        if not doc_meta:
            raise HTTPException(status_code=404, detail="Migration document not found for this analysis")
        path = doc_meta["path"]
    else:
        path = manifest.get("latest_migration")
        
    if not path:
        raise HTTPException(status_code=404, detail="No migration document found")

    try:
        content = repo.get_contents(path, ref=metadata_manager.branch_name)
        return {"content": content.decoded_content.decode("utf-8")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{repo_owner}/{repo_name}/comparisons")
async def list_comparisons(
    repo_owner: str,
    repo_name: str,
    user=Depends(verify_session_token)
):  
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    client = RepoHealGitHubClient(installation["id"])
    repo = client.get_repo(f"{repo_owner}/{repo_name}")
    metadata_manager = MetadataBranchManager(client)
    manifest = metadata_manager._load_manifest(repo)

    comparisons = manifest.get("comparisons", [])
    if isinstance(comparisons, list):
        return {"comparisons": comparisons, "repository": f"{repo_owner}/{repo_name}"}
    return {"comparisons": [], "repository": f"{repo_owner}/{repo_name}"}


@router.get("/{repo_owner}/{repo_name}/comparisons/{comparison_id}")
async def get_comparison(
    repo_owner: str,
    repo_name: str,
    comparison_id: str,
    user=Depends(verify_session_token)
):
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    client = RepoHealGitHubClient(installation["id"])
    repo = client.get_repo(f"{repo_owner}/{repo_name}")
    metadata_manager = MetadataBranchManager(client)
    manifest = metadata_manager._load_manifest(repo)

    comparisons = manifest.get("comparisons", [])
    if isinstance(comparisons, list):
        for c in comparisons:
            if c.get("comparison_id") == comparison_id or c.get("path", "").endswith(f"{comparison_id}.json"):
                try:
                    content = repo.get_contents(c["path"], ref=metadata_manager.branch_name)
                    import json
                    return json.loads(content.decoded_content.decode("utf-8"))
                except Exception as e:
                    raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(status_code=404, detail="Comparison not found")


@router.get("/{repo_owner}/{repo_name}/history")
async def get_analysis_history(
    repo_owner: str,
    repo_name: str,
    branch: Optional[str] = Query(None),
    user=Depends(verify_session_token)
):  
    installation = ensure_repoheal_installed(repo_owner, repo_name)
    client = RepoHealGitHubClient(installation["id"])
    repo = client.get_repo(f"{repo_owner}/{repo_name}")
    metadata_manager = MetadataBranchManager(client)
    manifest = metadata_manager._load_manifest(repo)

    analyses = manifest.get("analyses", [])
    health_reports = manifest.get("health_reports", [])

    timeline = []
    if isinstance(analyses, list):
        for a in analyses:
            if branch and a.get("branch") != branch:
                continue
            health_meta = None
            if isinstance(health_reports, list):
                health_meta = next((h for h in health_reports if h.get("analysis_id") == a.get("analysis_id")), None)
            entry = {
                "analysis_id": a.get("analysis_id"),
                "branch": a.get("branch"),
                "commit": a.get("commit"),
                "timestamp": a.get("timestamp"),
                "path": a.get("path"),
                "health_score": health_meta.get("health_score") if health_meta else None,
                "has_health_report": health_meta is not None
            }
            timeline.append(entry)

    timeline.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    current_head = None
    try:
        current_head = repo.get_branch(repo.default_branch).commit.sha[:7]
    except Exception:
        pass

    available_branches = sorted(set(a.get("branch") for a in (analyses if isinstance(analyses, list) else []) if a.get("branch")))

    return {
        "repository": f"{repo_owner}/{repo_name}",
        "default_branch": repo.default_branch,
        "current_head": current_head,
        "last_analyzed_commit": manifest.get("last_analyzed_commit"),
        "available_branches": available_branches,
        "timeline": timeline
    }


@router.get("/{repo_owner}/{repo_name}/hub", response_class=HTMLResponse)
async def reports_hub_page(repo_owner: str, repo_name: str, user=Depends(verify_session_token)):
    return HTMLResponse(get_template("reports_hub.html"))

@router.get("/{repo_owner}/{repo_name}/history-page", response_class=HTMLResponse)
async def analysis_history_page(repo_owner: str, repo_name: str, user=Depends(verify_session_token)):
    return HTMLResponse(get_template("analysis_history.html"))

@router.get("/{repo_owner}/{repo_name}/migration-review", response_class=HTMLResponse)
async def migration_review_page(repo_owner: str, repo_name: str, user=Depends(verify_session_token)):
    return HTMLResponse(get_template("migration_review.html"))
