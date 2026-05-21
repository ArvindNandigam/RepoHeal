import requests

from app.utils.logger import (
    get_logger
)

logger = get_logger(__name__)


def fetch_repoheal_installed_repositories(
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

        for repo in repos:

            owner_login = (
                repo["owner"]["login"]
            )
            repo_name = repo["name"]

            installation_response = requests.get(
                (
                    "https://api.github.com/repos/"
                    f"{owner_login}/{repo_name}/installation"
                ),
                headers={
                    "Authorization":
                        f"Bearer {github_token}",
                    "Accept":
                        "application/vnd.github+json"
                },
                timeout=15
            )

            if installation_response.status_code == 200:
                repositories.append(repo)
            elif installation_response.status_code == 404:
                continue
            else:
                installation_response.raise_for_status()

        page += 1

    logger.info(
        f"Fetched {len(repositories)} RepoHeal-installed repositories"
    )

    return repositories