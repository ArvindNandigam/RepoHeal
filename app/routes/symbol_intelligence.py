from __future__ import annotations

import logging
import traceback
from collections.abc import Sequence

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.config import MAX_SYMBOLS_PER_REQUEST
from app.dependencies import get_library_intelligence_service, get_operational_repository
from app.observability.repository import OperationalRepository
from app.rate_limit import limiter
from app.services.library_intelligence import LibraryIntelligenceService
from app.services.source_resolver import LibraryNotFoundError, SourceUnavailableError
from app.validators.library import normalize_library_name
from app.routes.response_formatters import format_symbol_response, is_debug_enabled


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


def _safe_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _symbol_summary(payload: dict[str, object], step: str = "completed") -> dict[str, object]:
    symbols = payload.get("symbols") if isinstance(payload.get("symbols"), list) else []
    evidence_found = 0
    versions_found = 0
    for symbol_entry in symbols:
        if not isinstance(symbol_entry, dict):
            continue
        evidence = symbol_entry.get("evidence") if isinstance(symbol_entry.get("evidence"), list) else []
        versions = symbol_entry.get("versions_observed") if isinstance(symbol_entry.get("versions_observed"), list) else []
        evidence_found += len(evidence)
        versions_found += len(versions)
    return {"status": "ok", "step": step, "versions_found": versions_found, "evidence_found": evidence_found}


async def _resolve_symbol_intelligence(
    request: Request,
    service: LibraryIntelligenceService,
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
            return JSONResponse(status_code=400, content={"status": "failed", "reason": "too_many_symbols"})
        logger.info("Library=%s", library)
        logger.info("Symbols=%s", symbols)
    except Exception:
        logger.exception("symbol-intelligence failed")
        if debug:
            return JSONResponse(
                status_code=500,
                content={"status": "failed", "error": "failed to parse request", "traceback": traceback.format_exc()},
            )
        raise

    if not symbols:
        return JSONResponse(status_code=400, content={"status": "failed", "reason": "failed"})

    request.state.library = library
    request.state.symbols = symbols
    request.state.libraries = [library]

    try:
        logger.info("Resolving library metadata")
        result = service.resolve(library, symbols)

        logger.info("Fetching release history")
        release_history = _safe_list(result.get("release_history"))
        result["release_history"] = release_history

        logger.info("Fetching migration guides")
        migration_guides = _safe_list(result.get("migration_guides"))
        result["migration_guides"] = migration_guides

        logger.info("Collecting symbol evidence")
        symbol_lifecycles = _safe_list(result.get("symbol_lifecycles"))
        result["symbol_lifecycles"] = symbol_lifecycles

        logger.info("Building response")
        response = format_symbol_response(result, debug=debug, cache_hit=service.last_cache_hit)
    except LibraryNotFoundError:
        return JSONResponse(status_code=404, content={"status": "failed", "reason": "library_not_found"})
    except SourceUnavailableError:
        return JSONResponse(status_code=503, content={"status": "failed", "reason": "source_unavailable"})
    except Exception:
        logger.exception("symbol-intelligence failed")
        if debug:
            return JSONResponse(
                status_code=500,
                content={"status": "failed", "error": "symbol-intelligence failed", "traceback": traceback.format_exc()},
            )
        return JSONResponse(status_code=500, content={"status": "failed", "error": "symbol-intelligence failed"})

    request.state.cache_hit = service.last_cache_hit

    if not service.last_cache_hit:
        operational_repository.log_audit_event(
            event="cache_refresh",
            request_id=request.state.request_id,
            library=library,
        )

    return response


@router.post("/symbol-intelligence")
@limiter.limit("100/minute")
async def symbol_intelligence(
    request: Request,
    service: LibraryIntelligenceService = Depends(get_library_intelligence_service),
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
        return JSONResponse(status_code=500, content={"status": "failed", "error": "symbol-intelligence failed"})


@router.post("/debug-symbol-intelligence")
@limiter.limit("100/minute")
async def debug_symbol_intelligence(
    request: Request,
    service: LibraryIntelligenceService = Depends(get_library_intelligence_service),
    operational_repository: OperationalRepository = Depends(get_operational_repository),
) -> JSONResponse:
    try:
        response = await _resolve_symbol_intelligence(request, service, operational_repository, debug=True)
        if isinstance(response, JSONResponse):
            return JSONResponse(status_code=200, content={"status": "ok", "step": "error", "versions_found": 0, "evidence_found": 0})
        return JSONResponse(status_code=200, content=_symbol_summary(response, step="completed"))
    except Exception as e:
        return JSONResponse(status_code=200, content={"status": "ok", "step": "error", "versions_found": 0, "evidence_found": 0, "error": str(e)})