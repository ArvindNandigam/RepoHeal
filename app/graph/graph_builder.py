from collections import defaultdict

from app.analysis.package_normalization import normalize_package_name
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

        semantic_files = (
            analysis
            .get("semantic_graph", {})
            .get("files", {})
        )

        dependency_graph = (
            analysis
            .get("dependency_graph", {})
        )

        file_node_ids = {}
        function_node_ids = {}
        class_node_ids = {}
        function_name_index = defaultdict(list)
        class_name_index = defaultdict(list)

        with neo4j_connection.get_session() as session:

            logger.info(
                f"Building Neo4j graph for {repo_id}"
            )

            session.run(
                """
                MERGE (r:Repository {id: $repo_id})

                SET r.updated_at = timestamp()
                """,
                repo_id=repo_id
            )

            for file_path, imports in import_files.items():

                file_id = f"{repo_id}:file:{file_path}"
                file_node_ids[file_path] = file_id

                session.run(
                    """
                    MERGE (f:File {
                        id: $file_id,
                        repo_id: $repo_id
                    })

                    SET
                        f.path = $file_path,
                        f.updated_at = timestamp()
                    """,
                    file_id=file_id,
                    repo_id=repo_id,
                    file_path=file_path
                )

                session.run(
                    """
                    MATCH (r:Repository {id: $repo_id})
                    MATCH (f:File {id: $file_id})
                    MERGE (r)-[:CONTAINS]->(f)
                    """,
                    repo_id=repo_id,
                    file_id=file_id
                )

                for imported_package in dict.fromkeys(
                    imports.get("normalized", [])
                ):

                    if not imported_package:
                        continue

                    dependency_info = dependency_graph.get(
                        normalize_package_name(imported_package),
                        {}
                    )

                    session.run(
                        """
                        MERGE (p:Package {
                            repo_id: $repo_id,
                            name: $package_name
                        })

                        SET
                            p.type = $package_type,
                            p.version = $package_version,
                            p.status = $package_status,
                            p.updated_at = timestamp()
                        """,
                        repo_id=repo_id,
                        package_name=imported_package,
                        package_type=dependency_info.get("type", "detected"),
                        package_version=dependency_info.get("version", "unknown"),
                        package_status=dependency_info.get("status", "unknown")
                    )

                    session.run(
                        """
                        MATCH (f:File {id: $file_id})
                        MATCH (p:Package {
                            repo_id: $repo_id,
                            name: $package_name
                        })

                        MERGE (f)-[:IMPORTS]->(p)
                        """,
                        repo_id=repo_id,
                        file_id=file_id,
                        package_name=imported_package
                    )

            for file_path, semantics in semantic_files.items():

                file_id = file_node_ids.get(file_path)

                if not file_id:
                    continue

                for function in semantics.get("functions", []):

                    qualified_name = (
                        function.get("qualified_name")
                        or function.get("name")
                    )
                    function_id = f"{file_id}:function:{qualified_name}"

                    function_node_ids[(file_path, qualified_name)] = function_id
                    function_name_index[function.get("name")].append(function_id)

                    session.run(
                        """
                        MERGE (fn:Function {
                            id: $function_id,
                            repo_id: $repo_id
                        })

                        SET
                            fn.name = $function_name,
                            fn.qualified_name = $qualified_name,
                            fn.file_path = $file_path,
                            fn.line_start = $line_start,
                            fn.line_end = $line_end,
                            fn.is_async = $is_async,
                            fn.updated_at = timestamp()
                        """,
                        function_id=function_id,
                        repo_id=repo_id,
                        function_name=function.get("name"),
                        qualified_name=qualified_name,
                        file_path=file_path,
                        line_start=function.get("line_start"),
                        line_end=function.get("line_end"),
                        is_async=function.get("is_async", False)
                    )

                    session.run(
                        """
                        MATCH (f:File {id: $file_id})
                        MATCH (fn:Function {id: $function_id})
                        MERGE (f)-[:DEFINES]->(fn)
                        """,
                        file_id=file_id,
                        function_id=function_id
                    )

                for class_node in semantics.get("classes", []):

                    qualified_name = (
                        class_node.get("qualified_name")
                        or class_node.get("name")
                    )
                    class_id = f"{file_id}:class:{qualified_name}"

                    class_node_ids[(file_path, qualified_name)] = class_id
                    class_name_index[class_node.get("name")].append(class_id)

                    session.run(
                        """
                        MERGE (cls:Class {
                            id: $class_id,
                            repo_id: $repo_id
                        })

                        SET
                            cls.name = $class_name,
                            cls.qualified_name = $qualified_name,
                            cls.file_path = $file_path,
                            cls.line_start = $line_start,
                            cls.line_end = $line_end,
                            cls.bases = $bases,
                            cls.updated_at = timestamp()
                        """,
                        class_id=class_id,
                        repo_id=repo_id,
                        class_name=class_node.get("name"),
                        qualified_name=qualified_name,
                        file_path=file_path,
                        line_start=class_node.get("line_start"),
                        line_end=class_node.get("line_end"),
                        bases=class_node.get("bases", [])
                    )

                    session.run(
                        """
                        MATCH (f:File {id: $file_id})
                        MATCH (cls:Class {id: $class_id})
                        MERGE (f)-[:DEFINES]->(cls)
                        """,
                        file_id=file_id,
                        class_id=class_id
                    )

            for file_path, semantics in semantic_files.items():

                file_id = file_node_ids.get(file_path)

                if not file_id:
                    continue

                for api in semantics.get("apis", []):

                    api_name = api.get("name")
                    api_package = normalize_package_name(
                        api.get("package")
                    )
                    api_id = f"{repo_id}:api:{api_package}:{api_name}:{file_path}:{api.get('line')}"

                    session.run(
                        """
                        MERGE (a:API {
                            id: $api_id,
                            repo_id: $repo_id
                        })

                        SET
                            a.name = $api_name,
                            a.package = $api_package,
                            a.file_path = $file_path,
                            a.line = $line,
                            a.updated_at = timestamp()
                        """,
                        api_id=api_id,
                        repo_id=repo_id,
                        api_name=api_name,
                        api_package=api_package,
                        file_path=file_path,
                        line=api.get("line")
                    )

                    function_id = function_node_ids.get(
                        (file_path, api.get("function"))
                    )

                    if function_id:

                        session.run(
                            """
                            MATCH (fn:Function {id: $function_id})
                            MATCH (a:API {id: $api_id})
                            MERGE (fn)-[:USES_API]->(a)
                            """,
                            function_id=function_id,
                            api_id=api_id
                        )

                for call in semantics.get("calls", []):

                    if call.get("is_external_api"):
                        continue

                    caller_id = function_node_ids.get(
                        (file_path, call.get("function"))
                    )

                    if not caller_id:
                        continue

                    call_name = call.get("name") or ""
                    simple_name = call_name.split(".")[-1]

                    for callee_id in function_name_index.get(simple_name, []):

                        if callee_id == caller_id:
                            continue

                        session.run(
                            """
                            MATCH (caller:Function {id: $caller_id})
                            MATCH (callee:Function {id: $callee_id})
                            MERGE (caller)-[:CALLS]->(callee)
                            """,
                            caller_id=caller_id,
                            callee_id=callee_id
                        )

                for class_node in semantics.get("classes", []):

                    class_id = class_node_ids.get(
                        (file_path, class_node.get("qualified_name") or class_node.get("name"))
                    )

                    if not class_id:
                        continue

                    for base in class_node.get("bases", []):

                        base_name = base.split(".")[-1]

                        for parent_id in class_name_index.get(base_name, []):

                            if parent_id == class_id:
                                continue

                            session.run(
                                """
                                MATCH (child:Class {id: $class_id})
                                MATCH (parent:Class {id: $parent_id})
                                MERGE (child)-[:INHERITS]->(parent)
                                """,
                                class_id=class_id,
                                parent_id=parent_id
                            )

            logger.info(
                f"Neo4j graph built successfully for {repo_id}"
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
                MATCH (n)
                WHERE n.repo_id = $repo_id
                DETACH DELETE n
                """,
                repo_id=repo_id
            )

            session.run(
                """
                MATCH (r:Repository {id: $repo_id})
                DETACH DELETE r
                """,
                repo_id=repo_id
            )

            logger.info(
                f"Graph cleared for {repo_id}"
            )