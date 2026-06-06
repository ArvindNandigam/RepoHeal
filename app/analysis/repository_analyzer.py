from app.analysis.ast_scanner import scan_repository
from app.analysis.dependency_detector import extract_requirements
from app.analysis.package_normalization import normalize_package_name

import concurrent.futures
import requests

from app.utils.logger import get_logger

logger = get_logger(__name__)

def _fetch_pypi_version(package: str):
    try:
        response = requests.get(f"https://pypi.org/pypi/{package}/json", timeout=3)
        if response.status_code == 200:
            return package, response.json()["info"]["version"]
    except Exception as e:
        pass
    return package, None

def get_latest_pypi_versions(packages):
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_pkg = {executor.submit(_fetch_pypi_version, pkg): pkg for pkg in packages}
        for future in concurrent.futures.as_completed(future_to_pkg):
            pkg, version = future.result()
            if version:
                results[pkg] = version
    return results

def analyze_repository(repo_path):

    logger.info(f"Analyzing repository: {repo_path}")

    scan_result = scan_repository(repo_path)

    file_imports = scan_result.get(
        "imports",
        {}
    ).get(
        "files",
        {}
    )

    semantic_graph = scan_result.get(
        "semantic_graph",
        {}
    )

    dependencies = extract_requirements(repo_path)

    all_imports = set()
    for imports in file_imports.values():
        all_imports.update(
            imports.get("normalized", [])
        )

    declared_packages = {
        normalize_package_name(package)
        for package in dependencies.keys()
    }
    missing_packages = sorted(all_imports - declared_packages)
    unused_packages = sorted(declared_packages - all_imports)

    logger.info("Fetching latest PyPI versions for packages...")
    packages_to_check = all_imports.union(declared_packages)
    latest_versions = get_latest_pypi_versions(packages_to_check)

    dependency_graph = {}
    for package in sorted(all_imports):
        package_info = dependencies.get(package, {})
        dependency_graph[package] = {
            "version": package_info.get("version", "unknown"),
            "latest_version": latest_versions.get(package, "unknown"),
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

    from app.analysis.fingerprint import generate_fingerprints
    fingerprints = generate_fingerprints(semantic_graph, dependencies)

    analysis = {
        "imports": {
            "files": file_imports,
            "summary": scan_result.get(
                "imports",
                {}
            ).get(
                "summary",
                {}
            )
        },
        "semantic_graph": semantic_graph,
        "dependencies": {
            "declared": dependencies,
            "count": len(dependencies)
        },
        "dependency_graph": dependency_graph,
        "fingerprints": fingerprints,
        "issues": {
            "missing_dependencies": missing_packages,
            "unused_dependencies": unused_packages,
            "missing_count": len(missing_packages),
            "unused_count": len(unused_packages)
        }
    }

    logger.info("Repository analysis complete")

    return analysis