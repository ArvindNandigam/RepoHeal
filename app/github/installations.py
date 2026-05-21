import requests

from app.github.auth import (
    generate_jwt
)

from app.utils.logger import (
    get_logger
)

logger = get_logger(__name__)


def get_repository_installation(
    repo_owner,
    repo_name
):

    """
    Returns GitHub App installation
    for repository.

    Raises exception if app is not installed.
    """

    jwt_token = generate_jwt()

    headers = {
        "Authorization": (
            f"Bearer {jwt_token}"
        ),
        "Accept": (
            "application/vnd.github+json"
        ),
        "X-GitHub-Api-Version": (
            "2022-11-28"
        )
    }

    url = (
        f"https://api.github.com/repos/"
        f"{repo_owner}/{repo_name}"
        f"/installation"
    )

    response = requests.get(
        url,
        headers=headers
    )

    if response.status_code == 404:

        logger.warning(
            f"RepoHeal not installed on "
            f"{repo_owner}/{repo_name}"
        )

        return None

    response.raise_for_status()

    installation = response.json()

    logger.info(
        f"Installation found for "
        f"{repo_owner}/{repo_name}"
    )

    return installation