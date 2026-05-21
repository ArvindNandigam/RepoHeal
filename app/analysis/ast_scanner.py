import ast
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)


def extract_imports_from_file(file_path):

    imports = []

    try:

        with open(
            file_path,
            "r",
            encoding="utf-8"
        ) as f:

            source = f.read()

        tree = ast.parse(source)

        for node in ast.walk(tree):

            if isinstance(node, ast.Import):

                for alias in node.names:
                    imports.append(alias.name)

            elif isinstance(node, ast.ImportFrom):

                if node.module:
                    imports.append(node.module)

    except Exception as e:

        logger.error(
            f"AST parsing failed for {file_path}: {e}"
        )

    return list(set(imports))


def scan_repository(repo_path):

    repository_imports = {}

    python_files = Path(repo_path).rglob("*.py")

    for py_file in python_files:

        imports = extract_imports_from_file(py_file)

        repository_imports[str(py_file)] = imports

    return repository_imports