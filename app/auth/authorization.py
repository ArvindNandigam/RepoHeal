import requests

from fastapi import (
    HTTPException
)

from app.utils.logger import (
    get_logger
)

logger = get_logger(__name__)


def verify_repository_access(
    github_token: str,
    repo_owner: str,
    repo_name: str
):

    url = (
        f"https://api.github.com/repos/"
        f"{repo_owner}/{repo_name}"
    )

    response = requests.get(
        url,
        headers={
            "Authorization":
                f"Bearer {github_token}",
            "Accept":
                "application/vnd.github+json"
        }
    )

    if response.status_code == 401:

        logger.warning(
            "GitHub session expired while "
            f"accessing {repo_owner}/{repo_name}"
        )

        raise HTTPException(
            status_code=401,
            detail=(
                "GitHub session expired. "
                "Please log in again."
            )
        )

    if response.status_code == 404:

        logger.warning(
            f"Unauthorized access attempt "
            f"to {repo_owner}/{repo_name}"
        )

        raise HTTPException(
            status_code=403,
            detail=(
                "You do not have access "
                "to this repository"
            )
        )

    if response.status_code != 200:

        logger.error(
            f"GitHub authorization failed: "
            f"{response.text}"
        )

        raise HTTPException(
            status_code=500,
            detail="GitHub authorization failed"
        )

    repo_data = response.json()

    logger.info(
        f"Access verified for "
        f"{repo_data['full_name']}"
    )

    return repo_data