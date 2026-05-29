from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.contracts.schemas import BulkLibraryRequestContract
from app.config import MAX_LIBRARIES_PER_REQUEST
from app.dependencies import get_library_intelligence_service, get_operational_repository
from app.observability.repository import OperationalRepository
from app.rate_limit import limiter
from app.services.library_intelligence import LibraryIntelligenceService


router = APIRouter(tags=["library-intelligence"])


@router.post("/bulk-library-intelligence")
@limiter.limit("100/minute")
def bulk_library_intelligence(
    request: Request,
    payload: BulkLibraryRequestContract,
    service: LibraryIntelligenceService = Depends(get_library_intelligence_service),
    operational_repository: OperationalRepository = Depends(get_operational_repository),
) -> dict:
    if len(payload.libraries) > MAX_LIBRARIES_PER_REQUEST:
        raise ValueError("too_many_libraries")

    request.state.library = "bulk"
    request.state.libraries = [item.library for item in payload.libraries]
    request.state.symbols = None
    any_cache_hit = False

    results: list[dict] = []
    for item in payload.libraries:
        try:
            result = service.resolve(item.library, item.symbols)
            request.state.cache_hit = service.last_cache_hit
            any_cache_hit = any_cache_hit or service.last_cache_hit

            if not service.last_cache_hit:
                operational_repository.log_audit_event(
                    event="cache_refresh",
                    request_id=request.state.request_id,
                    library=item.library,
                )

            results.append(
                    {
                    library=item.library,
                    status="success",
                    result=result,
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
                        "library": item.library,
                        "status": "failed",
                        "reason": "contract_validation_failed",
                    }
            )

    request.state.cache_hit = any_cache_hit
        return {"results": results}
