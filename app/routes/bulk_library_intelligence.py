from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.config import MAX_LIBRARIES_PER_REQUEST
from app.dependencies import get_library_intelligence_service, get_operational_repository
from app.observability.repository import OperationalRepository
from app.rate_limit import limiter
from app.services.library_intelligence import LibraryIntelligenceService
from app.services.source_resolver import LibraryNotFoundError, SourceUnavailableError
from app.validators.library import normalize_library_name, normalize_symbol_list
from app.routes.response_formatters import format_bulk_response


router = APIRouter(tags=["library-intelligence"])


@router.post("/bulk-library-intelligence")
@limiter.limit("100/minute")
async def bulk_library_intelligence(
    request: Request,
    service: LibraryIntelligenceService = Depends(get_library_intelligence_service),
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
    any_cache_hit = False

    results: list[dict] = []
    for item in normalized_items:
        try:
            result = service.resolve(item["library"], item["symbols"])
            request.state.cache_hit = service.last_cache_hit
            any_cache_hit = any_cache_hit or service.last_cache_hit

            if not service.last_cache_hit:
                operational_repository.log_audit_event(
                    event="cache_refresh",
                    request_id=request.state.request_id,
                    library=item["library"],
                )

            results.append(
                {
                    "library": item["library"],
                    "status": "success",
                    "result": result,
                }
            )
        except LibraryNotFoundError:
            results.append(
                {
                    "library": item["library"],
                    "status": "failed",
                    "reason": "library_not_found",
                }
            )
        except SourceUnavailableError:
            results.append(
                {
                    "library": item["library"],
                    "status": "failed",
                    "reason": "source_unavailable",
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
                    "reason": "source_unavailable",
                }
            )

    request.state.cache_hit = any_cache_hit
    return format_bulk_response(results)
