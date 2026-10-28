from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import REQUESTS_PER_MINUTE
from app.dependencies import get_migration_engine, get_operational_repository
from app.observability.repository import OperationalRepository
from app.rate_limit import limiter
from app.services.migration_engine import MigrationEngine
from app.validators.library import normalize_library_name
from app.routes.response_formatters import format_library_response, is_debug_enabled

router = APIRouter(tags=["library-intelligence"])
logger = logging.getLogger(__name__)


@router.get("/library-intelligence/{library}")
@limiter.limit(f"{REQUESTS_PER_MINUTE}/minute")
async def library_intelligence(
    library: str,
    request: Request,
    service: MigrationEngine = Depends(get_migration_engine),
    operational_repository: OperationalRepository = Depends(get_operational_repository),
) -> dict:
    normalized_library = normalize_library_name(library)
    request.state.library = normalized_library
    request.state.symbols = None
    request.state.libraries = [normalized_library]
    
    try:
        # We can just call resolve with an empty symbols list to get the library metadata
        response = await run_in_threadpool(
            service.resolve, normalized_library, [], is_debug_enabled(request.query_params)
        )
        request.state.cache_hit = response.get("status") == "cached"
        return format_library_response(
            response,
            debug=is_debug_enabled(request.query_params),
            request_id=request.state.request_id,
        )
    except Exception as exc:
        logger.exception("library-intelligence failed")
        return JSONResponse(
            status_code=500,
            content={"request_id": request.state.request_id, "status": "provider_unavailable", "reason": "library_intelligence_failed"},
        )
