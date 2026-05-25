"""Graph visualization API for semantic repository intelligence."""

from typing import Any, Dict, List

from app.analysis.package_normalization import normalize_package_name
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GraphVisualizer:

    def __init__(self, analysis: Dict):
        self.analysis = analysis

    def _get_import_files(self) -> Dict[str, Dict[str, List[str]]]:
        imports = self.analysis.get("imports", {})

        if isinstance(imports, dict):
            return imports.get("files", {})

        return {}

    def _get_semantic_files(self) -> Dict[str, Dict[str, Any]]:
        semantic_graph = self.analysis.get("semantic_graph", {})

        if isinstance(semantic_graph, dict):
            return semantic_graph.get("files", {})

        return {}

    def _get_dependency_graph(self) -> Dict[str, Dict[str, Any]]:
        return self.analysis.get("dependency_graph", {})

    def to_cytoscape_format(self, repo_id: str) -> Dict:
        nodes = []
        edges = []

        import_files = self._get_import_files()
        semantic_files = self._get_semantic_files()
        dependency_graph = self._get_dependency_graph()

        function_ids = {}
        class_ids = {}

        nodes.append(
            {
                "data": {
                    "id": repo_id,
                    "label": repo_id,
                    "type": "repository"
                }
            }
        )

        for file_path, imports in import_files.items():
            file_node_id = f"file_{file_path}"

            nodes.append(
                {
                    "data": {
                        "id": file_node_id,
                        "label": file_path.split("/")[-1],
                        "type": "file",
                        "path": file_path,
                        "imports": len(imports.get("normalized", []))
                    }
                }
            )

            edges.append(
                {
                    "data": {
                        "id": f"{repo_id}_contains_{file_path}",
                        "source": repo_id,
                        "target": file_node_id,
                        "relationship": "CONTAINS"
                    }
                }
            )

        package_colors = {
            "detected": "#cc3333",
            "local": "#9966ff",
            "stdlib": "#666666",
            "third-party": "#ff9900"
        }

        for package, details in dependency_graph.items():
            package_type = details.get("type", "detected")

            nodes.append(
                {
                    "data": {
                        "id": f"pkg_{package}",
                        "label": package,
                        "type": "package",
                        "package_type": package_type,
                        "version": details.get("version", "unknown"),
                        "status": details.get("status", "unknown"),
                        "color": package_colors.get(package_type, "#999999")
                    }
                }
            )

        for file_path, imports in import_files.items():
            file_node_id = f"file_{file_path}"

            for package in dict.fromkeys(imports.get("normalized", [])):
                if package not in dependency_graph:
                    continue

                edges.append(
                    {
                        "data": {
                            "id": f"{file_path}_imports_{package}",
                            "source": file_node_id,
                            "target": f"pkg_{package}",
                            "relationship": "IMPORTS"
                        }
                    }
                )

        for file_path, semantics in semantic_files.items():
            file_node_id = f"file_{file_path}"

            for function in semantics.get("functions", []):
                qualified_name = function.get("qualified_name") or function.get("name")
                function_id = f"func_{file_path}_{qualified_name}"
                function_ids[(file_path, qualified_name)] = function_id

                nodes.append(
                    {
                        "data": {
                            "id": function_id,
                            "label": function.get("name"),
                            "type": "function",
                            "path": file_path,
                            "qualified_name": qualified_name,
                            "line_start": function.get("line_start"),
                            "line_end": function.get("line_end"),
                            "is_async": function.get("is_async", False)
                        }
                    }
                )

                edges.append(
                    {
                        "data": {
                            "id": f"{file_path}_defines_{qualified_name}",
                            "source": file_node_id,
                            "target": function_id,
                            "relationship": "DEFINES"
                        }
                    }
                )

            for class_node in semantics.get("classes", []):
                qualified_name = class_node.get("qualified_name") or class_node.get("name")
                class_id = f"class_{file_path}_{qualified_name}"
                class_ids[(file_path, qualified_name)] = class_id

                nodes.append(
                    {
                        "data": {
                            "id": class_id,
                            "label": class_node.get("name"),
                            "type": "class",
                            "path": file_path,
                            "qualified_name": qualified_name,
                            "line_start": class_node.get("line_start"),
                            "line_end": class_node.get("line_end"),
                            "bases": class_node.get("bases", [])
                        }
                    }
                )

                edges.append(
                    {
                        "data": {
                            "id": f"{file_path}_defines_class_{qualified_name}",
                            "source": file_node_id,
                            "target": class_id,
                            "relationship": "DEFINES"
                        }
                    }
                )

            for api in semantics.get("apis", []):
                api_name = api.get("name")
                api_package = normalize_package_name(api.get("package"))
                api_id = f"api_{api_package}_{api_name}_{file_path}_{api.get('line')}"

                nodes.append(
                    {
                        "data": {
                            "id": api_id,
                            "label": api_name,
                            "type": "api",
                            "package": api_package,
                            "path": file_path,
                            "line": api.get("line")
                        }
                    }
                )

                function_id = function_ids.get((file_path, api.get("function")))

                if function_id:
                    edges.append(
                        {
                            "data": {
                                "id": f"{function_id}_uses_{api_id}",
                                "source": function_id,
                                "target": api_id,
                                "relationship": "USES_API"
                            }
                        }
                    )

            for call in semantics.get("calls", []):
                if call.get("is_external_api"):
                    continue

                caller_id = function_ids.get((file_path, call.get("function")))

                if not caller_id:
                    continue

                callee_name = (call.get("name") or "").split(".")[-1]

                for (candidate_file, candidate_name), callee_id in function_ids.items():
                    if candidate_name.split(".")[-1] != callee_name:
                        continue

                    if callee_id == caller_id:
                        continue

                    edges.append(
                        {
                            "data": {
                                "id": f"{caller_id}_calls_{callee_id}",
                                "source": caller_id,
                                "target": callee_id,
                                "relationship": "CALLS"
                            }
                        }
                    )

            for class_node in semantics.get("classes", []):
                class_id = class_ids.get(
                    (
                        file_path,
                        class_node.get("qualified_name") or class_node.get("name")
                    )
                )

                if not class_id:
                    continue

                for base in class_node.get("bases", []):
                    base_name = base.split(".")[-1]

                    for (candidate_file, candidate_name), parent_id in class_ids.items():
                        if candidate_name.split(".")[-1] != base_name:
                            continue

                        if parent_id == class_id:
                            continue

                        edges.append(
                            {
                                "data": {
                                    "id": f"{class_id}_inherits_{parent_id}",
                                    "source": class_id,
                                    "target": parent_id,
                                    "relationship": "INHERITS"
                                }
                            }
                        )

        logger.info(f"Cytoscape graph generated for {repo_id}")

        return {
            "nodes": nodes,
            "edges": edges
        }

    def get_statistics(self) -> Dict:
        import_files = self._get_import_files()
        semantic_files = self._get_semantic_files()
        dependency_graph = self._get_dependency_graph()
        issues = self.analysis.get("issues", {})

        imports_summary = self.analysis.get("imports", {}).get("summary", {})
        semantic_summary = self.analysis.get("semantic_graph", {}).get("summary", {})

        return {
            "repository_stats": {
                "total_files": len(import_files),
                "total_imports": imports_summary.get("total_imports", 0),
                "total_functions": semantic_summary.get("total_functions", 0),
                "total_classes": semantic_summary.get("total_classes", 0),
                "total_api_calls": semantic_summary.get("total_api_calls", 0)
            },
            "dependency_stats": {
                "declared_packages": self.analysis.get("dependencies", {}).get("count", 0),
                "tracked_packages": len(dependency_graph),
                "missing_dependencies": issues.get("missing_count", 0),
                "unused_dependencies": issues.get("unused_count", 0)
            },
            "semantic_stats": {
                "files_with_semantics": len(semantic_files),
                "total_calls": semantic_summary.get("total_calls", 0)
            },
            "issues": {
                "missing": issues.get("missing_dependencies", [])[:10],
                "unused": issues.get("unused_dependencies", [])[:10]
            }
        }

    def get_module_details(self, module_path: str) -> Dict:
        import_files = self._get_import_files()
        semantic_files = self._get_semantic_files()

        if module_path not in import_files:
            return {
                "error": f"File not found: {module_path}"
            }

        module_imports = import_files[module_path]
        module_semantics = semantic_files.get(
            module_path,
            {
                "functions": [],
                "classes": [],
                "calls": [],
                "apis": []
            }
        )

        all_imports = list(dict.fromkeys(
            module_imports.get("normalized", [])
        ))

        dependency_graph = self._get_dependency_graph()

        return {
            "path": module_path,
            "imports": {
                "direct": module_imports.get("direct", []),
                "from": module_imports.get("from", []),
                "normalized": module_imports.get("normalized", [])
            },
            "functions": module_semantics.get("functions", []),
            "classes": module_semantics.get("classes", []),
            "third_party_packages": [
                imp for imp in all_imports if imp in dependency_graph
            ],
            "local_imports": [
                imp for imp in all_imports if imp not in dependency_graph
            ]
        }

    def get_package_impact(self, package: str) -> Dict:
        normalized_package = normalize_package_name(package)
        dependent_files = []

        import_files = self._get_import_files()

        for file_path, imports in import_files.items():
            all_imports = list(dict.fromkeys(imports.get("normalized", [])))

            if normalized_package in all_imports:
                dependent_files.append(file_path)

        package_data = self._get_dependency_graph().get(
            normalized_package,
            {}
        )

        return {
            "package": normalized_package,
            "package_data": package_data,
            "dependent_modules": dependent_files,
            "impact_count": len(dependent_files)
        }


def visualize_repository(repo_id: str, analysis: Dict) -> Dict:
    visualizer = GraphVisualizer(analysis)

    return {
        "cytoscape": visualizer.to_cytoscape_format(repo_id),
        "statistics": visualizer.get_statistics()
    }
