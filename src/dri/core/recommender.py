"""
Resource recommender: p95-based CPU/memory limit recommendations,
memory leak detection, and statistical anomaly detection helpers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List

import numpy as np

from ..utils.logger import get_logger
from .storage import MetricsStorage

logger = get_logger("recommender")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Recommendation:
    """Resource limit recommendation for a single container."""

    container_id: str
    container_name: str

    # Recommended limits (add safety margin on top of p95)
    recommended_cpu_pct: float       # percent (0-100+)
    recommended_memory_bytes: int    # bytes

    # Raw p95 values (no safety margin)
    p95_cpu: float
    p95_memory_bytes: int
    p95_memory_pct: float

    # Context
    sample_count: int
    lookback_days: int
    safety_margin: float             # e.g. 0.20 = +20%

    # Anomalies
    is_memory_leak: bool = False
    memory_leak_slope_pct_per_hour: float = 0.0

    def to_dict(self) -> dict:
        return {
            "container_id": self.container_id,
            "container_name": self.container_name,
            "recommended_cpu_pct": round(self.recommended_cpu_pct, 2),
            "recommended_memory_bytes": self.recommended_memory_bytes,
            "p95_cpu": round(self.p95_cpu, 2),
            "p95_memory_bytes": self.p95_memory_bytes,
            "p95_memory_pct": round(self.p95_memory_pct, 2),
            "sample_count": self.sample_count,
            "lookback_days": self.lookback_days,
            "safety_margin": self.safety_margin,
            "is_memory_leak": self.is_memory_leak,
            "memory_leak_slope_pct_per_hour": round(self.memory_leak_slope_pct_per_hour, 4),
        }


# ---------------------------------------------------------------------------
# Recommender
# ---------------------------------------------------------------------------


class ResourceRecommender:
    """
    Compute per-container resource limit recommendations from historical data.

    Uses a configurable lookback window and safety margin on top of p95 usage.
    Also detects sustained memory growth (leak signature) via linear regression
    on rolling 60-minute averages.
    """

    # Minimum samples required to make any recommendation
    MIN_SAMPLES = 10

    # Slope threshold (% memory per hour) above which we call it a leak
    LEAK_SLOPE_THRESHOLD = 0.5

    def __init__(self, storage: MetricsStorage) -> None:
        self.storage = storage

    async def compute_recommendation(
        self,
        container_id: str,
        container_name: str = "",
        lookback_days: int = 7,
        safety_margin: float = 0.20,
    ) -> Optional[Recommendation]:
        """
        Compute recommended CPU and memory limits for a container.

        Algorithm:
          1. Load samples from the last ``lookback_days`` days.
          2. Compute p95 of cpu_percent and memory_usage.
          3. Recommended limit = p95 * (1 + safety_margin).
          4. Run memory leak detection on the same samples.

        Args:
            container_id: Docker container short-ID.
            container_name: Human-readable name (used in the result).
            lookback_days: How many days of history to use.
            safety_margin: Fractional overhead added to p95 (default +20 %).

        Returns:
            Recommendation dataclass, or None if insufficient data.
        """
        minutes = lookback_days * 24 * 60
        loop = asyncio.get_event_loop()

        samples = await self.storage.get_recent_metrics(container_id, minutes=minutes)

        if len(samples) < self.MIN_SAMPLES:
            logger.debug(
                f"Insufficient samples for {container_id}: {len(samples)} < {self.MIN_SAMPLES}"
            )
            return None

        cpu_vals = np.array([s.cpu_percent for s in samples if s.cpu_percent is not None])
        mem_usage_vals = np.array(
            [s.memory_usage for s in samples if s.memory_usage is not None]
        )
        mem_pct_vals = np.array(
            [s.memory_percent for s in samples if s.memory_percent is not None]
        )

        if len(cpu_vals) < self.MIN_SAMPLES or len(mem_usage_vals) < self.MIN_SAMPLES:
            return None

        p95_cpu = float(np.percentile(cpu_vals, 95))
        p95_memory_bytes = int(np.percentile(mem_usage_vals, 95))
        p95_memory_pct = float(np.percentile(mem_pct_vals, 95))

        recommended_cpu_pct = p95_cpu * (1 + safety_margin)
        recommended_memory_bytes = int(p95_memory_bytes * (1 + safety_margin))

        # Memory leak detection
        is_leak, slope = self._detect_memory_leak(samples)

        return Recommendation(
            container_id=container_id,
            container_name=container_name,
            recommended_cpu_pct=recommended_cpu_pct,
            recommended_memory_bytes=recommended_memory_bytes,
            p95_cpu=p95_cpu,
            p95_memory_bytes=p95_memory_bytes,
            p95_memory_pct=p95_memory_pct,
            sample_count=len(samples),
            lookback_days=lookback_days,
            safety_margin=safety_margin,
            is_memory_leak=is_leak,
            memory_leak_slope_pct_per_hour=slope,
        )

    def _detect_memory_leak(
        self,
        samples: list,
        window_hours: float = 6.0,
    ) -> tuple[bool, float]:
        """
        Detect a sustained upward trend in memory usage.

        Strategy:
          - Use all samples within the last ``window_hours`` hours.
          - Compute x = seconds-since-start, y = memory_percent.
          - Fit a linear regression (numpy polyfit degree=1).
          - slope > LEAK_SLOPE_THRESHOLD (%/hour) → memory leak.

        Args:
            samples: List of MetricsSample objects ordered oldest-first.
            window_hours: How far back to look for the trend.

        Returns:
            Tuple of (is_leak: bool, slope_pct_per_hour: float).
        """
        if len(samples) < self.MIN_SAMPLES:
            return False, 0.0

        now = datetime.utcnow()
        cutoff = now - timedelta(hours=window_hours)
        recent = [s for s in samples if s.timestamp >= cutoff and s.memory_percent is not None]

        if len(recent) < self.MIN_SAMPLES:
            return False, 0.0

        t0 = recent[0].timestamp
        x = np.array([(s.timestamp - t0).total_seconds() / 3600.0 for s in recent])
        y = np.array([s.memory_percent for s in recent])

        try:
            coeffs = np.polyfit(x, y, 1)
        except Exception:
            return False, 0.0

        slope_per_hour = float(coeffs[0])  # % change per hour
        is_leak = slope_per_hour > self.LEAK_SLOPE_THRESHOLD

        return is_leak, slope_per_hour

    async def detect_memory_leak(
        self,
        container_id: str,
        window_hours: float = 6.0,
    ) -> tuple[bool, float]:
        """
        Public async wrapper for memory leak detection.

        Args:
            container_id: Container to analyse.
            window_hours: Trend window in hours.

        Returns:
            Tuple of (is_leak: bool, slope_pct_per_hour: float).
        """
        minutes = int(window_hours * 60) + 5  # slight buffer
        samples = await self.storage.get_recent_metrics(container_id, minutes=minutes)
        return self._detect_memory_leak(samples, window_hours=window_hours)


# ---------------------------------------------------------------------------
# Statistical anomaly helpers (used by aggregator)
# ---------------------------------------------------------------------------


def z_score_anomaly(
    values: List[float],
    current: float,
    threshold: float = 3.0,
) -> tuple[bool, float]:
    """
    Compute z-score of ``current`` against the distribution in ``values``.

    Args:
        values: Recent historical values.
        current: The value to test.
        threshold: Z-score magnitude above which we flag an anomaly.

    Returns:
        Tuple of (is_anomaly: bool, z_score: float).
    """
    if len(values) < 5:
        return False, 0.0

    arr = np.array(values, dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr))

    if std < 1e-6:
        return False, 0.0

    z = (current - mean) / std
    return abs(z) > threshold, round(z, 3)
