from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.dependencies import get_library_intelligence_service, get_operational_repository
from app.observability.repository import OperationalRepository
from app.rate_limit import limiter
from app.services.library_intelligence import LibraryIntelligenceService
from app.services.source_resolver import LibraryNotFoundError, SourceUnavailableError
from app.validators.library import normalize_library_name


router = APIRouter(tags=["symbol-intelligence"])


@router.post("/symbol-intelligence")
@limiter.limit("100/minute")
async def symbol_intelligence(
    request: Request,
    service: LibraryIntelligenceService = Depends(get_library_intelligence_service),
    operational_repository: OperationalRepository = Depends(get_operational_repository),
) -> dict:
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("invalid body")
        library = normalize_library_name(str(body.get("library", "")))
        symbol = str(body.get("symbol", "")).strip()
        if not symbol:
            raise ValueError("symbol is required")
    except Exception:
        return JSONResponse(status_code=400, content={"status": "failed", "reason": "contract_validation_failed"})

    request.state.library = library
    request.state.symbols = [symbol]
    request.state.libraries = [library]

    try:
        result = service.resolve_symbol(library, symbol)
    except LibraryNotFoundError:
        return JSONResponse(status_code=404, content={"status": "failed", "reason": "library_not_found"})
    except SourceUnavailableError:
        return JSONResponse(status_code=503, content={"status": "failed", "reason": "source_unavailable"})
    request.state.cache_hit = service.last_cache_hit

    if not service.last_cache_hit:
        operational_repository.log_audit_event(
            event="cache_refresh",
            request_id=request.state.request_id,
            library=library,
        )

    return result