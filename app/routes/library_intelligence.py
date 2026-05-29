from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.contracts.schemas import FailureResponseContract, RequestContract, ToolResponseContract
from app.dependencies import get_library_intelligence_service, get_operational_repository
from app.rate_limit import limiter
from app.services.library_intelligence import LibraryIntelligenceService
from app.observability.repository import OperationalRepository


router = APIRouter(tags=["library-intelligence"])


@router.post("/library-intelligence", response_model=ToolResponseContract, responses={400: {"model": FailureResponseContract}})
@limiter.limit("100/minute")
def library_intelligence(
    request: Request,
    payload: RequestContract,
    service: LibraryIntelligenceService = Depends(get_library_intelligence_service),
    operational_repository: OperationalRepository = Depends(get_operational_repository),
) -> ToolResponseContract:
    request.state.library = payload.library
    request.state.symbols = payload.symbols
    request.state.libraries = [payload.library]

    result = service.resolve(payload.library, payload.symbols)
    request.state.cache_hit = service.last_cache_hit

    if not service.last_cache_hit:
        operational_repository.log_audit_event(
            event="cache_refresh",
            request_id=request.state.request_id,
            library=payload.library,
        )

    return result

