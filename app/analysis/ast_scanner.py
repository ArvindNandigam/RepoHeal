import ast
import json

from pathlib import Path

from app.analysis.package_normalization import (
    build_namespace_hierarchy,
    build_module_name,
    is_local_import,
    normalize_package_name
)

from app.utils.logger import get_logger

logger = get_logger(__name__)


EXTERNAL_API_ROOTS = {
    "boto3",
    "cv2",
    "matplotlib",
    "numpy",
    "openai",
    "pandas",
    "requests",
    "scipy",
    "seaborn",
    "sklearn",
    "torch",
}


def _node_name(node):

    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):

        parent = _node_name(node.value)

        if parent:
            return f"{parent}.{node.attr}"

        return node.attr

    if isinstance(node, ast.Call):
        return _node_name(node.func)

    return None


def _attribute_chain_parts(node):

    if isinstance(node, ast.Name):
        return [node.id]

    if isinstance(node, ast.Attribute):
        parent_parts = _attribute_chain_parts(node.value)

        if not parent_parts:
            return [node.attr]

        return parent_parts + [node.attr]

    if isinstance(node, ast.Call):
        return _attribute_chain_parts(node.func)

    return None


def extract_imports_from_python_source(source, module_index=None, import_aliases=None):

    imports = {
        "direct": [],
        "from": [],
        "normalized": [],
        "external": [],
        "local": [],
        "hierarchical": []
    }

    module_index = module_index or set()

    hierarchical_imports = []

    try:

        tree = ast.parse(source)

        import_aliases = import_aliases or {}
        for node in ast.walk(tree):

            if isinstance(node, ast.Import):

                for imported in node.names:
                    local_name = imported.asname or imported.name.split(".")[0]
                    import_aliases[local_name] = imported.name

            elif isinstance(node, ast.ImportFrom):

                if not node.module:
                    continue

                for imported in node.names:
                    local_name = imported.asname or imported.name
                    import_aliases[local_name] = f"{node.module}.{imported.name}"

        # Track variable origins: df -> pandas (from df = pd.DataFrame(...))
        variable_origins = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
                call_chain = _attribute_chain_parts(node.value.func)
                if call_chain and len(call_chain) >= 2:
                    lhs_root = call_chain[0]
                    resolved = import_aliases.get(lhs_root, lhs_root)
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            variable_origins[target.id] = normalize_package_name(resolved)

        for node in ast.walk(tree):

            if isinstance(node, ast.Import):

                for alias in node.names:

                    imports["direct"].append(
                        alias.name
                    )

                    normalized_name = normalize_package_name(alias.name)
                    hierarchy = build_namespace_hierarchy(alias.name)
                    import_record = {
                        "source": "import",
                        "module": alias.name,
                        "symbol": None,
                        "alias": alias.asname,
                        "root": normalized_name,
                        "is_local": is_local_import(
                            alias.name,
                            module_index
                        ),
                        **hierarchy
                    }

                    hierarchical_imports.append(import_record)

                    if is_local_import(alias.name, module_index):

                        imports["local"].append(
                            normalized_name
                        )

                    else:

                        imports["normalized"].append(
                            normalized_name
                        )

            elif isinstance(node, ast.ImportFrom):

                if node.module:

                    imports["from"].append(
                        node.module
                    )

                    normalized_name = normalize_package_name(node.module)

                    if is_local_import(node.module, module_index):

                        imports["local"].append(
                            normalized_name
                        )

                    else:

                        imports["normalized"].append(
                            normalized_name
                        )

                    for imported in node.names:

                        hierarchy = build_namespace_hierarchy(
                            node.module,
                            imported.name
                        )

                        hierarchical_imports.append(
                            {
                                "source": "from",
                                "module": node.module,
                                "symbol": imported.name,
                                "alias": imported.asname,
                                "root": normalized_name,
                                "is_local": is_local_import(
                                    node.module,
                                    module_index
                                ),
                                **hierarchy
                            }
                        )

            # synthesize attribute-chain usage (strict heuristic)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):

                # get full dotted name
                chain_parts = _attribute_chain_parts(node.func)
                full_name = ".".join(chain_parts or [])

                if not chain_parts or len(chain_parts) < 2:
                    continue

                parts = chain_parts
                leftmost = parts[0]

                # resolve alias if present, also check variable origins
                resolved_root = import_aliases.get(leftmost, variable_origins.get(leftmost, leftmost))
                canonical_root = normalize_package_name(resolved_root)

                # strict heuristic: only synthesize if leftmost is an import alias, known normalized import, external root, or local module
                should_synthesize = False

                if leftmost in import_aliases or leftmost in variable_origins:
                    should_synthesize = True

                if canonical_root in EXTERNAL_API_ROOTS:
                    should_synthesize = True

                if canonical_root in imports.get("normalized", []):
                    should_synthesize = True

                if resolved_root in (module_index or set()):
                    should_synthesize = True

                if not should_synthesize:
                    continue

                # build module_path (all but last) and symbol (last)
                module_path = ".".join([resolved_root] + parts[1:-1]) if len(parts) > 2 else resolved_root
                symbol = parts[-1]

                # normalize for root
                normalized_root = normalize_package_name(resolved_root)

                try:
                    hierarchy = build_namespace_hierarchy(module_path, symbol)

                    hierarchical_imports.append(
                        {
                            "source": "attribute",
                            "module": module_path,
                            "symbol": symbol,
                            "alias": None,
                            "root": normalized_root,
                            "is_local": is_local_import(resolved_root, module_index),
                            "inferred": True,
                            "module_path": module_path,
                            "leaf_path": f"{module_path}.{symbol}" if module_path else symbol,
                            **hierarchy
                        }
                    )
                except Exception:
                    # fall back silently
                    pass

    except Exception as e:

        logger.error(
            f"AST parsing failed: {e}"
        )

    imports["direct"] = list(dict.fromkeys(
        imports["direct"]
    ))

    imports["from"] = list(dict.fromkeys(
        imports["from"]
    ))

    imports["normalized"] = list(dict.fromkeys(
        imports["normalized"]
    ))

    imports["local"] = list(dict.fromkeys(
        imports["local"]
    ))

    unique_hierarchical_imports = []
    seen_hierarchical_imports = set()

    for import_record in hierarchical_imports:
        unique_key = (
            import_record.get("source"),
            import_record.get("module"),
            import_record.get("symbol"),
            import_record.get("alias")
        )

        if unique_key in seen_hierarchical_imports:
            continue

        seen_hierarchical_imports.add(unique_key)
        unique_hierarchical_imports.append(import_record)

    imports["hierarchical"] = unique_hierarchical_imports

    return imports


def extract_python_semantics(source, module_name=None, module_index=None):

    module_index = module_index or set()

    semantics = {
        "module_name": module_name,
        "functions": [],
        "classes": [],
        "calls": [],
        "apis": []
    }

    try:

        tree = ast.parse(source)

        for node in ast.walk(tree):

            if isinstance(node, ast.FunctionDef):

                semantics["functions"].append(
                    {
                        "name": node.name,
                        "qualified_name": node.name,
                        "line_start": getattr(node, "lineno", None),
                        "line_end": getattr(node, "end_lineno", None),
                        "is_async": False
                    }
                )

            elif isinstance(node, ast.AsyncFunctionDef):

                semantics["functions"].append(
                    {
                        "name": node.name,
                        "qualified_name": node.name,
                        "line_start": getattr(node, "lineno", None),
                        "line_end": getattr(node, "end_lineno", None),
                        "is_async": True
                    }
                )

            elif isinstance(node, ast.ClassDef):

                semantics["classes"].append(
                    {
                        "name": node.name,
                        "qualified_name": node.name,
                        "line_start": getattr(node, "lineno", None),
                        "line_end": getattr(node, "end_lineno", None),
                        "bases": [
                            ast.unparse(base)
                            if hasattr(ast, "unparse")
                            else getattr(base, "id", None)
                            for base in node.bases
                        ]
                    }
                )

        import_aliases = {}

        for node in ast.walk(tree):

            if isinstance(node, ast.Import):

                for imported in node.names:
                    local_name = imported.asname or imported.name.split(".")[0]
                    import_aliases[local_name] = imported.name

            elif isinstance(node, ast.ImportFrom):

                if not node.module:
                    continue

                for imported in node.names:
                    local_name = imported.asname or imported.name
                    import_aliases[local_name] = f"{node.module}.{imported.name}"

        # Track variable origins: df -> pandas (from df = pd.DataFrame(...))
        variable_origins = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
                call_chain = _attribute_chain_parts(node.value.func)
                if call_chain and len(call_chain) >= 2:
                    lhs_root = call_chain[0]
                    resolved = import_aliases.get(lhs_root, lhs_root)
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            variable_origins[target.id] = normalize_package_name(resolved)

        function_stack = []

        class SemanticVisitor(ast.NodeVisitor):

            def visit_FunctionDef(self, node):
                function_stack.append(node.name)
                self.generic_visit(node)
                function_stack.pop()

            def visit_AsyncFunctionDef(self, node):
                function_stack.append(node.name)
                self.generic_visit(node)
                function_stack.pop()

            def visit_Call(self, node):
                call_name = _node_name(node.func)

                if call_name:
                    root_name = call_name.split(".")[0]
                    resolved_root = import_aliases.get(root_name, variable_origins.get(root_name, root_name))
                    canonical_root = normalize_package_name(resolved_root)

                    is_local = is_local_import(
                        resolved_root,
                        module_index
                    )
                    
                    if root_name != resolved_root:
                        parts = call_name.split(".")
                        parts[0] = resolved_root
                        qualified_call_name = ".".join(parts)
                    else:
                        qualified_call_name = call_name

                    semantics["calls"].append(
                        {
                            "name": qualified_call_name,
                            "canonical_root": canonical_root,
                            "line": getattr(node, "lineno", None),
                            "function": ".".join(function_stack)
                            if function_stack
                            else None,
                            "is_local": is_local,
                            "is_external_api": (
                                canonical_root in EXTERNAL_API_ROOTS
                                or not is_local
                            )
                        }
                    )

                self.generic_visit(node)

        SemanticVisitor().visit(tree)

        semantics["apis"] = [
            {
                "name": call_record["name"],
                "package": call_record["canonical_root"],
                "line": call_record["line"],
                "function": call_record["function"]
            }
            for call_record in semantics["calls"]
            if call_record["is_external_api"]
        ]

    except Exception as e:

        logger.error(
            f"AST parsing failed: {e}"
        )

    return semantics


def extract_imports_from_file(file_path):

    try:

        with open(
            file_path,
            "r",
            encoding="utf-8"
        ) as f:

            source = f.read()

        return extract_imports_from_python_source(
            source
        )

    except Exception as e:

        logger.error(
            f"Failed reading {file_path}: {e}"
        )

        return {
            "direct": [],
            "from": []
        }


def extract_imports_from_notebook(file_path, module_index=None, _content_override=None):

    imports = {
        "direct": [],
        "from": [],
        "normalized": [],
        "local": [],
        "hierarchical": []
    }

    try:

        if _content_override is not None:
            notebook = json.loads(_content_override) if isinstance(_content_override, str) else _content_override
        else:
            with open(
                file_path,
                "r",
                encoding="utf-8"
            ) as f:

                notebook = json.load(f)

        cells = notebook.get("cells", [])

        import_aliases = {}

        for cell in cells:

            if cell.get("cell_type") != "code":
                continue

            source = "".join(
                cell.get("source", [])
            )

            cell_imports = (
                extract_imports_from_python_source(
                    source,
                    module_index=module_index,
                    import_aliases=import_aliases
                )
            )

            imports["direct"].extend(
                cell_imports["direct"]
            )

            imports["from"].extend(
                cell_imports["from"]
            )

            imports["normalized"].extend(
                cell_imports.get("normalized", [])
            )

            imports["local"].extend(
                cell_imports.get("local", [])
            )

            imports["hierarchical"].extend(
                cell_imports.get("hierarchical", [])
            )

    except Exception as e:

        logger.error(
            f"Notebook parsing failed "
            f"for {file_path}: {e}"
        )

    imports["direct"] = list(dict.fromkeys(
        imports["direct"]
    ))

    imports["from"] = list(dict.fromkeys(
        imports["from"]
    ))

    imports["normalized"] = list(dict.fromkeys(
        imports["normalized"]
    ))

    imports["local"] = list(dict.fromkeys(
        imports["local"]
    ))

    unique_hierarchical_imports = []
    seen_hierarchical_imports = set()

    for import_record in imports["hierarchical"]:
        unique_key = (
            import_record.get("source"),
            import_record.get("module"),
            import_record.get("symbol"),
            import_record.get("alias")
        )

        if unique_key in seen_hierarchical_imports:
            continue

        seen_hierarchical_imports.add(unique_key)
        unique_hierarchical_imports.append(import_record)

    imports["hierarchical"] = unique_hierarchical_imports

    return imports


def extract_semantics_from_notebook(file_path, module_name=None, module_index=None, _content_override=None):

    semantic_data = {
        "module_name": module_name,
        "functions": [],
        "classes": [],
        "calls": [],
        "apis": []
    }

    try:

        if _content_override is not None:
            notebook = json.loads(_content_override) if isinstance(_content_override, str) else _content_override
        else:
            with open(
                file_path,
                "r",
                encoding="utf-8"
            ) as f:

                notebook = json.load(f)

        cells = notebook.get("cells", [])

        for cell in cells:

            if cell.get("cell_type") != "code":
                continue

            source = "".join(
                cell.get("source", [])
            )

            cell_semantics = extract_python_semantics(
                source,
                module_name=module_name,
                module_index=module_index
            )

            semantic_data["functions"].extend(
                cell_semantics.get("functions", [])
            )

            semantic_data["classes"].extend(
                cell_semantics.get("classes", [])
            )

            semantic_data["calls"].extend(
                cell_semantics.get("calls", [])
            )

            semantic_data["apis"].extend(
                cell_semantics.get("apis", [])
            )

    except Exception as e:

        logger.error(
            f"Notebook semantic parsing failed for {file_path}: {e}"
        )

    return semantic_data


def _memory_module_name(rel_path: str) -> str:
    path = rel_path.replace("\\", "/")
    parts = path.split("/")
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join(p for p in parts if p)


def scan_repository(repo_path, file_contents: dict | None = None):
    """
    Scans repository files for imports and semantic structure.
    When `file_contents` is provided (`{relative_path: text_content}`),
    uses in-memory content instead of reading from disk.
    """
    import json as _json

    repository_files = []
    python_files: list = []
    notebook_files: list = []

    if file_contents:
        for rel_path in file_contents:
            if rel_path.endswith(".py"):
                python_files.append(rel_path)
            elif rel_path.endswith(".ipynb"):
                notebook_files.append(rel_path)
        repository_files = python_files + notebook_files
    else:
        python_files = list(Path(repo_path).rglob("*.py"))
        notebook_files = list(Path(repo_path).rglob("*.ipynb"))
        repository_files = python_files + notebook_files

    module_index = set()

    if file_contents:
        for py_file in python_files:
            module_index.add(
                _memory_module_name(py_file)
            )
    else:
        for py_file in python_files:
            module_index.add(
                build_module_name(str(py_file), repo_path)
            )

    imports_by_file = {}
    semantic_by_file = {}

    for notebook_file in notebook_files:
        if file_contents:
            nb_content = file_contents.get(notebook_file, "{}")
            imports = extract_imports_from_notebook(
                notebook_file,
                module_index=module_index,
                _content_override=nb_content if isinstance(nb_content, str) else nb_content.decode("utf-8", errors="replace"),
            )
            mod_name = _memory_module_name(notebook_file)
            imports_by_file[notebook_file] = imports
            semantic_by_file[notebook_file] = {
                **extract_semantics_from_notebook(
                    notebook_file,
                    module_name=mod_name,
                    module_index=module_index,
                    _content_override=nb_content if isinstance(nb_content, str) else nb_content.decode("utf-8", errors="replace"),
                )
            }
        else:
            imports = extract_imports_from_notebook(
                notebook_file,
                module_index=module_index
            )
            imports_by_file[str(notebook_file)] = imports
            semantic_by_file[str(notebook_file)] = {
                **extract_semantics_from_notebook(
                    notebook_file,
                    module_name=build_module_name(
                        str(notebook_file),
                        repo_path
                    ),
                    module_index=module_index
                )
            }

    for py_file in python_files:
        if file_contents:
            source = file_contents[py_file]
            if isinstance(source, bytes):
                source = source.decode("utf-8", errors="replace")
            mod_name = _memory_module_name(py_file)
        else:
            with open(py_file, "r", encoding="utf-8") as f:
                source = f.read()
            mod_name = build_module_name(str(py_file), repo_path)

        imports = extract_imports_from_python_source(
            source,
            module_index=module_index
        )

        fp_key = py_file if file_contents else str(py_file)
        imports_by_file[fp_key] = imports
        semantic_by_file[fp_key] = extract_python_semantics(
            source,
            module_name=mod_name,
            module_index=module_index
        )

    repository_imports = {
        "files": imports_by_file,
        "summary": {
            "total_files": len(repository_files),
            "total_python_files": len(python_files),
            "total_notebooks": len(notebook_files),
            "total_imports": len({
                normalized
                for file_imports in imports_by_file.values()
                for normalized in file_imports.get("normalized", [])
            }),
            "total_local_imports": len({
                local_import
                for file_imports in imports_by_file.values()
                for local_import in file_imports.get("local", [])
            })
        }
    }

    semantic_summary = {
        "total_files": len(semantic_by_file),
        "total_functions": sum(
            len(file_semantics.get("functions", []))
            for file_semantics in semantic_by_file.values()
        ),
        "total_classes": sum(
            len(file_semantics.get("classes", []))
            for file_semantics in semantic_by_file.values()
        ),
        "total_calls": sum(
            len(file_semantics.get("calls", []))
            for file_semantics in semantic_by_file.values()
        ),
        "total_api_calls": sum(
            len(file_semantics.get("apis", []))
            for file_semantics in semantic_by_file.values()
        )
    }

    logger.info(
        f"Scanned "
        f"{len(repository_files)} files"
    )

    return {
        "imports": repository_imports,
        "semantic_graph": {
            "files": semantic_by_file,
            "summary": semantic_summary
        }
    }