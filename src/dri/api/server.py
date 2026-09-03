"""FastAPI server for DRI agent HTTP API."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional, Any
from fastapi import FastAPI, Request, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import generate_latest, REGISTRY
import asyncio
import uvicorn

from ..utils.logger import get_logger
from ..core.storage_base import StorageBackend
from ..core.aggregator import MetricsAggregator
from ..core.engine import PolicyEngine
from ..core.recommender import ResourceRecommender
from ..core.background import RecommendationCacheWorker
from ..config import DRIConfig
from . import routes

logger = get_logger("api")

_configured_api_key: Optional[str] = None


def set_api_key(api_key: Optional[str]) -> None:
    """Set the active API key for request authentication."""
    global _configured_api_key
    _configured_api_key = api_key


def get_api_key() -> Optional[str]:
    """Get the currently configured API key."""
    return _configured_api_key


async def verify_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-Api-Key"),
) -> Optional[str]:
    """FastAPI dependency to verify API key.

    When config.api.api_key is set, checks x_api_key against it and raises
    HTTPException(401) on mismatch or missing header.
    When config.api.api_key is None, this is a no-op.
    """
    if _configured_api_key is not None:
        if not x_api_key or x_api_key != _configured_api_key:
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing API key",
            )
    return x_api_key


class DRIAPIServer:
    """FastAPI server for DRI agent."""

    def __init__(
        self,
        config: DRIConfig,
        storage: StorageBackend,
        aggregator: MetricsAggregator,
        policy_engine: PolicyEngine,
        agent: Optional[Any] = None,
    ):
        """
        Initialize API server.

        Args:
            config: DRI configuration
            storage: Metrics storage instance
            aggregator: Metrics aggregator instance
            policy_engine: Policy engine instance
            agent: Optional DRIAgent reference for live counters
        """
        self.config = config
        self.storage = storage
        self.aggregator = aggregator
        self.policy_engine = policy_engine
        self.agent = agent

        # Configure API key authentication state
        set_api_key(config.api.api_key)

        # Instantiate Phase 3/4 components
        self.recommender = ResourceRecommender(storage)
        # Forecaster is imported lazily to avoid hard statsmodels dep
        self.forecaster = self._create_forecaster()

        # Background cache worker (Item 3)
        self.cache_worker = RecommendationCacheWorker(
            storage=storage,
            aggregator=aggregator,
            recommender=self.recommender,
            forecaster=self.forecaster,
            interval_seconds=config.recommendation_cache_interval,
        )

        self.app = self._create_app()

    def _create_forecaster(self) -> Any:
        """Lazily create forecaster, returning None if module unavailable."""
        try:
            from ..core.forecaster import MetricsForecaster
            return MetricsForecaster(self.storage)
        except ImportError:
            logger.warning("forecaster module not available — /forecast endpoint will return 503")
            return None

    def _create_app(self) -> FastAPI:
        """Create FastAPI application."""

        # Inject dependencies eagerly so routes are ready before first request
        routes.set_dependencies(
            self.storage,
            self.aggregator,
            self.policy_engine,
            self.agent,
            self.recommender,
            self.forecaster,
            self.config,
        )

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            logger.info("API server ready")
            yield
            logger.info("API server stopping...")

        app = FastAPI(
            title="Docker Resource Intelligence API",
            description="Monitoring and self-healing agent for Docker containers",
            version="0.1.0",
            lifespan=lifespan,
        )

        # ------------------------------------------------------------------
        # Global exception handler — returns ErrorResponse JSON on any
        # unhandled exception so clients always get a structured error body
        # instead of a bare 500 HTML traceback.
        # ------------------------------------------------------------------
        @app.exception_handler(Exception)
        async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
            logger.error(
                f"Unhandled exception on {request.method} {request.url.path}: "
                f"{type(exc).__name__}: {exc}"
            )
            return JSONResponse(
                status_code=500,
                content={
                    "status_code": 500,
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        # CORS middleware
        if self.config.api.enable_cors:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=self.config.api.allowed_origins,
                allow_credentials=self.config.api.allowed_origins != ["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            )

        # Include unauthenticated public router (health checks)
        app.include_router(routes.health_router)

        # Include protected API routes with API key verification dependency
        app.include_router(routes.router, dependencies=[Depends(verify_api_key)])

        # Health alias at /health (unauthenticated)
        @app.get("/health", response_model=routes.HealthCheckResponse, tags=["health"])
        async def root_health_check() -> routes.HealthCheckResponse:
            """Root health check endpoint (unauthenticated for liveness probes)."""
            return await routes.health_check()

        # Prometheus metrics endpoint (protected by API key when configured)
        @app.get("/metrics", dependencies=[Depends(verify_api_key)])
        async def prometheus_metrics() -> Response:
            """Prometheus metrics endpoint."""
            return Response(
                content=generate_latest(REGISTRY),
                media_type="text/plain",
            )

        # Root endpoint
        @app.get("/")
        async def root():
            """Root endpoint."""
            return {
                "name": "Docker Resource Intelligence",
                "version": "0.1.0",
                "docs": "/docs",
                "health": "/api/v1/health",
                "endpoints": [
                    "/api/v1/health",
                    "/api/v1/metrics",
                    "/api/v1/alerts",
                    "/api/v1/actions/history",
                    "/api/v1/policies",
                    "/api/v1/recommendations",
                    "/api/v1/forecast/{container_id}",
                ],
            }

        return app

    async def start(self) -> None:
        """Start the API server in a thread, sharing the running event loop.

        Uses loop.run_in_executor to run uvicorn.run() (the synchronous
        entrypoint) in a ThreadPoolExecutor thread.  This avoids both:
          - Nested event loops (asyncio.run() inside a thread)
          - Blocking asyncio.gather() (await server.serve() deadlocks startup)

        The thread shares the process so uvicorn can reach FastAPI routes
        which reference the aggregator/storage objects set up in the main loop.
        """
        import threading

        logger.info(
            f"Starting API server on {self.config.api.host}:{self.config.api.port}"
        )

        def _run_uvicorn() -> None:
            uvicorn.run(
                self.app,
                host=self.config.api.host,
                port=self.config.api.port,
                log_level="info",
                access_log=False,
            )

        thread = threading.Thread(target=_run_uvicorn, daemon=True, name="uvicorn")
        thread.start()
        logger.info("API server thread started")

        # Yield control back to asyncio.gather() so all other coroutines
        # (collector, aggregator, etc.) can run while uvicorn serves requests.
        while thread.is_alive():
            await asyncio.sleep(1)

    def get_app(self) -> FastAPI:
        """Get FastAPI application instance."""
        return self.app
