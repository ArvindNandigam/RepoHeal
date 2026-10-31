import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi.middleware import SlowAPIMiddleware
from app.auth.session_store import session_store
from app.graph.connection import neo4j_connection
from app.utils.logger import get_logger
from app.utils.rate_limit import limiter
from app.errors.handlers import register_error_handlers
from app.routers import health, auth, dashboard, workspace, visualization, webhook, analysis, graph, reports, sse, migrations, monitoring, admin, repo_data, repo_detail, legal

logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting RepoHeal backend")
    try:
        neo4j_connection.connect()
    except Exception as neo4j_error:
        logger.warning("Neo4j unavailable during startup; graph features will be limited: %s", neo4j_error)
    session_store.cleanup_expired_sessions()

    # Phase 1/2: Recover orphaned jobs from previous crashes/restarts
    try:
        from app.worker.task_registry import recover_orphaned_jobs
        orphaned = recover_orphaned_jobs()
        if orphaned:
            logger.warning(f"Recovered {orphaned} orphaned job(s) on startup")
    except Exception as recovery_err:
        logger.warning(f"Job recovery skipped (non-fatal): {recovery_err}")

    # Phase 6: Enforce cache governance on startup
    try:
        from app.worker.task_registry import _enforce_cache_governance
        _enforce_cache_governance()
    except Exception as cache_err:
        logger.warning(f"Cache governance error on startup: {cache_err}")

    # Initialize platform metrics baseline
    try:
        from app.worker.metrics import ensure_platform_metrics_initialized
        ensure_platform_metrics_initialized()
    except Exception as metrics_err:
        logger.warning(f"Metrics initialization skipped (non-fatal): {metrics_err}")

    # Start the auto-analysis scheduler loop
    scheduler_task = None
    try:
        from app.worker.scheduler import check_due_repositories, update_all_next_runs
        update_all_next_runs()
        async def scheduler_loop():
            while True:
                try:
                    due = check_due_repositories()
                    if due:
                        logger.info(f"Auto-analysis scheduler queued {len(due)} job(s)")
                except Exception as e:
                    logger.warning(f"Scheduler check failed: {e}")
                await asyncio.sleep(300)  # check every 5 minutes
        scheduler_task = asyncio.create_task(scheduler_loop())
        logger.info("Auto-analysis scheduler started (5min interval)")
    except Exception as init_err:
        logger.warning(f"Scheduler init skipped: {init_err}")

    yield

    if scheduler_task:
        scheduler_task.cancel()
    neo4j_connection.close()
    logger.info("Shutting down RepoHeal backend")

app = FastAPI(lifespan=lifespan)

frontend_assets = dashboard.FRONTEND_DIST / "assets"
if frontend_assets.is_dir():
    app.mount("/dashboard/assets", StaticFiles(directory=frontend_assets), name="dashboard-assets")


@app.get("/favicon.svg", include_in_schema=False)
@app.get("/dashboard/favicon.svg", include_in_schema=False)
async def favicon():
    favicon_file = dashboard.FRONTEND_DIST / "favicon.svg"
    if not favicon_file.is_file():
        favicon_file = dashboard.FRONTEND_ROOT / "public" / "favicon.svg"
    if favicon_file.is_file():
        return FileResponse(favicon_file, media_type="image/svg+xml")
    return RedirectResponse(url="/dashboard")

# Middleware
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# Error Handlers
register_error_handlers(app)

# Routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(workspace.router)
app.include_router(visualization.router)
app.include_router(webhook.router)
app.include_router(analysis.router)
app.include_router(graph.router)
app.include_router(reports.router)
app.include_router(sse.router)
app.include_router(migrations.router)
app.include_router(monitoring.router)
app.include_router(admin.router)
app.include_router(repo_data.router)
app.include_router(repo_detail.router)
app.include_router(legal.router)

@app.get("/login")
async def login_redirect():
    return RedirectResponse(url="/auth/login-page")

@app.post("/github-marketplace-webhook")
async def github_marketplace_webhook(
    request: Request
):
    event = request.headers.get("X-GitHub-Event")
    delivery = request.headers.get("X-GitHub-Delivery")

    payload = await request.json()

    logger.info(
        "GitHub Marketplace event=%s delivery=%s action=%s",
        event,
        delivery,
        payload.get("action")
    )

    if event == "ping":
        return {"status": "pong"}

    return {
        "status": "accepted",
        "event": event
    }
