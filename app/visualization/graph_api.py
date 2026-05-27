"""Graph visualization API for semantic repository intelligence."""

from typing import Any, Dict, List

from app.analysis.package_normalization import (
    build_namespace_hierarchy,
    normalize_package_name
)
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

    def _node_view_level(self, node_type: str) -> int:
        if node_type in {"repository", "file", "package", "module"}:
            return 0

        return 1

    def _edge_view_level(
        self,
        relationship: str,
        source_type: str,
        target_type: str
    ) -> int:
        relationship = (relationship or "").upper()

        if relationship == "CONTAINS":
            return 0

        if relationship == "IMPORTS":
            if source_type in {"file", "repository"} and target_type in {"package", "module"}:
                return 0

            return 1

        return 1

    def _build_function_library_map(self) -> Dict[tuple, List[str]]:
        semantic_files = self._get_semantic_files()
        function_libraries = {}

        for file_path, semantics in semantic_files.items():
            api_by_function = {}

            for api in semantics.get("apis", []):
                function_name = api.get("function")

                if not function_name:
                    continue

                api_by_function.setdefault(function_name, []).append(api.get("package"))

            for function in semantics.get("functions", []):
                qualified_name = function.get("qualified_name") or function.get("name")
                libraries = list(
                    dict.fromkeys(
                        [
                            library
                            for library in api_by_function.get(qualified_name, [])
                            if library
                        ]
                    )
                )

                if libraries:
                    function_libraries[(file_path, qualified_name)] = libraries

        return function_libraries

    def _get_hierarchical_imports(self, imports: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        hierarchical_imports = imports.get("hierarchical", [])

        if hierarchical_imports:
            return hierarchical_imports

        fallback_imports = []

        for package in dict.fromkeys(imports.get("normalized", [])):
            fallback_imports.append(
                {
                    "source": "import",
                    "module": package,
                    "symbol": None,
                    "root": normalize_package_name(package),
                    "is_local": False,
                    **build_namespace_hierarchy(package)
                }
            )

        return fallback_imports

    def to_cytoscape_format(self, repo_id: str) -> Dict:
        nodes = []
        edges = []

        import_files = self._get_import_files()
        semantic_files = self._get_semantic_files()
        dependency_graph = self._get_dependency_graph()
        function_library_map = self._build_function_library_map()
        namespace_usage_counts = {}

        function_ids = {}
        class_ids = {}
        namespace_ids = {}
        node_index = {}
        node_types = {}

        nodes.append(
            {
                "data": {
                    "id": repo_id,
                    "label": repo_id,
                    "type": "repository",
                    "repo_id": repo_id,
                    "parent": None,
                    "usage_count": 0,
                    "module_path": repo_id,
                    "leaf_path": repo_id,
                    "view_level": self._node_view_level("repository")
                }
            }
        )
        node_types[repo_id] = "repository"

        for file_path, imports in import_files.items():
            file_node_id = f"file_{file_path}"

            hierarchical_imports = self._get_hierarchical_imports(imports)

            for import_record in hierarchical_imports:
                for namespace_node in import_record.get("nodes", []):
                    namespace_path = namespace_node.get("path")

                    if namespace_path:
                        namespace_usage_counts[namespace_path] = namespace_usage_counts.get(namespace_path, 0) + 1

            nodes.append(
                {
                    "data": {
                        "id": file_node_id,
                        "label": file_path.split("/")[-1],
                        "type": "file",
                        "path": file_path,
                        "imports": len(hierarchical_imports),
                        "repo_id": repo_id,
                        "parent": repo_id,
                        "scope": "repository",
                        "view_level": self._node_view_level("file")
                    }
                }
            )
            node_types[file_node_id] = "file"

            edges.append(
                {
                    "data": {
                        "id": f"{repo_id}_contains_{file_path}",
                        "source": repo_id,
                        "target": file_node_id,
                        "relationship": "CONTAINS",
                        "view_level": self._edge_view_level("CONTAINS", "repository", "file")
                    }
                }
            )

            for import_record in hierarchical_imports:

                nodes_for_import = import_record.get("nodes", [])

                for namespace_node in nodes_for_import:

                    namespace_path = namespace_node.get("path")

                    if not namespace_path or namespace_path in namespace_ids:
                        continue

                    namespace_id = f"ns_{namespace_path}"
                    namespace_ids[namespace_path] = namespace_id

                    nodes.append(
                        {
                            "data": {
                                "id": namespace_id,
                                "label": namespace_node.get("label"),
                                "type": namespace_node.get("kind", "Module").lower(),
                                "path": namespace_path,
                                "kind": namespace_node.get("kind", "Module"),
                                "depth": namespace_node.get("depth"),
                                "root": import_record.get("root"),
                                "scope": "local" if import_record.get("is_local") else "external",
                                "repo_id": repo_id,
                                "parent": namespace_ids.get(namespace_node.get("parent_path")),
                                "usage_count": namespace_usage_counts.get(namespace_path, 0),
                                "module_path": import_record.get("module_path"),
                                "leaf_path": import_record.get("leaf_path"),
                                "inferred": bool(namespace_node.get("inferred", import_record.get("inferred", False))),
                                "view_level": self._node_view_level(namespace_node.get("kind", "Module").lower())
                            }
                        }
                    )
                    node_index[namespace_id] = len(nodes) - 1
                    node_types[namespace_id] = namespace_node.get("kind", "Module").lower()

                for namespace_node in nodes_for_import:

                    namespace_path = namespace_node.get("path")
                    parent_path = namespace_node.get("parent_path")
                    relationship = namespace_node.get("relationship", "CONTAINS")

                    if not namespace_path or not parent_path:
                        continue

                    parent_id = namespace_ids.get(parent_path)
                    child_id = namespace_ids.get(namespace_path)

                    if not parent_id or not child_id:
                        continue

                    edges.append(
                        {
                            "data": {
                                "id": f"{parent_id}_{relationship.lower()}_{child_id}",
                                "source": parent_id,
                                "target": child_id,
                                "relationship": relationship,
                                "view_level": self._edge_view_level(
                                    relationship,
                                    node_types.get(parent_id, "module"),
                                    node_types.get(child_id, "symbol")
                                )
                            }
                        }
                    )

                leaf_node = nodes_for_import[-1] if nodes_for_import else None

                if not leaf_node:
                    continue

                leaf_namespace_id = namespace_ids.get(leaf_node.get("path"))

                if leaf_namespace_id:
                    visible_namespace_id = leaf_namespace_id

                    for namespace_node in reversed(nodes_for_import):
                        candidate_path = namespace_node.get("path")
                        candidate_id = namespace_ids.get(candidate_path)
                        candidate_type = node_types.get(candidate_id)

                        if candidate_path and candidate_type in {"package", "module"}:
                            visible_namespace_id = candidate_id or visible_namespace_id
                            break

                    leaf_node_type = node_types.get(visible_namespace_id, "symbol")
                    edges.append(
                        {
                            "data": {
                                "id": f"{file_node_id}_imports_{visible_namespace_id}",
                                "source": file_node_id,
                                "target": visible_namespace_id,
                                "relationship": "IMPORTS",
                                "view_level": self._edge_view_level("IMPORTS", "file", leaf_node_type)
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
            package_id = f"ns_{package}"

            if package_id in node_index:

                nodes[node_index[package_id]]["data"].update(
                    {
                        "package_type": package_type,
                        "version": details.get("version", "unknown"),
                        "status": details.get("status", "unknown"),
                        "color": package_colors.get(package_type, "#999999"),
                        "view_level": self._node_view_level("package")
                    }
                )

                continue

            nodes.append(
                {
                    "data": {
                        "id": package_id,
                        "label": package,
                        "type": "package",
                        "kind": "Package",
                        "package_type": package_type,
                        "version": details.get("version", "unknown"),
                        "status": details.get("status", "unknown"),
                        "color": package_colors.get(package_type, "#999999"),
                        "repo_id": repo_id,
                        "parent": repo_id,
                        "usage_count": namespace_usage_counts.get(package, 0),
                        "module_path": package,
                        "leaf_path": package,
                        "view_level": self._node_view_level("package")
                    }
                }
            )
            node_index[package_id] = len(nodes) - 1
            node_types[package_id] = "package"

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
                            "is_async": function.get("is_async", False),
                            "repo_id": repo_id,
                            "parent": file_node_id,
                            "usage_count": len(function_library_map.get((file_path, qualified_name), [])),
                            "libraries_used": function_library_map.get((file_path, qualified_name), []),
                            "module_path": qualified_name,
                            "leaf_path": qualified_name,
                            "view_level": self._node_view_level("function")
                        }
                    }
                )
                node_types[function_id] = "function"

                edges.append(
                    {
                        "data": {
                            "id": f"{file_path}_defines_{qualified_name}",
                            "source": file_node_id,
                            "target": function_id,
                            "relationship": "DEFINES",
                            "view_level": self._edge_view_level("DEFINES", "file", "function")
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
                            "bases": class_node.get("bases", []),
                            "repo_id": repo_id,
                            "parent": file_node_id,
                            "usage_count": len(class_node.get("bases", [])),
                            "module_path": qualified_name,
                            "leaf_path": qualified_name,
                            "view_level": self._node_view_level("class")
                        }
                    }
                )
                node_types[class_id] = "class"

                edges.append(
                    {
                        "data": {
                            "id": f"{file_path}_defines_class_{qualified_name}",
                            "source": file_node_id,
                            "target": class_id,
                            "relationship": "DEFINES",
                            "view_level": self._edge_view_level("DEFINES", "file", "class")
                        }
                    }
                )

            for api in semantics.get("apis", []):
                api_name = api.get("name")
                api_package = normalize_package_name(api.get("package"))
                api_id = f"api_{api_package}_{api_name}_{file_path}_{api.get('line')}"
                api_parent_id = function_ids.get((file_path, api.get("function")))

                nodes.append(
                    {
                        "data": {
                            "id": api_id,
                            "label": api_name,
                            "type": "api",
                            "package": api_package,
                            "path": file_path,
                            "line": api.get("line"),
                            "repo_id": repo_id,
                            "parent": api_parent_id,
                            "usage_count": 1,
                            "module_path": api_package,
                            "leaf_path": api_name,
                            "view_level": self._node_view_level("api")
                        }
                    }
                )
                node_types[api_id] = "api"

                if api_parent_id:
                    edges.append(
                        {
                            "data": {
                                "id": f"{api_parent_id}_uses_{api_id}",
                                "source": api_parent_id,
                                "target": api_id,
                                "relationship": "USES_API",
                                "view_level": self._edge_view_level("USES_API", "function", "api")
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
                                "relationship": "CALLS",
                                "view_level": self._edge_view_level(
                                    "CALLS",
                                    node_types.get(caller_id, "function"),
                                    node_types.get(callee_id, "function")
                                )
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
                                    "relationship": "INHERITS",
                                    "view_level": self._edge_view_level("INHERITS", "class", "class")
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
                "total_namespace_nodes": sum(
                    len(self._get_hierarchical_imports(imports))
                    for imports in import_files.values()
                ),
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

        hierarchical_imports = self._get_hierarchical_imports(module_imports)

        all_imports = list(dict.fromkeys(
            module_imports.get("normalized", [])
        ))

        dependency_graph = self._get_dependency_graph()

        return {
            "path": module_path,
            "imports": {
                "direct": module_imports.get("direct", []),
                "from": module_imports.get("from", []),
                "normalized": module_imports.get("normalized", []),
                "hierarchical": hierarchical_imports
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
        requested_namespace = package.strip().strip(".")
        normalized_package = normalize_package_name(requested_namespace)
        dependent_files = []

        import_files = self._get_import_files()

        for file_path, imports in import_files.items():
            hierarchical_imports = self._get_hierarchical_imports(imports)

            if any(
                self._namespace_matches_request(import_record, requested_namespace, normalized_package)
                for import_record in hierarchical_imports
            ):
                dependent_files.append(file_path)

        package_data = self._get_dependency_graph().get(
            normalized_package,
            {}
        )

        return {
            "package": requested_namespace or normalized_package,
            "root_package": normalized_package,
            "package_data": package_data,
            "dependent_modules": dependent_files,
            "impact_count": len(dependent_files)
        }

    def _namespace_matches_request(
        self,
        import_record: Dict[str, Any],
        requested_namespace: str,
        root_package: str
    ) -> bool:

        if not requested_namespace:
            return False

        candidate_paths = []

        for namespace_node in import_record.get("nodes", []):
            namespace_path = namespace_node.get("path")

            if namespace_path:
                candidate_paths.append(namespace_path)

        candidate_paths.extend(
            [
                import_record.get("module"),
                import_record.get("root")
            ]
        )

        for candidate_path in candidate_paths:
            if not candidate_path:
                continue

            if candidate_path == requested_namespace:
                return True

            if candidate_path.startswith(f"{requested_namespace}."):
                return True

            if requested_namespace == root_package and candidate_path.startswith(f"{root_package}."):
                return True

        return False


def visualize_repository(repo_id: str, analysis: Dict) -> Dict:
    visualizer = GraphVisualizer(analysis)

    return {
        "cytoscape": visualizer.to_cytoscape_format(repo_id),
        "statistics": visualizer.get_statistics()
    }
