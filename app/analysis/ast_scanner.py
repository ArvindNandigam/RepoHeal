import ast
import json

from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)


def extract_imports_from_python_source(source):

    imports = {
        "direct": [],
        "from": []
    }

    try:

        tree = ast.parse(source)

        for node in ast.walk(tree):

            if isinstance(node, ast.Import):

                for alias in node.names:

                    imports["direct"].append(
                        alias.name
                    )

            elif isinstance(node, ast.ImportFrom):

                if node.module:

                    imports["from"].append(
                        node.module
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

    return imports


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

    repository_imports = {}

    # Python files
    python_files = Path(repo_path).rglob("*.py")

    for py_file in python_files:

        imports = extract_imports_from_file(
            py_file
        )

        repository_imports[str(py_file)] = imports

    # Jupyter notebooks
    notebook_files = Path(repo_path).rglob(
        "*.ipynb"
    )

    for notebook_file in notebook_files:

        imports = (
            extract_imports_from_notebook(
                notebook_file
            )
        )

        repository_imports[
            str(notebook_file)
        ] = imports

    logger.info(
        f"Scanned "
        f"{len(repository_imports)} files"
    )

    return repository_imports