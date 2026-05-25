import ast
import json

from pathlib import Path

from app.analysis.package_normalization import (
    build_module_name,
    is_local_import,
    normalize_package_name
)

from app.utils.logger import get_logger

logger = get_logger(__name__)


EXTERNAL_API_ROOTS = {
    "boto3",
    "cv2",
    "openai",
    "requests",
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


def extract_imports_from_python_source(source, module_index=None):

    imports = {
        "direct": [],
        "from": [],
        "normalized": [],
        "external": [],
        "local": []
    }

    module_index = module_index or set()

    try:

        tree = ast.parse(source)

        for node in ast.walk(tree):

            if isinstance(node, ast.Import):

                for alias in node.names:

                    imports["direct"].append(
                        alias.name
                    )

                    normalized_name = normalize_package_name(alias.name)

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

        for node in tree.body:

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
                    resolved_root = import_aliases.get(root_name, root_name)
                    canonical_root = normalize_package_name(resolved_root)

                    semantics["calls"].append(
                        {
                            "name": call_name,
                            "canonical_root": canonical_root,
                            "line": getattr(node, "lineno", None),
                            "function": ".".join(function_stack)
                            if function_stack
                            else None,
                            "is_local": is_local_import(
                                resolved_root,
                                module_index
                            ),
                            "is_external_api": (
                                canonical_root in EXTERNAL_API_ROOTS
                                or canonical_root != resolved_root
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


def extract_imports_from_notebook(file_path):

    imports = {
        "direct": [],
        "from": []
    }

    try:

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

            cell_imports = (
                extract_imports_from_python_source(
                    source
                )
            )

            imports["direct"].extend(
                cell_imports["direct"]
            )

            imports["from"].extend(
                cell_imports["from"]
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

    return imports


def scan_repository(repo_path):

    repository_files = []

    python_files = list(Path(repo_path).rglob("*.py"))
    notebook_files = list(Path(repo_path).rglob("*.ipynb"))

    repository_files.extend(python_files)
    repository_files.extend(notebook_files)

    module_index = set()

    for py_file in python_files:
        module_index.add(
            build_module_name(str(py_file), repo_path)
        )

    imports_by_file = {}
    semantic_by_file = {}

    for notebook_file in notebook_files:

        imports = extract_imports_from_notebook(
            notebook_file
        )

        imports_by_file[str(notebook_file)] = imports
        semantic_by_file[str(notebook_file)] = {
            "module_name": build_module_name(
                str(notebook_file),
                repo_path
            ),
            "functions": [],
            "classes": [],
            "calls": [],
            "apis": []
        }

    for py_file in python_files:

        with open(
            py_file,
            "r",
            encoding="utf-8"
        ) as f:
            source = f.read()

        imports = extract_imports_from_python_source(
            source,
            module_index=module_index
        )

        imports_by_file[str(py_file)] = imports
        semantic_by_file[str(py_file)] = extract_python_semantics(
            source,
            module_name=build_module_name(
                str(py_file),
                repo_path
            ),
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