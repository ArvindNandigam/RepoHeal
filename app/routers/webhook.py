from datetime import datetime
import shutil
from fastapi import APIRouter, BackgroundTasks, Request
from app.errors.exceptions import AuthenticationError, ExternalServiceError
from app.github.webhooks import verify_github_signature
from app.github.client import RepoHealGitHubClient
from app.github.metadata_branch import MetadataBranchManager
from app.github.installed_repositories import (
    upsert_installed_repositories,
    remove_installed_repositories,
    list_installed_repositories_for_installation
)
from app.graph.graph_builder import Neo4jGraphBuilder
from app.routers.dependencies import get_repo_cache_path
from app.utils.logger import get_logger
from app.db.database import get_mongo_db
from app.worker.task_registry import (
    cancel_repository_jobs,
    create_job,
    run_analysis_in_background,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])

@router.post("/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        await verify_github_signature(request)
    except Exception as e:
        logger.error(f"Webhook verification failed: {e}")
        raise AuthenticationError(message="Invalid GitHub signature")

    payload = await request.json()
    event_type = request.headers.get("X-GitHub-Event")
    event_action = payload.get("action")

    logger.info(f"Received GitHub event: {event_type} ({event_action})")

    if event_type == "installation" and event_action == "created":
        installation = payload.get("installation") or {}
        installation_id = installation.get("id")
        if not installation_id:
            raise ExternalServiceError(message="Missing installation id")

        bootstrap_client = RepoHealGitHubClient(installation_id)
        installation_repositories = bootstrap_client.list_installation_repositories()
        upsert_installed_repositories(installation_id, installation_repositories)
        background_tasks.add_task(
            bootstrap_installation_metadata,
            installation_id,
            installation_repositories
        )
        queued_repositories = queue_repository_analyses(
            background_tasks,
            installation_repositories
        )

        return {
            "received": True,
            "event": event_type,
            "action": event_action,
            "bootstrapped_repositories": [
                repository.get("full_name")
                for repository in installation_repositories
                if repository.get("full_name")
            ],
            "queued_repositories": queued_repositories,
            "timestamp": datetime.utcnow().isoformat()
        }

    if event_type == "installation_repositories":
        installation = payload.get("installation") or {}
        installation_id = installation.get("id")
        if not installation_id:
            raise ExternalServiceError(message="Missing installation id")

        repositories_added = payload.get("repositories_added") or []
        repositories_removed = payload.get("repositories_removed") or []

        if repositories_added:
            upsert_installed_repositories(installation_id, repositories_added)
            background_tasks.add_task(
                bootstrap_installation_metadata,
                installation_id,
                repositories_added
            )
            queue_repository_analyses(background_tasks, repositories_added)

        if repositories_removed:
            # Partial removal: clean up data but skip metadata branch marking
            # since the installation is still active for other repos.
            for repository in repositories_removed:
                full_name = repository.get("full_name")
                if not full_name or "/" not in full_name:
                    continue
                repo_owner, repo_name = full_name.split("/", 1)
                repo_id = f"{repo_owner}/{repo_name}"
                try:
                    cancel_repository_jobs(repo_owner, repo_name)
                except Exception as exc:
                    logger.error(f"Job cleanup failed for {repo_id}: {exc}")
                try:
                    Neo4jGraphBuilder().clear_repository_graph(repo_id)
                except Exception as exc:
                    logger.error(f"Neo4j cleanup failed for {repo_id}: {exc}")
                try:
                    shutil.rmtree(get_repo_cache_path(repo_owner, repo_name), ignore_errors=True)
                except Exception as exc:
                    logger.error(f"Cache cleanup failed for {repo_id}: {exc}")
                _cleanup_mongodb_state(repo_owner, repo_name)
            remove_installed_repositories(
                installation_id,
                [
                    repository.get("id")
                    for repository in repositories_removed
                    if repository.get("id")
                ]
            )

        return {
            "received": True,
            "event": event_type,
            "added": len(repositories_added),
            "removed": len(repositories_removed),
            "timestamp": datetime.utcnow().isoformat()
        }

    if event_type == "installation" and event_action == "deleted":
        installation = payload.get("installation") or {}
        installation_id = installation.get("id")
        if installation_id:
            repositories = _repositories_for_uninstall(
                installation_id,
                payload.get("repositories") or []
            )
            cleanup_uninstalled_repositories(installation_id, repositories)
            remove_installed_repositories(installation_id)

        return {
            "received": True,
            "event": event_type,
            "action": event_action,
            "timestamp": datetime.utcnow().isoformat()
        }

    return {
        "received": True,
        "event": event_type,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.delete("/uninstall/{installation_id}")
async def manual_uninstall_endpoint(
    installation_id: int,
    request: Request,
    background_tasks: BackgroundTasks
):
    """Admin endpoint to manually trigger full uninstall cleanup for an installation."""
    repositories = list_installed_repositories_for_installation(installation_id)
    if not repositories:
        return {
            "status": "not_found",
            "installation_id": installation_id,
            "message": "No repositories found for this installation"
        }
    background_tasks.add_task(
        _run_full_uninstall,
        installation_id,
        repositories
    )
    return {
        "status": "queued",
        "installation_id": installation_id,
        "repositories": [r.get("full_name") for r in repositories],
        "message": f"Uninstall cleanup queued for {len(repositories)} repositories"
    }


def _run_full_uninstall(installation_id: int, repositories: list[dict]) -> None:
    cleanup_uninstalled_repositories(installation_id, repositories)
    remove_installed_repositories(installation_id)
    logger.info(f"Full uninstall completed for installation {installation_id}")


def bootstrap_installation_metadata(
    installation_id: int,
    repositories: list[dict]
):
    try:
        RepoHealGitHubClient(installation_id).bootstrap_installation_metadata(
            repositories
        )
    except Exception as exc:
        logger.error(
            f"Metadata bootstrap failed for installation {installation_id}: {exc}"
        )


def queue_repository_analyses(
    background_tasks: BackgroundTasks,
    repositories: list[dict]
) -> list[str]:
    """Queue installation-triggered analyses and skip recent or active work."""
    queued = []
    for repository in repositories:
        full_name = repository.get("full_name")
        if not full_name or "/" not in full_name:
            continue

        repo_owner, repo_name = full_name.split("/", 1)
        job_id = create_job(repo_owner, repo_name, skip_if_recent=True)
        if not job_id:
            logger.info(f"Skipped recent or active analysis for {full_name}")
            continue

        background_tasks.add_task(
            run_analysis_in_background,
            job_id,
            repo_owner,
            repo_name
        )
        queued.append(full_name)
        logger.info(f"Queued analysis for {full_name}")

    return queued


def _repositories_for_uninstall(
    installation_id: int,
    payload_repositories: list[dict]
) -> list[dict]:
    stored_repositories = list_installed_repositories_for_installation(
        installation_id
    )
    if stored_repositories:
        return stored_repositories
    return payload_repositories


def _cleanup_mongodb_state(repo_owner: str, repo_name: str) -> None:
    """Remove MongoDB tracking documents for the uninstalled repository."""
    try:
        db = get_mongo_db()
        db.repository_analysis_status.delete_one({
            "repo_owner": repo_owner,
            "repo_name": repo_name
        })
    except Exception as exc:
        logger.error(
            f"MongoDB status cleanup failed for {repo_owner}/{repo_name}: {exc}"
        )


def cleanup_uninstalled_repositories(
    installation_id: int,
    repositories: list[dict]
) -> None:
    github_client = None
    try:
        github_client = RepoHealGitHubClient(installation_id)
    except Exception as exc:
        logger.warning(
            f"Could not initialize GitHub client for uninstall metadata update "
            f"{installation_id}: {exc}"
        )

    for repository in repositories:
        full_name = repository.get("full_name")
        if not full_name or "/" not in full_name:
            continue

        repo_owner, repo_name = full_name.split("/", 1)
        repo_id = f"{repo_owner}/{repo_name}"

        # 1. Cancel active background jobs
        try:
            cancel_repository_jobs(repo_owner, repo_name)
        except Exception as exc:
            logger.error(f"Job uninstall cleanup failed for {repo_id}: {exc}")

        # 2. Clear Neo4j graph (repository + all its nodes/edges)
        try:
            Neo4jGraphBuilder().clear_repository_graph(repo_id)
        except Exception as exc:
            logger.error(f"Neo4j uninstall cleanup failed for {repo_id}: {exc}")

        # 3. Remove local file cache
        try:
            shutil.rmtree(get_repo_cache_path(repo_owner, repo_name), ignore_errors=True)
        except Exception as exc:
            logger.error(f"Cache uninstall cleanup failed for {repo_id}: {exc}")

        # 4. Remove MongoDB tracking documents
        _cleanup_mongodb_state(repo_owner, repo_name)

        # 5. Mark metadata branch as uninstalled (preserves artifacts)
        if github_client:
            try:
                repo = github_client.get_repo(repo_id)
                MetadataBranchManager(github_client).mark_uninstalled(
                    repo,
                    installation_id
                )
            except Exception as exc:
                logger.warning(
                    f"Metadata branch uninstall marker skipped for {repo_id}: {exc}"
                )
