from datetime import datetime

from app.graph.connection import (
    neo4j_connection
)

from app.utils.logger import (
    get_logger
)

logger = get_logger(__name__)


def upsert_installed_repositories(
    installation_id: int,
    repositories: list[dict]
):

    installed_at = datetime.utcnow().isoformat()

    with neo4j_connection.get_session() as session:

        for repository in repositories:

            repo_id = repository.get("id")
            full_name = repository.get("full_name")

            if not repo_id or not full_name:
                continue

            owner_login = (
                repository.get("owner", {}).get("login")
            )

            session.run(
                """
                MERGE (r:InstalledRepository {
                    installation_id: $installation_id,
                    repo_id: $repo_id
                })

                SET
                    r.full_name = $full_name,
                    r.owner = $owner,
                    r.repo_name = $repo_name,
                    r.private = $private,
                    r.installed_at = coalesce(
                        r.installed_at,
                        $installed_at
                    ),
                    r.updated_at = timestamp()
                """,
                installation_id=installation_id,
                repo_id=repo_id,
                full_name=full_name,
                owner=owner_login,
                repo_name=repository.get("name"),
                private=repository.get("private", False),
                installed_at=installed_at
            )

    logger.info(
        f"Upserted {len(repositories)} installed repositories for installation {installation_id}"
    )


def remove_installed_repositories(
    installation_id: int,
    repository_ids: list[int] | None = None
):

    with neo4j_connection.get_session() as session:

        if repository_ids is not None:

            session.run(
                """
                MATCH (r:InstalledRepository)
                WHERE r.installation_id = $installation_id
                  AND r.repo_id IN $repository_ids
                DETACH DELETE r
                """,
                installation_id=installation_id,
                repository_ids=repository_ids
            )
        else:

            session.run(
                """
                MATCH (r:InstalledRepository)
                WHERE r.installation_id = $installation_id
                DETACH DELETE r
                """,
                installation_id=installation_id
            )

    logger.info(
        f"Removed installed repository records for installation {installation_id}"
    )


def get_installed_repositories() -> set[str]:

    with neo4j_connection.get_session() as session:

        result = session.run(
            """
            MATCH (r:InstalledRepository)
            WHERE r.full_name IS NOT NULL
            RETURN DISTINCT r.full_name AS full_name
            ORDER BY full_name
            """
        )

        repositories = {
            record["full_name"]
            for record in result
            if record["full_name"]
        }

    logger.info(
        f"Loaded {len(repositories)} installed repositories from Neo4j"
    )

    return repositories


def fetch_repoheal_installed_repositories() -> set[str]:

    return get_installed_repositories()