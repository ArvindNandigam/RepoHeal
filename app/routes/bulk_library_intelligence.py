from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.config import MAX_LIBRARIES_PER_REQUEST
from app.dependencies import get_migration_engine, get_operational_repository
from app.observability.repository import OperationalRepository
from app.rate_limit import limiter
from app.services.migration_engine import MigrationEngine
from app.validators.library import normalize_library_name, normalize_symbol_list
from app.routes.response_formatters import format_bulk_response, is_debug_enabled


router = APIRouter(tags=["library-intelligence"])


@router.post("/bulk-library-intelligence")
@limiter.limit("3000/minute")
async def bulk_library_intelligence(
    request: Request,
    service: MigrationEngine = Depends(get_migration_engine),
    operational_repository: OperationalRepository = Depends(get_operational_repository),
) -> dict:
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
        libraries_payload = body.get("libraries")
        if not isinstance(libraries_payload, list):
            libraries_payload = []
        if len(libraries_payload) > MAX_LIBRARIES_PER_REQUEST:
            return JSONResponse(status_code=400, content={"status": "failed", "reason": "too_many_libraries"})

        normalized_items: list[dict[str, list[str] | str]] = []
        for item in libraries_payload:
            if not isinstance(item, dict):
                continue
            normalized_items.append(
                {
                    "library": normalize_library_name(str(item.get("library", ""))),
                    "symbols": normalize_symbol_list(item.get("symbols") or []),
                }
            )
    except Exception:
        return JSONResponse(status_code=400, content={"status": "failed", "reason": "failed"})

    request.state.library = "bulk"
    request.state.libraries = [item["library"] for item in normalized_items]
    request.state.symbols = None

    results: list[dict] = []
    debug = is_debug_enabled(request.query_params)
    try:
        for item in normalized_items:
            try:
                result = service.resolve(item["library"], item["symbols"], debug=debug)
                results.append(
                    {
                        "library": item["library"],
                        "status": "success",
                        "result": result,
                    }
                )
            except Exception as exc:
                operational_repository.log_error(
                    request_id=request.state.request_id,
                    endpoint=request.url.path,
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                )
                results.append(
                    {
                        "library": item["library"],
                        "status": "failed",
                        "reason": "failed",
                    }
                )
    except Exception as exc:
        operational_repository.log_error(
            request_id=request.state.request_id,
            endpoint=request.url.path,
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )
        return JSONResponse(status_code=500, content={"status": "failed", "error": str(exc)})

    return format_bulk_response(results)
