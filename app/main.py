from contextlib import asynccontextmanager
from fastapi import FastAPI
from slowapi.middleware import SlowAPIMiddleware
from app.auth.session_store import session_store
from app.graph.connection import neo4j_connection
from app.utils.logger import get_logger
from app.utils.rate_limit import limiter
from app.errors.handlers import register_error_handlers
from app.routers import health, auth, dashboard, workspace, visualization, webhook, analysis, graph, reports, sse, migrations, monitoring

logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting RepoHeal backend")
    neo4j_connection.connect()
    session_store.cleanup_expired_sessions()
    yield
    neo4j_connection.close()
    logger.info("Shutting down RepoHeal backend")

app = FastAPI(lifespan=lifespan)

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
