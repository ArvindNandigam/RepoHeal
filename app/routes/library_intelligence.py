from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.dependencies import get_library_intelligence_service, get_operational_repository
from app.rate_limit import limiter
from app.services.library_intelligence import LibraryIntelligenceService
from app.observability.repository import OperationalRepository
from app.services.source_resolver import LibraryNotFoundError, SourceUnavailableError
from app.validators.library import normalize_library_name, normalize_symbol_list
from app.routes.response_formatters import format_library_response, is_debug_enabled


router = APIRouter(tags=["library-intelligence"])


@router.post("/library-intelligence")
@limiter.limit("100/minute")
async def library_intelligence(
    request: Request,
    service: LibraryIntelligenceService = Depends(get_library_intelligence_service),
    operational_repository: OperationalRepository = Depends(get_operational_repository),
) -> dict:
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
        library = normalize_library_name(str(body.get("library", "")))
        symbols = normalize_symbol_list(body.get("symbols") or [])
    except Exception:
        return JSONResponse(status_code=400, content={"status": "failed", "reason": "failed"})

    request.state.library = library
    request.state.symbols = symbols
    request.state.libraries = [library]

    try:
        response_payload = service.resolve(library, symbols)
    except LibraryNotFoundError:
        return JSONResponse(status_code=404, content={"status": "failed", "reason": "library_not_found"})
    except SourceUnavailableError:
        return JSONResponse(status_code=503, content={"status": "failed", "reason": "source_unavailable"})
    except Exception as exc:
        operational_repository.log_error(
            request_id=request.state.request_id,
            endpoint=request.url.path,
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )
        return JSONResponse(status_code=500, content={"status": "failed", "error": str(exc)})

    request.state.cache_hit = service.last_cache_hit

    if not service.last_cache_hit:
        operational_repository.log_audit_event(
            event="cache_refresh",
            request_id=request.state.request_id,
            library=library,
        )

    return format_library_response(response_payload, debug=is_debug_enabled(request.query_params))

