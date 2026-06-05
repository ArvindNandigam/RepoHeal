from datetime import datetime
from fastapi import APIRouter, Request
from app.errors.exceptions import AuthenticationError, ExternalServiceError
from app.github.webhooks import verify_github_signature
from app.github.client import RepoHealGitHubClient
from app.github.installed_repositories import (
    upsert_installed_repositories,
    remove_installed_repositories
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])

@router.post("/github")
async def github_webhook(request: Request):
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
        bootstrapped_repositories = bootstrap_client.bootstrap_installation_metadata(installation_repositories)

        return {
            "received": True,
            "event": event_type,
            "action": event_action,
            "bootstrapped_repositories": bootstrapped_repositories,
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

        if repositories_removed:
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
