import re
from pathlib import Path
from app.auth.session_store import session_store
from app.errors.exceptions import AuthorizationError, AuthenticationError
from app.github.installations import get_repository_installation
from app.storage.metadata_store import MetadataStore
from app.github.user_repositories import fetch_user_repositories
from app.github.installed_repositories import get_installed_repositories
from app.worker.task_registry import get_repository_status

REPO_CACHE_ROOT = Path(".repoheal_cache")

def sanitize_repo_component(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", value)

def get_repo_cache_path(repo_owner: str, repo_name: str) -> Path:
    return REPO_CACHE_ROOT / sanitize_repo_component(repo_owner) / sanitize_repo_component(repo_name)

def ensure_repoheal_installed(repo_owner: str, repo_name: str):
    installation = get_repository_installation(repo_owner, repo_name)
    if not installation:
        raise AuthorizationError(message="RepoHeal is not installed on this repository")
    return installation

def load_cached_analysis(repo_owner: str, repo_name: str):
    cache_store = MetadataStore(str(get_repo_cache_path(repo_owner, repo_name)))

    full_analysis = cache_store.load_full_analysis_snapshot() or {}
    if full_analysis:
        return full_analysis

    imports = cache_store.load_imports() or {"files": {}, "summary": {}}
    dependencies = cache_store.load_packages() or {"declared": {}, "count": 0}
    dependency_graph = cache_store.load_dependency_graph() or {}
    summary = cache_store.load_analysis_snapshot() or {}

    return {
        "imports": imports,
        "dependencies": dependencies,
        "dependency_graph": dependency_graph,
        "issues": summary.get("issues", {})
    }

def get_session_data(user: dict):
    session_data = session_store.get_session(user["session_id"])
    if not session_data:
        raise AuthenticationError(message="Session expired")
    if session_data.get("github_id") != user.get("github_id"):
        raise AuthenticationError(message="Session mismatch")
    return session_data

def build_dashboard_repositories(github_token: str):
    repositories = fetch_user_repositories(github_token)
    installed_repositories = get_installed_repositories()
    dashboard_repositories = []
    for repo in repositories:
        owner_login = repo.get("owner", {}).get("login")
        repo_name = repo.get("name")
        repo_full_name = repo.get("full_name")
        repo_private = repo.get("private", False)
        if not owner_login or not repo_name or not repo_full_name or repo_full_name not in installed_repositories:
            continue
        status = get_repository_status(owner_login, repo_name) or {}
        health_score = None
        issue_count = 0
        critical_issue_count = 0
        try:
            analysis = load_cached_analysis(owner_login, repo_name)
            report = analysis.get("report", {}) if isinstance(analysis, dict) else {}
            summary = report.get("executive_summary", {}) if isinstance(report, dict) else {}
            health_score = summary.get("overall_health_score", report.get("overall_health_score"))
            issues = analysis.get("issues", {}) if isinstance(analysis, dict) else {}
            issue_count = int(issues.get("total", issues.get("count", 0)) or 0)
            critical_issue_count = int(issues.get("critical", issues.get("high", 0)) or 0)
        except (TypeError, ValueError):
            pass
        current_head = status.get("current_head")
        last_commit = status.get("last_commit_analyzed") or status.get("target_commit_sha")
        score = int(health_score) if isinstance(health_score, (int, float)) else None
        dashboard_repositories.append({
            "name": repo_full_name,
            "owner": owner_login,
            "repo": repo_name,
            "private": repo_private,
            "analyze_url": f"/analyze/{owner_login}/{repo_name}",
            "reanalyze_url": f"/reanalyze/{owner_login}/{repo_name}",
            "health_refresh_url": f"/health-refresh/{owner_login}/{repo_name}",
            "status_url": f"/status/{owner_login}/{repo_name}",
            "visualize_url": f"/visualize/{owner_login}/{repo_name}",
            "reports_url": f"/reports/{owner_login}/{repo_name}",
            "reports_hub_url": f"/reports/{owner_login}/{repo_name}/hub",
            "history_url": f"/reports/{owner_login}/{repo_name}/history-page",
            "description": repo.get("description"),
            "language": repo.get("language"),
            "default_branch": repo.get("default_branch"),
            "updated_at": repo.get("updated_at"),
            "health_score": score,
            "issue_count": issue_count,
            "critical_issue_count": critical_issue_count,
            "analysis_status": status.get("status", "not_analyzed"),
            "analysis_progress": status.get("progress", 0),
            "last_analysis": status.get("last_analysis"),
            "last_commit_analyzed": last_commit,
            "current_head": current_head,
            "trend": [],
        })
    return dashboard_repositories
