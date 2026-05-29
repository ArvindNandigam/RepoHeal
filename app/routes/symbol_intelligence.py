from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.contracts.schemas import FailureResponseContract, SymbolIntelligenceRequestContract, SymbolIntelligenceResponseContract
from app.dependencies import get_library_intelligence_service, get_operational_repository
from app.observability.repository import OperationalRepository
from app.rate_limit import limiter
from app.services.library_intelligence import LibraryIntelligenceService


router = APIRouter(tags=["symbol-intelligence"])


@router.post("/symbol-intelligence", response_model=SymbolIntelligenceResponseContract, responses={400: {"model": FailureResponseContract}})
@limiter.limit("100/minute")
def symbol_intelligence(
    request: Request,
    payload: SymbolIntelligenceRequestContract,
    service: LibraryIntelligenceService = Depends(get_library_intelligence_service),
    operational_repository: OperationalRepository = Depends(get_operational_repository),
) -> SymbolIntelligenceResponseContract:
    request.state.library = payload.library
    request.state.symbols = [payload.symbol]
    request.state.libraries = [payload.library]

    result = service.resolve_symbol(payload.library, payload.symbol)
    request.state.cache_hit = service.last_cache_hit

    if not service.last_cache_hit:
        operational_repository.log_audit_event(
            event="cache_refresh",
            request_id=request.state.request_id,
            library=payload.library,
        )

    return SymbolIntelligenceResponseContract.model_validate(result)