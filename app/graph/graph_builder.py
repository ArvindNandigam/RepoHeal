from app.graph.connection import neo4j_connection

from app.utils.logger import get_logger

logger = get_logger(__name__)


class Neo4jGraphBuilder:

    def build_graph(
        self,
        repo_id,
        analysis
    ):

        import_files = (
            analysis
            .get("imports", {})
            .get("files", {})
        )

        dependency_graph = (
            analysis
            .get("dependency_graph", {})
        )

        with neo4j_connection.get_session() as session:

            logger.info(
                f"Building Neo4j graph for {repo_id}"
            )

            # Repository node
            session.run(
                """
                MERGE (r:Repository {id: $repo_id})

                SET r.updated_at = timestamp()
                """,
                repo_id=repo_id
            )

            # Create module nodes
            for module_path, imports in import_files.items():

                module_id = (
                    f"{repo_id}:{module_path}"
                )

                session.run(
                    """
                    MERGE (m:Module {
                        id: $module_id
                    })

                    SET
                        m.path = $module_path,
                        m.updated_at = timestamp()
                    """,
                    module_id=module_id,
                    module_path=module_path
                )

                # Repository contains module
                session.run(
                    """
                    MATCH (r:Repository {
                        id: $repo_id
                    })

                    MATCH (m:Module {
                        id: $module_id
                    })

                    MERGE (r)-[:CONTAINS]->(m)
                    """,
                    repo_id=repo_id,
                    module_id=module_id
                )

                # Normalize imports
                all_imports = list(dict.fromkeys(
                    imports.get("direct", [])
                    + imports.get("from", [])
                ))

                for imported_package in all_imports:

                    dependency_info = (
                        dependency_graph.get(
                            imported_package,
                            {}
                        )
                    )

                    package_type = (
                        dependency_info.get(
                            "type",
                            "detected"
                        )
                    )

                    package_version = (
                        dependency_info.get(
                            "version",
                            "unknown"
                        )
                    )

                    package_status = (
                        dependency_info.get(
                            "status",
                            "unknown"
                        )
                    )

                    # Package node
                    session.run(
                        """
                        MERGE (p:Package {
                            name: $package_name
                        })

                        SET
                            p.type = $package_type,
                            p.version = $package_version,
                            p.status = $package_status,
                            p.updated_at = timestamp()
                        """,
                        package_name=imported_package,
                        package_type=package_type,
                        package_version=package_version,
                        package_status=package_status
                    )

                    # Module imports package
                    session.run(
                        """
                        MATCH (m:Module {
                            id: $module_id
                        })

                        MATCH (p:Package {
                            name: $package_name
                        })

                        MERGE (m)-[:IMPORTS]->(p)
                        """,
                        module_id=module_id,
                        package_name=imported_package
                    )

            logger.info(
                f"Neo4j graph built successfully "
                f"for {repo_id}"
            )

    def clear_repository_graph(
        self,
        repo_id
    ):

        with neo4j_connection.get_session() as session:

            logger.info(
                f"Clearing graph for {repo_id}"
            )

            session.run(
                """
                MATCH (r:Repository {
                    id: $repo_id
                })

                OPTIONAL MATCH
                    (r)-[:CONTAINS]->
                    (m:Module)

                OPTIONAL MATCH
                    (m)-[:IMPORTS]->
                    (p:Package)

                DETACH DELETE r, m
                """,
                repo_id=repo_id
            )

            session.run(
                """
                MATCH (p:Package)
                WHERE NOT ()-[:IMPORTS]->(p)
                DELETE p
                """
            )

            logger.info(
                f"Graph cleared for {repo_id}"
            )