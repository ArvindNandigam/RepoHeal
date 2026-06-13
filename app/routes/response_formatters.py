from __future__ import annotations

from typing import Any

def _is_truthy_debug(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}

def is_debug_enabled(query_params: Any) -> bool:
    return _is_truthy_debug(getattr(query_params, "get", lambda _key, default=None: default)("debug", None))

def format_symbol_response(payload: dict[str, Any], debug: bool = False) -> dict[str, Any]:
    # payload is already essentially in the right shape from MigrationEngine
    response = {
        "library": payload.get("library"),
        "latest_version": payload.get("latest_version"),
        "intelligence_status": payload.get("intelligence_status", "ok"),
        "intelligence_reason": payload.get("intelligence_reason"),
        "results": []
    }
    
    for result in payload.get("results", []):
        formatted_result = {
            "symbol": result.get("symbol"),
            "known": result.get("known", False),
            "relationships": []
        }
        
        for rel in result.get("relationships", []):
            formatted_rel = {
                "relation": rel.get("relation"),
                "target": rel.get("to"),
                "status": rel.get("status"),
                "confidence": rel.get("confidence"),
            }
            formatted_result["relationships"].append(formatted_rel)
            
        if debug and "_debug" in result:
            formatted_result["_debug"] = result["_debug"]
            
        response["results"].append(formatted_result)
        
    return response

def format_library_response(payload: dict[str, Any], debug: bool = False) -> dict[str, Any]:
    response = {
        "library": payload.get("library"),
        "latest_version": payload.get("latest_version"),
        "intelligence_status": payload.get("intelligence_status", "ok"),
        "intelligence_reason": payload.get("intelligence_reason"),
        "official_docs": payload.get("official_docs"),
        "github_repo": payload.get("github_repo"),
    }
    if debug and "results" in payload:
        response["results"] = payload["results"]
    return response

def format_bulk_response(result_items: list[dict[str, Any]]) -> dict[str, Any]:
    formatted_results: list[dict[str, Any]] = []
    for item in result_items:
        if item.get("status") == "success" and isinstance(item.get("result"), dict):
            symbol_response = format_symbol_response(item["result"])
            formatted_results.append(
                {
                    "library": item["library"],
                    "latest_version": symbol_response.get("latest_version"),
                    "intelligence_status": symbol_response.get("intelligence_status", "ok"),
                    "intelligence_reason": symbol_response.get("intelligence_reason"),
                    "results": symbol_response.get("results", [])
                }
            )
            continue

        formatted_results.append(
            {
                "library": item["library"],
                "status": item.get("status", "failed"),
                "reason": item.get("reason", "source_unavailable"),
            }
        )

    return {"results": formatted_results}
