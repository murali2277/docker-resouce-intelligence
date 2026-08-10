"""FastAPI server for DRI agent HTTP API."""

from contextlib import asynccontextmanager
from typing import Optional, Any
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, REGISTRY
from fastapi.responses import Response
import asyncio
import uvicorn

from ..utils.logger import get_logger
from ..core.storage import MetricsStorage
from ..core.aggregator import MetricsAggregator
from ..core.engine import PolicyEngine
from ..core.recommender import ResourceRecommender
from ..config import DRIConfig
from . import routes

logger = get_logger("api")


class DRIAPIServer:
    """FastAPI server for DRI agent."""

    def __init__(
        self,
        config: DRIConfig,
        storage: MetricsStorage,
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

        # Instantiate Phase 3/4 components
        self.recommender = ResourceRecommender(storage)
        # Forecaster is imported lazily to avoid hard statsmodels dep
        self.forecaster = self._create_forecaster()

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

        # CORS middleware
        if self.config.api.enable_cors:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

        # Include routes
        app.include_router(routes.router)

        # Prometheus metrics endpoint
        @app.get("/metrics")
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
        """Start the API server with uvicorn in a background thread."""
        import threading

        logger.info(
            f"Starting API server on {self.config.api.host}:{self.config.api.port}"
        )

        config = uvicorn.Config(
            app=self.app,
            host=self.config.api.host,
            port=self.config.api.port,
            log_level="info",
            access_log=False,
        )
        server = uvicorn.Server(config)
        # Let the agent's signal handlers take precedence
        server.install_signal_handlers = False

        # Run uvicorn in a dedicated thread so its internal event loop
        # doesn't interfere with the agent's asyncio.gather() loop.
        loop = asyncio.get_event_loop()
        ready = asyncio.Event()

        def _run() -> None:
            import asyncio as _asyncio
            _asyncio.run(server.serve())

        thread = threading.Thread(target=_run, daemon=True, name="uvicorn")
        thread.start()

        # Keep this coroutine alive so gather() doesn't exit
        try:
            while thread.is_alive():
                await asyncio.sleep(1)
        finally:
            server.should_exit = True
            thread.join(timeout=5)


    def get_app(self) -> FastAPI:
        """Get FastAPI application instance."""
        return self.app
