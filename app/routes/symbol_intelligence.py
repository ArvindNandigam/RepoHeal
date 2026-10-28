from __future__ import annotations

import logging
from collections.abc import Sequence

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import REQUESTS_PER_MINUTE
from app.config import MAX_SYMBOLS_PER_REQUEST
from app.dependencies import get_migration_engine, get_operational_repository
from app.observability.repository import OperationalRepository
from app.rate_limit import limiter
from app.services.migration_engine import MigrationEngine
from app.validators.library import normalize_library_name
from app.routes.response_formatters import is_debug_enabled, format_symbol_response


router = APIRouter(tags=["symbol-intelligence"])
logger = logging.getLogger(__name__)


def _extract_symbols(body: dict) -> list[str]:
    raw_symbol = body.get("symbol")
    if isinstance(raw_symbol, str) and raw_symbol.strip():
        return [raw_symbol.strip()]

    raw_symbols = body.get("symbols")
    if isinstance(raw_symbols, Sequence) and not isinstance(raw_symbols, (str, bytes)):
        symbols = [str(symbol).strip() for symbol in raw_symbols if str(symbol).strip()]
        if symbols:
            return symbols

    return []


async def _resolve_symbol_intelligence(
    request: Request,
    service: MigrationEngine,
    operational_repository: OperationalRepository,
    debug: bool,
) -> JSONResponse | dict:
    logger.info("Starting symbol intelligence")
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
        library = normalize_library_name(str(body.get("library", "")))
        symbols = _extract_symbols(body)
        if len(symbols) > MAX_SYMBOLS_PER_REQUEST:
            return JSONResponse(status_code=400, content={"request_id": request.state.request_id, "status": "degraded", "reason": "too_many_symbols"})
        logger.info("Library=%s", library)
        logger.info("Symbols=%s", symbols)
    except Exception:
        logger.exception("symbol-intelligence failed")
        return JSONResponse(
            status_code=500,
            content={
                "request_id": request.state.request_id,
                "status": "provider_unavailable",
                "reason": "failed_to_parse_request",
            },
        )

    if not symbols:
        return JSONResponse(status_code=400, content={"request_id": request.state.request_id, "status": "degraded", "reason": "invalid_symbols"})

    request.state.library = library
    request.state.symbols = symbols
    request.state.libraries = [library]

    try:
        logger.info("Resolving symbol intelligence via MigrationEngine")
        response = await run_in_threadpool(service.resolve, library, symbols, debug)
    except Exception:
        logger.exception("symbol-intelligence failed")
        return JSONResponse(
            status_code=500,
            content={"request_id": request.state.request_id, "status": "provider_unavailable", "reason": "symbol_intelligence_failed"},
        )

    request.state.cache_hit = response.get("status") == "cached"

    return format_symbol_response(response, debug=debug, request_id=request.state.request_id)


@router.post("/symbol-intelligence")
@limiter.limit(f"{REQUESTS_PER_MINUTE}/minute")
async def symbol_intelligence(
    request: Request,
    service: MigrationEngine = Depends(get_migration_engine),
    operational_repository: OperationalRepository = Depends(get_operational_repository),
) -> dict:
    try:
        response = await _resolve_symbol_intelligence(
            request,
            service,
            operational_repository,
            debug=is_debug_enabled(request.query_params),
        )
        if isinstance(response, JSONResponse):
            return response
        return response
    except Exception:
        logger.exception("symbol-intelligence failed")
        return JSONResponse(
            status_code=500,
            content={"request_id": request.state.request_id, "status": "provider_unavailable", "reason": "symbol_intelligence_failed"},
        )


@router.post("/debug-symbol-intelligence")
@limiter.limit(f"{REQUESTS_PER_MINUTE}/minute")
async def debug_symbol_intelligence(
    request: Request,
    service: MigrationEngine = Depends(get_migration_engine),
    operational_repository: OperationalRepository = Depends(get_operational_repository),
) -> JSONResponse:
    try:
        response = await _resolve_symbol_intelligence(request, service, operational_repository, debug=True)
        if isinstance(response, JSONResponse):
            return response
        return JSONResponse(status_code=200, content=response)
    except Exception:
        logger.exception("debug-symbol-intelligence failed")
        return JSONResponse(
            status_code=500,
            content={
                "request_id": request.state.request_id,
                "status": "provider_unavailable",
                "reason": "debug_symbol_intelligence_failed",
            },
        )
