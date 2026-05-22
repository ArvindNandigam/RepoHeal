import requests

from app.utils.logger import (
    get_logger
)

logger = get_logger(__name__)


def fetch_repoheal_installed_repositories(
    github_token: str
):

    repositories = []
    seen_repository_ids = set()
    page = 1

    while True:

        installations_response = requests.get(
            "https://api.github.com/user/installations",
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

        installations_response.raise_for_status()

        installations = installations_response.json()

        if not installations:
            break

        for installation in installations:

            installation_id = installation["id"]
            repositories_page = 1

            while True:

                repository_response = requests.get(
                    (
                        "https://api.github.com/user/installations/"
                        f"{installation_id}/repositories"
                    ),
                    headers={
                        "Authorization":
                            f"Bearer {github_token}",
                        "Accept":
                            "application/vnd.github+json"
                    },
                    params={
                        "per_page": 100,
                        "page": repositories_page
                    },
                    timeout=15
                )

                repository_response.raise_for_status()

                installed_repositories = repository_response.json().get(
                    "repositories",
                    []
                )

                if not installed_repositories:
                    break

                for repository in installed_repositories:

                    repository_id = repository.get("id")

                    if repository_id in seen_repository_ids:
                        continue

                    seen_repository_ids.add(repository_id)
                    repositories.append(repository)

                repositories_page += 1

        page += 1

    logger.info(
        f"Fetched {len(repositories)} RepoHeal-installed repositories"
    )

    return repositories