from app.analysis.ast_scanner import scan_repository
from app.analysis.dependency_detector import extract_requirements

from app.utils.logger import get_logger

logger = get_logger(__name__)


def analyze_repository(repo_path):

    logger.info(f"Analyzing repository: {repo_path}")

    file_imports = scan_repository(repo_path)

    dependencies = extract_requirements(repo_path)

    all_imports = set()
    for imports in file_imports.values():
        all_imports.update(
            imports.get("direct", [])
        )
        all_imports.update(
            imports.get("from", [])
        )

    declared_packages = set(dependencies.keys())
    missing_packages = sorted(all_imports - declared_packages)
    unused_packages = sorted(declared_packages - all_imports)

    dependency_graph = {}
    for package in sorted(all_imports):
        dependency_graph[package] = {
            "version": dependencies.get(package, "unknown"),
            "type": (
                "third-party"
                if package in declared_packages
                else "detected"
            ),
            "status": (
                "declared"
                if package in declared_packages
                else "missing"
            )
        }

    analysis = {
        "imports": {
            "files": file_imports,
            "summary": {
                "total_modules": len(file_imports),
                "total_imports": len(all_imports),
                "declared_dependencies": len(dependencies),
                "third_party_packages": len(declared_packages & all_imports),
                "local_packages": len(all_imports - declared_packages)
            }
        },
        "dependencies": {
            "declared": dependencies,
            "count": len(dependencies)
        },
        "dependency_graph": dependency_graph,
        "issues": {
            "missing_dependencies": missing_packages,
            "unused_dependencies": unused_packages,
            "missing_count": len(missing_packages),
            "unused_count": len(unused_packages)
        }
    }

    logger.info("Repository analysis complete")

    return analysis