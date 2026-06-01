"""Metrics aggregator for moving averages and anomaly detection."""

import asyncio
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import statistics

from ..utils.logger import get_logger
from ..utils.metrics import ContainerMetrics, AggregatedMetrics
from .storage import MetricsStorage, MetricsSample

logger = get_logger("aggregator")


class MetricsAggregator:
    """Calculate moving averages and detect anomalies."""

    def __init__(self, storage: MetricsStorage):
        """
        Initialize aggregator.

        Args:
            storage: MetricsStorage instance for data persistence
        """
        self.storage = storage
        self._windows: Dict[str, deque] = {}  # Container ID -> metrics deque
        self._max_samples = 1000  # Max samples to keep in memory

    def _get_window(self, container_id: str) -> deque:
        """Get or create metric window for container."""
        if container_id not in self._windows:
            self._windows[container_id] = deque(maxlen=self._max_samples)
        return self._windows[container_id]

    def add_metrics(self, metrics: ContainerMetrics) -> None:
        """Add metrics sample to window."""
        window = self._get_window(metrics.container_id)
        window.append(metrics)

    def _calculate_moving_average(
        self,
        window: deque,
        minutes: int,
        field: str,
    ) -> float:
        """Calculate moving average for a metric."""
        if not window:
            return 0.0

        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        samples = [
            getattr(m, field)
            for m in window
            if m.timestamp >= cutoff
        ]

        if not samples:
            return 0.0

        return round(statistics.mean(samples), 2)

    def _calculate_growth_rate(
        self,
        window: deque,
        minutes: int,
    ) -> float:
        """
        Calculate memory growth rate (percent per minute).

        Args:
            window: Metric samples window
            minutes: Time window in minutes

        Returns:
            Growth rate as percent per minute
        """
        if len(window) < 2:
            return 0.0

        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        samples = [
            (m.timestamp, m.memory_percent)
            for m in window
            if m.timestamp >= cutoff
        ]

        if len(samples) < 2:
            return 0.0

        first = samples[0]
        last = samples[-1]
        time_delta_minutes = (last[0] - first[0]).total_seconds() / 60
        if time_delta_minutes == 0:
            return 0.0

        memory_delta = last[1] - first[1]
        return round(memory_delta / time_delta_minutes, 2)

    def _detect_anomaly(self, metrics: AggregatedMetrics) -> Tuple[bool, Optional[str]]:
        """
        Detect memory anomalies (sudden spikes).

        Args:
            metrics: Aggregated metrics

        Returns:
            Tuple of (is_anomaly, anomaly_type)
        """
        # Spike detection: sudden memory increase > 20% in 5 minutes
        if metrics.memory_growth_rate_5m > 20.0:
            return True, "memory_spike"

        # High memory with rapid growth rate
        if metrics.memory_percent > 80.0 and metrics.memory_growth_rate_1m > 10.0:
            return True, "high_memory_rapid_growth"

        # Sustained high memory
        if (
            metrics.memory_percent > 95.0 and
            metrics.memory_percent_5m > 90.0 and
            metrics.memory_percent_15m > 85.0
        ):
            return True, "sustained_high_memory"

        return False, None

    async def aggregate(self, container_id: str) -> Optional[AggregatedMetrics]:
        """
        Calculate aggregated metrics for a container.

        Args:
            container_id: Container ID

        Returns:
            AggregatedMetrics or None if insufficient data
        """
        loop = asyncio.get_event_loop()

        def _aggregate() -> Optional[AggregatedMetrics]:
            window = self._get_window(container_id)
            if not window:
                return None

            # Get latest metrics to extract container info
            latest = window[-1]

            # Calculate moving averages
            cpu_5m = self._calculate_moving_average(window, 5, "cpu_percent")
            cpu_15m = self._calculate_moving_average(window, 15, "cpu_percent")
            cpu_60m = self._calculate_moving_average(window, 60, "cpu_percent")

            mem_5m = self._calculate_moving_average(window, 5, "memory_percent")
            mem_15m = self._calculate_moving_average(window, 15, "memory_percent")
            mem_60m = self._calculate_moving_average(window, 60, "memory_percent")

            # Calculate growth rates
            growth_1m = self._calculate_growth_rate(window, 1)
            growth_5m = self._calculate_growth_rate(window, 5)

            agg_metrics = AggregatedMetrics(
                container_id=latest.container_id,
                container_name=latest.container_name,
                timestamp=latest.timestamp,
                cpu_percent=latest.cpu_percent,
                memory_percent=latest.memory_percent,
                cpu_percent_5m=cpu_5m,
                cpu_percent_15m=cpu_15m,
                cpu_percent_60m=cpu_60m,
                memory_percent_5m=mem_5m,
                memory_percent_15m=mem_15m,
                memory_percent_60m=mem_60m,
                memory_growth_rate_1m=growth_1m,
                memory_growth_rate_5m=growth_5m,
            )

            # Detect anomalies
            is_anomaly, anomaly_type = self._detect_anomaly(agg_metrics)
            agg_metrics.is_anomaly = is_anomaly
            agg_metrics.anomaly_type = anomaly_type

            return agg_metrics

        try:
            result = await loop.run_in_executor(None, _aggregate)
            return result
        except Exception as e:
            logger.error(f"Aggregation failed for {container_id}: {e}")
            return None

    async def aggregate_all(self) -> Dict[str, AggregatedMetrics]:
        """
        Aggregate metrics for all containers.

        Returns:
            Dict mapping container ID to AggregatedMetrics
        """
        results = {}
        tasks = [
            self.aggregate(container_id)
            for container_id in self._windows.keys()
        ]

        if not tasks:
            return results

        try:
            agg_list = await asyncio.gather(*tasks)
            for agg in agg_list:
                if agg:
                    results[agg.container_id] = agg
        except Exception as e:
            logger.error(f"Batch aggregation failed: {e}")

        return results

    def cleanup_old_containers(self, max_age_minutes: int = 1440) -> None:
        """Remove old container windows from memory."""
        cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        to_remove = []

        for container_id, window in self._windows.items():
            if window and window[-1].timestamp < cutoff:
                to_remove.append(container_id)

        for container_id in to_remove:
            del self._windows[container_id]
            logger.debug(f"Removed old container window: {container_id}")
