"""
Graph visualization API.

Converts repository intelligence into
Cytoscape.js-compatible graph structures.
"""

from typing import Dict, List, Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


class GraphVisualizer:

    def __init__(self, analysis: Dict):

        self.analysis = analysis

    def _get_import_files(
        self
    ) -> Dict[str, Dict[str, List[str]]]:

        imports = self.analysis.get(
            "imports",
            {}
        )

        if (
            isinstance(imports, dict)
            and "files" in imports
        ):

            return imports.get(
                "files",
                {}
            )

        return {}

    def _get_dependency_graph(
        self
    ) -> Dict[str, Dict[str, Any]]:

        dependency_graph = (
            self.analysis.get(
                "dependency_graph",
                {}
            )
        )

        return dependency_graph

    def to_cytoscape_format(
        self,
        repo_id: str
    ) -> Dict:

        nodes = []
        edges = []

        import_files = self._get_import_files()

        dependency_graph = (
            self._get_dependency_graph()
        )

        # Repository node
        nodes.append({
            "data": {
                "id": repo_id,
                "label": repo_id,
                "type": "repository"
            }
        })

        # Module nodes
        for file_path, imports in import_files.items():

            module_node_id = (
                f"module_{file_path}"
            )

            all_imports = list(dict.fromkeys(
                imports.get("direct", [])
                + imports.get("from", [])
            ))

            nodes.append({
                "data": {
                    "id": module_node_id,
                    "label": file_path.split("/")[-1],
                    "type": "module",
                    "path": file_path,
                    "imports": len(all_imports)
                }
            })

            edges.append({
                "data": {
                    "id": (
                        f"{repo_id}_contains_"
                        f"{file_path}"
                    ),
                    "source": repo_id,
                    "target": module_node_id,
                    "relationship": "CONTAINS"
                }
            })

        # Package nodes
        package_colors = {
            "third-party": "#ff9900",
            "stdlib": "#666666",
            "local": "#9966ff",
            "detected": "#cc3333"
        }

        for package, details in (
            dependency_graph.items()
        ):

            package_type = details.get(
                "type",
                "detected"
            )

            nodes.append({
                "data": {
                    "id": f"pkg_{package}",
                    "label": package,
                    "type": "package",
                    "package_type": package_type,
                    "version": details.get(
                        "version",
                        "unknown"
                    ),
                    "status": details.get(
                        "status",
                        "unknown"
                    ),
                    "color": package_colors.get(
                        package_type,
                        "#999999"
                    )
                }
            })

        # Import edges
        for file_path, imports in import_files.items():

            module_node_id = (
                f"module_{file_path}"
            )

            all_imports = list(dict.fromkeys(
                imports.get("direct", [])
                + imports.get("from", [])
            ))

            for package in all_imports:

                if package in dependency_graph:

                    edges.append({
                        "data": {
                            "id": (
                                f"{file_path}_"
                                f"imports_"
                                f"{package}"
                            ),
                            "source": module_node_id,
                            "target": f"pkg_{package}",
                            "relationship": "IMPORTS"
                        }
                    })

        logger.info(
            f"Cytoscape graph generated "
            f"for {repo_id}"
        )

        return {
            "nodes": nodes,
            "edges": edges
        }

    def get_statistics(
        self
    ) -> Dict:

        import_files = (
            self._get_import_files()
        )

        imports_summary = (
            self.analysis
            .get("imports", {})
            .get("summary", {})
        )

        dependency_graph = (
            self._get_dependency_graph()
        )

        issues = (
            self.analysis.get(
                "issues",
                {}
            )
        )

        total_imports = (
            imports_summary.get(
                "total_imports",
                0
            )
        )

        return {
            "repository_stats": {
                "total_modules": len(import_files),
                "total_imports": total_imports,
                "third_party_packages": len(
                    dependency_graph
                ),
                "local_modules": (
                    imports_summary.get(
                        "local_packages",
                        0
                    )
                )
            },
            "dependency_stats": {
                "declared_packages": (
                    self.analysis
                    .get("dependencies", {})
                    .get("count", 0)
                ),
                "missing_dependencies": (
                    issues.get(
                        "missing_count",
                        0
                    )
                ),
                "unused_dependencies": (
                    issues.get(
                        "unused_count",
                        0
                    )
                )
            },
            "issues": {
                "missing": issues.get(
                    "missing_dependencies",
                    []
                )[:10],
                "unused": issues.get(
                    "unused_dependencies",
                    []
                )[:10]
            }
        }

    def get_module_details(
        self,
        module_path: str
    ) -> Dict:

        import_files = (
            self._get_import_files()
        )

        if module_path not in import_files:

            return {
                "error": (
                    f"Module not found: "
                    f"{module_path}"
                )
            }

        module_imports = (
            import_files[module_path]
        )

        all_imports = list(dict.fromkeys(
            module_imports.get("direct", [])
            + module_imports.get("from", [])
        ))

        dependency_graph = (
            self._get_dependency_graph()
        )

        return {
            "path": module_path,
            "imports": {
                "direct": module_imports.get(
                    "direct",
                    []
                ),
                "from": module_imports.get(
                    "from",
                    []
                )
            },
            "third_party_packages": [
                imp
                for imp in all_imports
                if imp in dependency_graph
            ],
            "local_imports": [
                imp
                for imp in all_imports
                if imp.startswith(".")
            ]
        }

    def get_package_impact(
        self,
        package: str
    ) -> Dict:

        dependent_modules = []

        import_files = (
            self._get_import_files()
        )

        dependency_graph = (
            self._get_dependency_graph()
        )

        for file_path, imports in (
            import_files.items()
        ):

            all_imports = list(dict.fromkeys(
                imports.get("direct", [])
                + imports.get("from", [])
            ))

            if package in all_imports:

                dependent_modules.append(
                    file_path
                )

        impact_score = len(
            dependent_modules
        )

        return {
            "package": package,
            "version": (
                dependency_graph
                .get(package, {})
                .get("version")
            ),
            "dependent_modules": (
                dependent_modules
            ),
            "impact_score": impact_score,
            "risk_level": (
                self._assess_risk(
                    impact_score
                )
            )
        }

    def _assess_risk(
        self,
        impact: int
    ) -> str:

        if impact > 10:
            return "critical"

        if impact > 5:
            return "high"

        if impact > 2:
            return "medium"

        return "low"


def visualize_repository(
    repo_id: str,
    analysis: Dict
) -> Dict:

    visualizer = GraphVisualizer(
        analysis
    )

    return {
        "cytoscape": (
            visualizer.to_cytoscape_format(
                repo_id
            )
        ),
        "statistics": (
            visualizer.get_statistics()
        )
    }