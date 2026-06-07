from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Thread
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import get_settings
from app.dependencies import get_knowledge_repository, get_operational_repository
from app.observability.repository import OperationalRepository
from app.rate_limit import limiter
from app.startup import initialize_runtime
from app.routes.health import router as health_router
from app.routes.bulk_library_intelligence import router as bulk_library_router
from app.routes.library_intelligence import router as library_router
from app.routes.symbol_intelligence import router as symbol_router


logger = logging.getLogger(__name__)


def _failure_response(reason: str, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"status": "failed", "reason": reason})


def _extract_bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return token or None


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Restricted Web Tool", version=settings.service_version)
    app.state.start_time = datetime.now(timezone.utc)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(health_router)
    app.include_router(library_router)
    app.include_router(bulk_library_router)
    app.include_router(symbol_router)

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = str(uuid4())
        request.state.now = datetime.now(timezone.utc)
        request.state.request_id = request_id
        request.state.cache_hit = False
        request.state.library = None
        request.state.symbols = None
        request.state.libraries = None

        operational_repository = get_operational_repository()
        start = perf_counter()

        if request.url.path != "/health":
            raw_token = _extract_bearer_token(request)
            if raw_token is None:
                response = _failure_response("unauthorized", 401)
                response.headers["X-Request-ID"] = request_id
                response.headers["X-Service-Version"] = settings.service_version
                operational_repository.log_audit_event(
                    event="authentication_failure",
                    request_id=request_id,
                    library=None,
                    details={"reason": "missing_bearer_token"},
                )
                operational_repository.log_request(
                    request_id=request_id,
                    endpoint=request.url.path,
                    library=None,
                    symbols=None,
                    cache_hit=False,
                    response_time_ms=int((perf_counter() - start) * 1000),
                    status="unauthorized",
                    libraries=None,
                )
                operational_repository.update_daily_metrics(cache_hit=False, error=True)
                return response

            authorized, api_key_name, api_key_hash = operational_repository.find_matching_api_key(raw_token)
            if not authorized:
                response = _failure_response("unauthorized", 401)
                response.headers["X-Request-ID"] = request_id
                response.headers["X-Service-Version"] = settings.service_version
                operational_repository.log_audit_event(
                    event="authentication_failure",
                    request_id=request_id,
                    library=None,
                    details={"reason": "invalid_bearer_token", "api_key_name": api_key_name},
                )
                operational_repository.log_request(
                    request_id=request_id,
                    endpoint=request.url.path,
                    library=None,
                    symbols=None,
                    cache_hit=False,
                    response_time_ms=int((perf_counter() - start) * 1000),
                    status="unauthorized",
                    libraries=None,
                )
                operational_repository.update_daily_metrics(cache_hit=False, error=True)
                return response

            request.state.api_key_name = api_key_name
            request.state.api_key_hash = api_key_hash

        try:
            response = await call_next(request)
        except Exception as exc:
            logger.exception("Unhandled request exception", exc_info=(type(exc), exc, exc.__traceback__))
            operational_repository.log_error(request_id, request.url.path, exc.__class__.__name__, str(exc))
            response = _failure_response("internal_error", 500)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Service-Version"] = settings.service_version
            operational_repository.log_request(
                request_id=request_id,
                endpoint=request.url.path,
                library=getattr(request.state, "library", None),
                symbols=getattr(request.state, "symbols", None),
                cache_hit=bool(getattr(request.state, "cache_hit", False)),
                response_time_ms=int((perf_counter() - start) * 1000),
                status="failed",
                libraries=getattr(request.state, "libraries", None),
            )
            operational_repository.update_daily_metrics(cache_hit=getattr(request.state, "cache_hit", False), error=True)
            return response
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Service-Version"] = settings.service_version

        operational_repository.log_request(
            request_id=request_id,
            endpoint=request.url.path,
            library=getattr(request.state, "library", None),
            symbols=getattr(request.state, "symbols", None),
            cache_hit=bool(getattr(request.state, "cache_hit", False)),
            response_time_ms=int((perf_counter() - start) * 1000),
            status="success" if response.status_code < 400 else "failed",
            libraries=getattr(request.state, "libraries", None),
        )
        operational_repository.update_daily_metrics(
            cache_hit=getattr(request.state, "cache_hit", False),
            error=response.status_code >= 400,
        )
        return response

    @app.exception_handler(RequestValidationError)
    def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid4()))
        operational_repository = get_operational_repository()
        operational_repository.log_error(request_id, request.url.path, exc.__class__.__name__, str(exc))
        return _failure_response("contract_validation_failed", 400)

    @app.exception_handler(Exception)
    def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid4()))
        operational_repository = get_operational_repository()
        operational_repository.log_error(request_id, request.url.path, exc.__class__.__name__, str(exc))
        logger.error("Unhandled application exception", exc_info=(type(exc), exc, exc.__traceback__))
        response = _failure_response("internal_error", 500)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Service-Version"] = settings.service_version
        return response

    @app.exception_handler(RateLimitExceeded)
    def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid4()))
        operational_repository = get_operational_repository()
        operational_repository.log_error(request_id, request.url.path, exc.__class__.__name__, str(exc))
        operational_repository.log_audit_event(
            event="rate_limit_exceeded",
            request_id=request_id,
            library=getattr(request.state, "library", None),
        )
        response = _failure_response("rate_limit_exceeded", 429)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Service-Version"] = settings.service_version
        response.headers["Retry-After"] = "60"
        return response

    @app.on_event("startup")
    def startup_event() -> None:
        background_thread = Thread(
            target=initialize_runtime,
            args=(get_operational_repository(), get_knowledge_repository(), settings),
            daemon=True,
        )
        background_thread.start()

    return app


app = create_app()
