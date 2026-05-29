from __future__ import annotations

import traceback

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

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
) -> ToolResponseContract | JSONResponse:
    request.state.library = payload.library
    request.state.symbols = payload.symbols
    request.state.libraries = [payload.library]

    try:
        response_payload = service.build_response_payload(payload.library, payload.symbols)
    except Exception as exc:
        print("RETRIEVAL ERROR:")
        print(exc)
        print("TRACEBACK:")
        print(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={
                "retrieval_error": exc.__class__.__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )

    try:
        validated = ToolResponseContract.model_validate(response_payload)
    except ValidationError as exc:
        print("VALIDATION ERROR:")
        print(exc)
        print("ERROR JSON:")
        print(exc.json())
        return JSONResponse(
            status_code=500,
            content={
                "validation_error": exc.errors(),
                "response": response_payload,
            },
        )

    service.cache_repository.upsert_library_payload(payload.library, payload.symbols, validated.model_dump(mode="json"))
    service.cache_repository.upsert_source_payload(payload.library, "pypi_json", {"latest_version": validated.latest_version})
    for symbol_lifecycle in validated.symbol_lifecycles:
        service.cache_repository.upsert_symbol_payload(payload.library, symbol_lifecycle.symbol, symbol_lifecycle.model_dump(mode="json"))

    request.state.cache_hit = service.last_cache_hit

    if not service.last_cache_hit:
        operational_repository.log_audit_event(
            event="cache_refresh",
            request_id=request.state.request_id,
            library=payload.library,
        )

    return validated

