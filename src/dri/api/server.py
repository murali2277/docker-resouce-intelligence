"""FastAPI server for DRI agent HTTP API."""

from contextlib import asynccontextmanager
from typing import Optional, Any
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, REGISTRY
from fastapi.responses import Response
import asyncio

from ..utils.logger import get_logger
from ..core.storage import MetricsStorage
from ..core.aggregator import MetricsAggregator
from ..core.engine import PolicyEngine
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
        agent: "Any" = None,
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
        self.app = self._create_app()

    def _create_app(self) -> FastAPI:
        """Create FastAPI application."""

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            logger.info("API server starting...")
            # Inject dependencies into routes
            routes.set_dependencies(self.storage, self.aggregator, self.policy_engine, self.agent)
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
            }

        return app

    async def start(self) -> None:
        """Start the API server."""
        try:
            logger.info(
                f"Starting API server on {self.config.api.host}:{self.config.api.port}"
            )
            # This is typically run with uvicorn in production
            # For development, use: uvicorn app:app --reload
        except Exception as e:
            logger.error(f"Failed to start API server: {e}")
            raise

    def get_app(self) -> FastAPI:
        """Get FastAPI application instance."""
        return self.app
