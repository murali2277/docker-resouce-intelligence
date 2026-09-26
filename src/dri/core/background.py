"""
Background worker that periodically computes and caches recommendations
and forecasts for all known containers.

The worker runs in a separate asyncio task and writes results to the
RecommendationCache / ForecastCache tables in storage so that API
requests can be served from the cache in O(1) instead of recomputing
on each request.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from ..utils.logger import get_logger

if TYPE_CHECKING:
    from .storage_base import StorageBackend
    from .recommender import ResourceRecommender
    from .forecaster import MetricsForecaster
    from ..core.aggregator import MetricsAggregator

logger = get_logger("background")

# Default metrics and horizon to pre-cache for forecasts
_FORECAST_METRICS = ("cpu_percent", "memory_percent")
_FORECAST_HORIZONS = (24,)   # hours


class RecommendationCacheWorker:
    """
    Periodic background task that recomputes recommendations and forecasts
    for every container visible in the aggregator's in-memory windows and
    writes results to the storage cache tables.

    Usage::

        worker = RecommendationCacheWorker(
            storage=storage,
            aggregator=aggregator,
            recommender=recommender,
            forecaster=forecaster,
            interval_seconds=3600,
        )
        task = asyncio.create_task(worker.run())
        # ... later ...
        worker.stop()
        await task
    """

    def __init__(
        self,
        storage: "StorageBackend",
        aggregator: "MetricsAggregator",
        recommender: "ResourceRecommender",
        forecaster: Optional["MetricsForecaster"],
        interval_seconds: int = 3600,
    ) -> None:
        self.storage = storage
        self.aggregator = aggregator
        self.recommender = recommender
        self.forecaster = forecaster
        self.interval_seconds = interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def run(self) -> None:
        """Main loop — compute immediately on start, then on each interval."""
        self._running = True
        logger.info(
            f"RecommendationCacheWorker started "
            f"(interval={self.interval_seconds}s)"
        )
        # Run immediately on startup, then wait for the interval.
        while self._running:
            try:
                await self._refresh_all()
            except Exception as e:
                logger.error(f"Cache refresh error: {e}")
            if not self._running:
                break
            try:
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                break

        logger.info("RecommendationCacheWorker stopped")

    def stop(self) -> None:
        """Signal the worker to stop after the current refresh completes."""
        self._running = False

    async def _refresh_all(self) -> None:
        """Recompute recommendations and forecasts for all known containers."""
        container_ids = list(self.aggregator._windows.keys())
        if not container_ids:
            logger.debug("No containers in aggregator window — skipping cache refresh")
            return

        logger.info(f"Refreshing cache for {len(container_ids)} container(s)")
        computed_at = datetime.now(timezone.utc)

        for cid in container_ids:
            window = self.aggregator._windows.get(cid)
            cname = window[-1].container_name if window else ""

            # --- Recommendation ---
            try:
                result = await self.recommender.compute_recommendation(
                    container_id=cid,
                    container_name=cname,
                )
                # Only cache successful (non-insufficient) results
                from .recommender import Recommendation
                if isinstance(result, Recommendation):
                    await self.storage.save_recommendation_cache(
                        container_id=cid,
                        payload=result.to_dict(),
                        computed_at=computed_at,
                    )
            except Exception as e:
                logger.warning(f"Recommendation cache refresh failed for {cid}: {e}")

            # --- Forecasts ---
            if self.forecaster is not None:
                for metric in _FORECAST_METRICS:
                    for horizon in _FORECAST_HORIZONS:
                        try:
                            fr = await self.forecaster.forecast(
                                container_id=cid,
                                horizon_hours=horizon,
                                metric=metric,
                            )
                            if fr is not None:
                                from .forecaster import ForecastResult
                                if isinstance(fr, ForecastResult):
                                    await self.storage.save_forecast_cache(
                                        container_id=cid,
                                        metric=metric,
                                        horizon_hours=horizon,
                                        payload=fr.to_dict(),
                                        computed_at=computed_at,
                                    )
                        except Exception as e:
                            logger.warning(
                                f"Forecast cache refresh failed for "
                                f"{cid}/{metric}/{horizon}h: {e}"
                            )

        logger.info(f"Cache refresh complete for {len(container_ids)} container(s)")
