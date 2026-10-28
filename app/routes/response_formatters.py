from __future__ import annotations

from typing import Any

VALID_STATUSES = {
    "success",
    "cached",
    "degraded",
    "rate_limited",
    "provider_unavailable",
    "timeout",
}

def _is_truthy_debug(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}

def is_debug_enabled(query_params: Any) -> bool:
    return _is_truthy_debug(getattr(query_params, "get", lambda _key, default=None: default)("debug", None))

def _status(payload: dict[str, Any]) -> str:
    value = payload.get("status") or payload.get("intelligence_status") or "success"
    if value == "ok":
        value = "success"
    return value if value in VALID_STATUSES else "degraded"


def format_symbol_response(payload: dict[str, Any], debug: bool = False, request_id: str | None = None) -> dict[str, Any]:
    response = {
        "library": payload.get("library"),
        "latest_version": payload.get("latest_version"),
        "intelligence_status": payload.get("intelligence_status", "ok"),
        "intelligence_reason": payload.get("intelligence_reason"),
        "results": []
    }
    if request_id is not None:
        response["status"] = _status(payload)
        response["request_id"] = request_id
    
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

def format_library_response(payload: dict[str, Any], debug: bool = False, request_id: str | None = None) -> dict[str, Any]:
    response = {
        "library": payload.get("library"),
        "latest_version": payload.get("latest_version"),
        "intelligence_status": payload.get("intelligence_status", "ok"),
        "intelligence_reason": payload.get("intelligence_reason"),
        "official_docs": payload.get("official_docs"),
        "github_repo": payload.get("github_repo"),
    }
    if request_id is not None:
        response["status"] = _status(payload)
        response["request_id"] = request_id
    if debug and "results" in payload:
        response["results"] = payload["results"]
    return response

def format_bulk_response(result_items: list[dict[str, Any]], request_id: str | None = None) -> dict[str, Any]:
    formatted_results: list[dict[str, Any]] = []
    for item in result_items:
        if isinstance(item.get("result"), dict):
            symbol_response = format_symbol_response(item["result"], request_id=request_id)
            formatted_item = {
                    "library": item["library"],
                    "latest_version": symbol_response.get("latest_version"),
                    "intelligence_status": symbol_response.get("intelligence_status", "ok"),
                    "intelligence_reason": symbol_response.get("intelligence_reason"),
                    "results": symbol_response.get("results", [])
                }
            if request_id is not None:
                formatted_item["status"] = symbol_response.get("status", "success")
                formatted_item["request_id"] = request_id
            formatted_results.append(formatted_item)
            continue

        formatted_item = {
                "library": item["library"],
                "reason": item.get("reason", "source_unavailable"),
            }
        if request_id is not None:
            formatted_item["status"] = item.get("status", "provider_unavailable")
            formatted_item["request_id"] = request_id
        formatted_results.append(formatted_item)

    statuses = {item.get("status") for item in formatted_results}
    if statuses == {"cached"}:
        overall_status = "cached"
    else:
        overall_status = "success" if statuses <= {"success", "cached"} else "degraded"
    if statuses == {"timeout"}:
        overall_status = "timeout"
    response = {"results": formatted_results}
    if request_id is not None:
        response["status"] = overall_status
        response["request_id"] = request_id
    return response
