from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from app.auth.jwt_manager import verify_session_token
from app.auth.authorization import verify_repository_access
from app.config import settings
from app.errors.exceptions import AnalysisError
from app.github.client import RepoHealGitHubClient
from app.github.metadata_branch import MetadataBranchManager
from app.routers.dependencies import ensure_repoheal_installed, get_session_data
from pathlib import Path
from typing import Dict, Any, Optional, List

router = APIRouter(prefix="/reports", tags=["reports"])


def _authorize_reports_access(user: dict, repo_owner: str, repo_name: str) -> dict:
    session_data = get_session_data(user)
    verify_repository_access(
        github_token=session_data["github_token"],
        repo_owner=repo_owner,
        repo_name=repo_name,
    )
    return ensure_repoheal_installed(repo_owner, repo_name)

def _markdown_report(repository: str, report: dict) -> str:
    summary = report.get("executive_summary", {}) if isinstance(report, dict) else {}
    lines = [
        f"# RepoHeal health report: {repository}",
        "",
        f"- Health score: {summary.get('overall_health_score', report.get('overall_health_score', 'Unavailable'))}",
        f"- Risk score: {report.get('overall_risk_score', 'Unavailable')}",
        f"- Generated: {report.get('generated_at', 'Unavailable')}",
        "",
        "## Recommended actions",
    ]
    actions = report.get("recommended_actions", []) if isinstance(report, dict) else []
    if not actions:
        lines.append("- No recommended actions recorded.")
    else:
        for action in actions:
            if isinstance(action, dict):
                lines.append(f"- **{action.get('priority', 'normal')}** `{action.get('symbol', 'issue')}`: {action.get('description', action.get('recommendation', 'Review finding'))}")
            else:
                lines.append(f"- {action}")
    return "\n".join(lines) + "\n"

def get_template(name: str) -> str:
    template_path = Path(__file__).parent.parent / "visualization" / "templates" / name
    html = template_path.read_text(encoding="utf-8")
    return html.replace("{{ feedback_link }}", settings.FEEDBACK_LINK)

@router.get("/{repo_owner}/{repo_name}/health-page", response_class=HTMLResponse)
async def health_report_page(repo_owner: str, repo_name: str, user=Depends(verify_session_token)):
    _authorize_reports_access(user, repo_owner, repo_name)
    return HTMLResponse(get_template("health_report.html"))

@router.get("/{repo_owner}/{repo_name}/health")
async def get_health_report_data(
    repo_owner: str, 
    repo_name: str, 
    analysis_id: Optional[str] = Query(None),
    user=Depends(verify_session_token)
):
    installation = _authorize_reports_access(user, repo_owner, repo_name)
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
            "branch": data.get("branch"),
            "commit_sha": data.get("generated_from_commit"),
            "generated_at": data.get("generated_at"),
            "analysis_id": data.get("analysis_id"),
            "repository_snapshot_id": data.get("repository_snapshot_id"),
            "overall_risk_score": data.get("risk_score", report.get("overall_risk_score", 0)),
            "intelligence_warnings": data.get("intelligence_warnings", report.get("intelligence_warnings", [])),
        }
    except Exception as e:
        if hasattr(e, "status") and e.status == 404:
            # Fallback: try to find latest health report from health_reports list
            if not analysis_id:
                hr_list = manifest.get("health_reports", [])
                if hr_list:
                    latest_hr = max(hr_list, key=lambda x: x.get("timestamp", ""))
                    try:
                        content = repo.get_contents(latest_hr["path"], ref=metadata_manager.branch_name)
                        data = json.loads(content.decoded_content.decode("utf-8"))
                        report = data.get("report", {})
                        return {
                            **report,
                            "branch": data.get("branch"),
                            "commit_sha": data.get("generated_from_commit"),
                            "generated_at": data.get("generated_at"),
                            "analysis_id": data.get("analysis_id"),
                            "repository_snapshot_id": data.get("repository_snapshot_id"),
                            "overall_risk_score": data.get("risk_score", report.get("overall_risk_score", 0)),
                            "intelligence_warnings": data.get("intelligence_warnings", report.get("intelligence_warnings", [])),
                        }
                    except Exception:
                        pass
            raise HTTPException(status_code=404, detail="Health report not found on GitHub")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{repo_owner}/{repo_name}/migration")
async def get_migration_doc_data(
    repo_owner: str, 
    repo_name: str, 
    analysis_id: Optional[str] = Query(None),
    user=Depends(verify_session_token)
):
    installation = _authorize_reports_access(user, repo_owner, repo_name)
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
        if hasattr(e, "status") and e.status == 404:
            raise HTTPException(status_code=404, detail="Migration document not found on GitHub")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{repo_owner}/{repo_name}/history")
async def get_analysis_history(
    repo_owner: str,
    repo_name: str,
    branch: Optional[str] = Query(None),
    user=Depends(verify_session_token)
):  
    installation = _authorize_reports_access(user, repo_owner, repo_name)
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

@router.get("/{repo_owner}/{repo_name}/export")
async def export_report(
    repo_owner: str,
    repo_name: str,
    format: str = Query("json", pattern="^(json|markdown)$"),
    analysis_id: Optional[str] = Query(None),
    user=Depends(verify_session_token),
):
    report = await get_health_report_data(repo_owner, repo_name, analysis_id, user)
    repository = f"{repo_owner}/{repo_name}"
    if format == "markdown":
        return Response(
            content=_markdown_report(repository, report),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{repo_name}-health-report.md"'},
        )
    return report

@router.get("/{repo_owner}/{repo_name}/compare")
async def compare_reports(
    repo_owner: str,
    repo_name: str,
    left_analysis_id: Optional[str] = Query(None),
    right_analysis_id: Optional[str] = Query(None),
    user=Depends(verify_session_token),
):
    history = await get_analysis_history(repo_owner, repo_name, None, user)
    timeline = history.get("timeline", [])
    if len(timeline) < 2:
        return {
            "repository": f"{repo_owner}/{repo_name}",
            "available": False,
            "message": "At least two historical analyses are required for comparison.",
            "left": None,
            "right": None,
            "changes": [],
        }
    right = next((item for item in timeline if item.get("analysis_id") == right_analysis_id), None) if right_analysis_id else timeline[0]
    left = next((item for item in timeline if item.get("analysis_id") == left_analysis_id), None) if left_analysis_id else timeline[1]
    if not left or not right:
        raise HTTPException(status_code=404, detail="Requested analysis snapshot was not found")
    left_score = left.get("health_score")
    right_score = right.get("health_score")
    return {
        "repository": f"{repo_owner}/{repo_name}",
        "available": True,
        "left": left,
        "right": right,
        "changes": [
            {
                "metric": "health_score",
                "before": left_score,
                "after": right_score,
                "delta": (right_score - left_score) if isinstance(left_score, (int, float)) and isinstance(right_score, (int, float)) else None,
            },
            {
                "metric": "commit",
                "before": left.get("commit"),
                "after": right.get("commit"),
                "delta": None,
            },
        ],
    }


@router.get("/{repo_owner}/{repo_name}/hub", response_class=HTMLResponse)
async def reports_hub_page(repo_owner: str, repo_name: str, user=Depends(verify_session_token)):
    _authorize_reports_access(user, repo_owner, repo_name)
    return HTMLResponse(get_template("reports_hub.html"))

@router.get("/{repo_owner}/{repo_name}/history-page", response_class=HTMLResponse)
async def analysis_history_page(repo_owner: str, repo_name: str, user=Depends(verify_session_token)):
    _authorize_reports_access(user, repo_owner, repo_name)
    return HTMLResponse(get_template("analysis_history.html"))

@router.get("/{repo_owner}/{repo_name}/migration-reports", response_class=HTMLResponse)
async def migration_reports_page(repo_owner: str, repo_name: str, user=Depends(verify_session_token)):
    _authorize_reports_access(user, repo_owner, repo_name)
    return HTMLResponse(get_template("migration_reports.html"))

@router.get("/{repo_owner}/{repo_name}/migration-document", response_class=HTMLResponse)
async def migration_document_page(repo_owner: str, repo_name: str, user=Depends(verify_session_token)):
    _authorize_reports_access(user, repo_owner, repo_name)
    return HTMLResponse(get_template("migration_document.html"))
