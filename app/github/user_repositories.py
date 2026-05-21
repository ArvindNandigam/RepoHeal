import requests

from app.utils.logger import (
    get_logger
)

logger = get_logger(__name__)


def fetch_user_repositories(
    github_token: str
):

    repositories = []

    page = 1

    while True:

        response = requests.get(
            "https://api.github.com/user/repos",
            headers={
                "Authorization":
                    f"Bearer {github_token}",
                "Accept":
                    "application/vnd.github+json"
            },
            params={
                "per_page": 100,
                "page": page
            },
            timeout=15
        )

        response.raise_for_status()

        repos = response.json()

        if not repos:
            break

        repositories.extend(repos)

        page += 1

    logger.info(
        f"Fetched {len(repositories)} repositories"
    )

    return repositories
