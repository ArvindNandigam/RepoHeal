from datetime import datetime, timezone
from typing import Dict, Any
from app.db.database import get_mongo_db
from app.utils.logger import get_logger

logger = get_logger(__name__)


# --- Tier 1: Resume Metrics ---

def count_repository(repo_id: str) -> None:
    db = get_mongo_db()
    db.platform_metrics.update_one(
        {"metric": "repositories_analyzed"},
        {"$addToSet": {"values": repo_id}},
        upsert=True
    )


def count_analysis(repo_id: str) -> None:
    db = get_mongo_db()
    db.platform_metrics.update_one(
        {"metric": "analyses_performed"},
        {"$inc": {"count": 1}, "$set": {"last_repo": repo_id, "updated_at": datetime.now(timezone.utc)}},
        upsert=True
    )


def count_commit() -> None:
    db = get_mongo_db()
    db.platform_metrics.update_one(
        {"metric": "commits_analyzed"},
        {"$inc": {"count": 1}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        upsert=True
    )


def count_branch(branch: str) -> None:
    db = get_mongo_db()
    db.platform_metrics.update_one(
        {"metric": "branches_analyzed"},
        {"$addToSet": {"values": branch}},
        upsert=True
    )


# --- Tier 1: Code Scale ---

def record_code_scale(files: int, notebooks: int, functions: int, classes: int, apis: int, lines: int = 0) -> None:
    db = get_mongo_db()
    updates = {
        "$inc": {
            "python_files_scanned": files,
            "notebooks_scanned": notebooks,
            "functions_indexed": functions,
            "classes_indexed": classes,
            "apis_fingerprinted": apis,
            "lines_of_code_scanned": lines,
        },
        "$set": {"updated_at": datetime.now(timezone.utc)},
    }
    db.platform_metrics.update_one(
        {"metric": "code_scale"},
        updates,
        upsert=True
    )


# --- Tier 1: Knowledge Graph ---

def record_graph_scale(repo_id: str, node_count: int, edge_count: int) -> None:
    db = get_mongo_db()
    # Track largest graph
    largest = db.platform_metrics.find_one({"metric": "largest_graph"})
    current_max = (largest or {}).get("node_count", 0)
    is_largest = node_count > current_max
    largest_entry = {
        "repo_id": repo_id,
        "node_count": node_count,
        "edge_count": edge_count,
    } if is_largest else None

    db.platform_metrics.update_one(
        {"metric": "graph_scale"},
        {
            "$inc": {
                "total_nodes": node_count,
                "total_edges": edge_count,
                "graph_count": 1,
            },
            "$set": {"updated_at": datetime.now(timezone.utc)},
            "$max": {"largest_node_count": node_count if is_largest else 0},
        }
        if not largest_entry
        else {
            "$inc": {
                "total_nodes": node_count,
                "total_edges": edge_count,
                "graph_count": 1,
            },
            "$set": {
                "updated_at": datetime.now(timezone.utc),
                "largest_repo": repo_id,
                "largest_node_count": node_count,
                "largest_edge_count": edge_count,
            },
        },
        upsert=True
    )


# --- Tier 1: Dependency Intelligence ---

def record_dependency_intelligence(
    deps_detected: int,
    unique_packages: int,
    deprecated_apis: int,
    breaking_apis: int,
    migration_candidates: int
) -> None:
    db = get_mongo_db()
    db.platform_metrics.update_one(
        {"metric": "dependency_intelligence"},
        {
            "$inc": {
                "dependencies_detected": deps_detected,
                "unique_packages_seen": unique_packages,
                "deprecated_apis_found": deprecated_apis,
                "breaking_apis_found": breaking_apis,
                "migration_candidates": migration_candidates,
            },
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
        upsert=True
    )


# --- Tier 2: Impact Analysis ---

def record_impact_analysis(affected_files: int, affected_functions: int, chains_traversed: int) -> None:
    db = get_mongo_db()
    db.platform_metrics.update_one(
        {"metric": "impact_analysis"},
        {
            "$inc": {
                "affected_files_identified": affected_files,
                "affected_functions_traced": affected_functions,
                "call_chains_traversed": chains_traversed,
            },
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
        upsert=True
    )


# --- Tier 2: Migration ---

def record_migration_metrics(reports: int, simulations: int, auto_fixes: int) -> None:
    db = get_mongo_db()
    db.platform_metrics.update_one(
        {"metric": "migration_metrics"},
        {
            "$inc": {
                "migration_reports_generated": reports,
                "upgrade_simulations_run": simulations,
                "auto_fix_opportunities": auto_fixes,
            },
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
        upsert=True
    )


# --- Tier 2: Remediation ---

def record_remediation(prs: int = 0, files_modified: int = 0, imports_rewritten: int = 0, symbols_renamed: int = 0) -> None:
    db = get_mongo_db()
    db.platform_metrics.update_one(
        {"metric": "remediation"},
        {
            "$inc": {
                "prs_created": prs,
                "files_modified": files_modified,
                "imports_rewritten": imports_rewritten,
                "symbols_renamed": symbols_renamed,
            },
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
        upsert=True
    )


# --- Tier 3: Monitoring ---

def record_monitoring_metrics(alerts: int = 0, degradations: int = 0, watchlist_packages: int = 0) -> None:
    db = get_mongo_db()
    db.platform_metrics.update_one(
        {"metric": "monitoring"},
        {
            "$inc": {
                "alerts_generated": alerts,
                "health_degradations_detected": degradations,
                "watchlist_packages": watchlist_packages,
            },
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
        upsert=True
    )


# --- Performance ---

def record_analysis_duration(seconds: float, success: bool) -> None:
    db = get_mongo_db()
    from bson import DBRef
    db.platform_metrics.update_one(
        {"metric": "performance"},
        {
            "$inc": {
                "total_analysis_time_seconds": seconds,
                "analysis_count": 1,
                "success_count": 1 if success else 0,
                "failure_count": 0 if success else 1,
            },
            "$set": {"updated_at": datetime.now(timezone.utc)},
            "$min": {"min_analysis_time": seconds},
            "$max": {"max_analysis_time": seconds},
        },
        upsert=True
    )


# --- Aggregation ---

def get_all_metrics() -> Dict[str, Any]:
    """Aggregate all platform metrics into a single flat dict for the admin dashboard."""
    db = get_mongo_db()
    docs = list(db.platform_metrics.find({}, {"_id": 0}))
    result = {
        # Tier 1: Repository Scale
        "repositories_analyzed": 0,
        "unique_repositories": [],
        "analyses_performed": 0,
        "commits_analyzed": 0,
        "branches_analyzed": [],
        # Tier 1: Code Scale
        "python_files_scanned": 0,
        "notebooks_scanned": 0,
        "functions_indexed": 0,
        "classes_indexed": 0,
        "apis_fingerprinted": 0,
        "lines_of_code_scanned": 0,
        # Tier 1: Knowledge Graph
        "total_nodes": 0,
        "total_edges": 0,
        "graph_count": 0,
        "largest_graph_repo": "",
        "largest_node_count": 0,
        "largest_edge_count": 0,
        # Tier 1: Dependency Intelligence
        "dependencies_detected": 0,
        "unique_packages_seen": 0,
        "deprecated_apis_found": 0,
        "breaking_apis_found": 0,
        "migration_candidates": 0,
        # Tier 2: Impact
        "affected_files_identified": 0,
        "affected_functions_traced": 0,
        "call_chains_traversed": 0,
        # Tier 2: Migration
        "migration_reports_generated": 0,
        "upgrade_simulations_run": 0,
        "auto_fix_opportunities": 0,
        # Tier 2: Remediation
        "prs_created": 0,
        "files_modified": 0,
        "imports_rewritten": 0,
        "symbols_renamed": 0,
        # Tier 3: Monitoring
        "alerts_generated": 0,
        "health_degradations_detected": 0,
        "watchlist_packages": 0,
        # Performance
        "total_analysis_time_seconds": 0,
        "analysis_count": 0,
        "success_count": 0,
        "failure_count": 0,
        "min_analysis_time": float("inf"),
        "max_analysis_time": 0,
    }

    for doc in docs:
        metric = doc.get("metric")
        if metric == "repositories_analyzed":
            vals = doc.get("values", [])
            result["repositories_analyzed"] = len(vals)
            result["unique_repositories"] = sorted(vals)
        elif metric == "analyses_performed":
            result["analyses_performed"] = doc.get("count", 0)
        elif metric == "commits_analyzed":
            result["commits_analyzed"] = doc.get("count", 0)
        elif metric == "branches_analyzed":
            result["branches_analyzed"] = sorted(doc.get("values", []))
        elif metric == "code_scale":
            for k in ("python_files_scanned", "notebooks_scanned", "functions_indexed",
                       "classes_indexed", "apis_fingerprinted", "lines_of_code_scanned"):
                result[k] = doc.get(k, 0)
        elif metric == "graph_scale":
            result["total_nodes"] = doc.get("total_nodes", 0)
            result["total_edges"] = doc.get("total_edges", 0)
            result["graph_count"] = doc.get("graph_count", 0)
            result["largest_graph_repo"] = doc.get("largest_repo", "")
            result["largest_node_count"] = doc.get("largest_node_count", 0)
            result["largest_edge_count"] = doc.get("largest_edge_count", 0)
        elif metric == "dependency_intelligence":
            for k in ("dependencies_detected", "unique_packages_seen",
                       "deprecated_apis_found", "breaking_apis_found", "migration_candidates"):
                result[k] = doc.get(k, 0)
        elif metric == "impact_analysis":
            for k in ("affected_files_identified", "affected_functions_traced", "call_chains_traversed"):
                result[k] = doc.get(k, 0)
        elif metric == "migration_metrics":
            for k in ("migration_reports_generated", "upgrade_simulations_run", "auto_fix_opportunities"):
                result[k] = doc.get(k, 0)
        elif metric == "remediation":
            for k in ("prs_created", "files_modified", "imports_rewritten", "symbols_renamed"):
                result[k] = doc.get(k, 0)
        elif metric == "monitoring":
            for k in ("alerts_generated", "health_degradations_detected", "watchlist_packages"):
                result[k] = doc.get(k, 0)
        elif metric == "performance":
            result["total_analysis_time_seconds"] = doc.get("total_analysis_time_seconds", 0)
            result["analysis_count"] = doc.get("analysis_count", 0)
            result["success_count"] = doc.get("success_count", 0)
            result["failure_count"] = doc.get("failure_count", 0)
            result["min_analysis_time"] = doc.get("min_analysis_time", 0)
            result["max_analysis_time"] = doc.get("max_analysis_time", 0)

    if result["min_analysis_time"] == float("inf"):
        result["min_analysis_time"] = 0

    # Compute derived metrics
    result["semantic_entities_indexed"] = (
        result["functions_indexed"]
        + result["classes_indexed"]
        + result["apis_fingerprinted"]
    )
    result["average_analysis_time"] = (
        round(result["total_analysis_time_seconds"] / max(result["analysis_count"], 1), 1)
    )
    result["success_rate"] = (
        round(result["success_count"] / max(result["analysis_count"], 1) * 100, 1)
    )

    return result
