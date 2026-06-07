from app.graph.connection import neo4j_connection


class Neo4jGraphVisualizer:

    @staticmethod
    def to_cytoscape_format(repo_id: str):

        nodes = []
        edges = []

        with neo4j_connection.get_session() as session:

            node_result = session.run(
                """
                MATCH (n)
                WHERE n.repo_id = $repo_id
                   OR (n:Repository AND n.id = $repo_id)
                RETURN n
                """,
                repo_id=repo_id
            )

            for record in node_result:

                node = record["n"]

                labels = list(node.labels)

                node_type = labels[0] if labels else "Unknown"

                node_id = (
                    node.get("id")
                    or node.get("name")
                    or str(hash(str(dict(node))))
                )

                nodes.append(
                    {
                        "data": {
                            "id": node_id,
                            "label": node.get("name", node_id),
                            "type": node_type.lower(),
                            "kind": node_type,
                            "view_level": 0 if node_type in {"Repository", "File", "Package"} else 1,
                            **dict(node)
                        }
                    }
                )

            edge_result = session.run(
                """
                MATCH (a)-[r]->(b)
                WHERE (
                    a.repo_id = $repo_id
                    OR (a:Repository AND a.id = $repo_id)
                )
                AND (
                    b.repo_id = $repo_id
                    OR (b:Repository AND b.id = $repo_id)
                )
                RETURN
                    a,
                    b,
                    type(r) AS rel
                """,
                repo_id=repo_id
            )

            for record in edge_result:

                source = record["a"]
                target = record["b"]

                source_id = (
                    source.get("id")
                    or source.get("name")
                )

                target_id = (
                    target.get("id")
                    or target.get("name")
                )

                if not source_id or not target_id:
                    continue

                edges.append(
                    {
                        "data": {
                            "id": f"{source_id}->{target_id}",
                            "source": source_id,
                            "target": target_id,
                            "relationship": record["rel"],
                            "view_level": 0 if record["rel"] == "IMPORTS" else 1
                        }
                    }
                )

        return {
            "nodes": nodes,
            "edges": edges
        }
