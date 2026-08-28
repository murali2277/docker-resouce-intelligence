"""
Resource recommender: p95-based CPU/memory limit recommendations,
memory leak detection (restart-aware), and statistical anomaly detection helpers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Union

try:
    import numpy as np
except ImportError:
    np = None


def _mean(vals: list[float]) -> float:
    if np is not None:
        return float(np.mean(vals))
    import statistics
    return statistics.mean(vals) if vals else 0.0


def _percentile(vals: list[float], p: float) -> float:
    if np is not None:
        return float(np.percentile(vals, p))
    if not vals:
        return 0.0
    sorted_vals = sorted(vals)
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_vals):
        return sorted_vals[-1]
    d0 = sorted_vals[f] * (c - k)
    d1 = sorted_vals[c] * (k - f)
    return d0 + d1

from ..utils.logger import get_logger
from .storage_base import StorageBackend

logger = get_logger("recommender")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class InsufficientDataResult:
    """
    Returned instead of None when there isn't enough history to compute a
    recommendation.  Clients can inspect ``status``, ``min_samples_required``
    and ``samples_available`` to show a meaningful message.
    """

    container_id: str
    container_name: str
    status: str = "insufficient_data"
    min_samples_required: int = 0
    samples_available: int = 0

    def to_dict(self) -> dict:
        return {
            "container_id": self.container_id,
            "container_name": self.container_name,
            "status": self.status,
            "min_samples_required": self.min_samples_required,
            "samples_available": self.samples_available,
        }


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
    lookback_actual_days: float      # actual span of available data
    safety_margin: float             # e.g. 0.20 = +20%

    # Data quality
    data_completeness: str           # e.g. "3.2 of 7.0 days available"
    confidence_tier: str             # "low" | "medium" | "high"

    # Anomalies
    is_memory_leak: bool = False
    memory_leak_slope_pct_per_hour: float = 0.0

    # Idle / scale-to-zero signal (merged from ScaleAction)
    is_idle: bool = False
    idle_recommendation: Optional[str] = None

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
            "lookback_actual_days": round(self.lookback_actual_days, 2),
            "safety_margin": self.safety_margin,
            "data_completeness": self.data_completeness,
            "confidence_tier": self.confidence_tier,
            "is_memory_leak": self.is_memory_leak,
            "memory_leak_slope_pct_per_hour": round(self.memory_leak_slope_pct_per_hour, 4),
            "is_idle": self.is_idle,
            "idle_recommendation": self.idle_recommendation,
        }


# ---------------------------------------------------------------------------
# Recommender
# ---------------------------------------------------------------------------


class ResourceRecommender:
    """
    Compute per-container resource limit recommendations from historical data.

    Uses a configurable lookback window and safety margin on top of p95 usage.
    Also detects sustained memory growth (leak signature) via linear regression
    on rolling 60-minute averages, with restart-boundary awareness.
    """

    # Minimum samples required to make any recommendation
    MIN_SAMPLES = 10

    # Slope threshold (% memory per hour) above which we call it a leak
    LEAK_SLOPE_THRESHOLD = 0.5

    # Sharp drop in memory_percent (single step) that signals a container restart
    RESTART_DROP_THRESHOLD = 15.0

    # Sample-count thresholds for confidence tiers
    CONFIDENCE_LOW_THRESHOLD = 50
    CONFIDENCE_HIGH_THRESHOLD = 300

    # Idle detection thresholds (60-minute average)
    IDLE_CPU_THRESHOLD = 1.0        # percent
    IDLE_MEMORY_THRESHOLD = 1.0     # percent

    def __init__(self, storage: StorageBackend) -> None:
        self.storage = storage

    async def compute_recommendation(
        self,
        container_id: str,
        container_name: str = "",
        lookback_days: int = 7,
        safety_margin: float = 0.20,
    ) -> Union[Recommendation, InsufficientDataResult]:
        """
        Compute recommended CPU and memory limits for a container.

        Algorithm:
          1. Load samples from the last ``lookback_days`` days.
          2. Compute p95 of cpu_percent and memory_usage.
          3. Recommended limit = p95 * (1 + safety_margin).
          4. Compute data_completeness from actual span of loaded samples.
          5. Run restart-aware memory leak detection on the same samples.
          6. Emit confidence_tier based on sample_count.
          7. Detect idle containers (scale-to-zero signal).

        Args:
            container_id: Docker container short-ID.
            container_name: Human-readable name (used in the result).
            lookback_days: How many days of history to use.
            safety_margin: Fractional overhead added to p95 (default +20 %).

        Returns:
            Recommendation dataclass on success, or InsufficientDataResult
            when there are fewer than MIN_SAMPLES data points.
        """
        minutes = lookback_days * 24 * 60

        samples = await self.storage.get_recent_metrics(container_id, minutes=minutes)

        if len(samples) < self.MIN_SAMPLES:
            logger.debug(
                f"Insufficient samples for {container_id}: "
                f"{len(samples)} < {self.MIN_SAMPLES}"
            )
            return InsufficientDataResult(
                container_id=container_id,
                container_name=container_name,
                min_samples_required=self.MIN_SAMPLES,
                samples_available=len(samples),
            )

        cpu_vals = [s.cpu_percent for s in samples if s.cpu_percent is not None]
        mem_usage_vals = [
            s.memory_usage for s in samples if s.memory_usage is not None
        ]
        mem_pct_vals = [
            s.memory_percent for s in samples if s.memory_percent is not None
        ]

        if len(cpu_vals) < self.MIN_SAMPLES or len(mem_usage_vals) < self.MIN_SAMPLES:
            return InsufficientDataResult(
                container_id=container_id,
                container_name=container_name,
                min_samples_required=self.MIN_SAMPLES,
                samples_available=min(len(cpu_vals), len(mem_usage_vals)),
            )

        p95_cpu = _percentile(cpu_vals, 95)
        p95_memory_bytes = int(_percentile(mem_usage_vals, 95))
        p95_memory_pct = _percentile(mem_pct_vals, 95)

        recommended_cpu_pct = p95_cpu * (1 + safety_margin)
        recommended_memory_bytes = int(p95_memory_bytes * (1 + safety_margin))

        # ----------------------------------------------------------------
        # Data completeness: actual span vs. requested lookback
        # ----------------------------------------------------------------
        timestamps = [s.timestamp for s in samples]
        actual_span_seconds = (max(timestamps) - min(timestamps)).total_seconds()
        actual_days = actual_span_seconds / 86400.0
        data_completeness = (
            f"{round(actual_days, 1)} of {float(lookback_days)} days available"
        )

        # ----------------------------------------------------------------
        # Confidence tier
        # ----------------------------------------------------------------
        n = len(samples)
        if n < self.CONFIDENCE_LOW_THRESHOLD:
            confidence_tier = "low"
        elif n < self.CONFIDENCE_HIGH_THRESHOLD:
            confidence_tier = "medium"
        else:
            confidence_tier = "high"

        # ----------------------------------------------------------------
        # Restart-aware memory leak detection
        # ----------------------------------------------------------------
        is_leak, slope = self._detect_memory_leak(samples)

        # ----------------------------------------------------------------
        # Idle / scale-to-zero detection (merged from ScaleAction)
        # Uses the 60-minute average of memory and CPU from the sample set
        # (last 60 min of the loaded window).
        # ----------------------------------------------------------------
        is_idle, idle_recommendation = self._detect_idle(samples)

        return Recommendation(
            container_id=container_id,
            container_name=container_name,
            recommended_cpu_pct=recommended_cpu_pct,
            recommended_memory_bytes=recommended_memory_bytes,
            p95_cpu=p95_cpu,
            p95_memory_bytes=p95_memory_bytes,
            p95_memory_pct=p95_memory_pct,
            sample_count=n,
            lookback_days=lookback_days,
            lookback_actual_days=actual_days,
            safety_margin=safety_margin,
            data_completeness=data_completeness,
            confidence_tier=confidence_tier,
            is_memory_leak=is_leak,
            memory_leak_slope_pct_per_hour=slope,
            is_idle=is_idle,
            idle_recommendation=idle_recommendation,
        )

    def _detect_idle(
        self,
        samples: list,
        window_minutes: int = 60,
    ) -> tuple[bool, Optional[str]]:
        """
        Detect containers with sustained near-zero CPU and memory usage.

        Uses the last ``window_minutes`` of the supplied samples, matching
        the ScaleAction.identify_idle_containers logic (60 m average).

        Returns:
            Tuple of (is_idle: bool, recommendation_string or None).
        """
        if not samples:
            return False, None

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=window_minutes)
        recent = [s for s in samples if s.timestamp >= cutoff]

        if len(recent) < 2:
            return False, None

        cpu_vals = [s.cpu_percent for s in recent if s.cpu_percent is not None]
        mem_vals = [s.memory_percent for s in recent if s.memory_percent is not None]

        if not cpu_vals or not mem_vals:
            return False, None

        avg_cpu = _mean(cpu_vals)
        avg_mem = _mean(mem_vals)

        if avg_cpu < self.IDLE_CPU_THRESHOLD and avg_mem < self.IDLE_MEMORY_THRESHOLD:
            return True, "scale_to_zero"

        return False, None

    def _detect_memory_leak(
        self,
        samples: list,
        window_hours: float = 6.0,
    ) -> tuple[bool, float]:
        """
        Detect a sustained upward trend in memory usage, skipping pre-restart data.
        """
        if len(samples) < self.MIN_SAMPLES:
            return False, 0.0

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cutoff = now - timedelta(hours=window_hours)
        recent = [s for s in samples if s.timestamp >= cutoff and s.memory_percent is not None]

        if len(recent) < self.MIN_SAMPLES:
            return False, 0.0

        last_restart_idx = -1
        for i in range(1, len(recent)):
            drop = recent[i - 1].memory_percent - recent[i].memory_percent
            if drop >= self.RESTART_DROP_THRESHOLD:
                last_restart_idx = i

        if last_restart_idx >= 0:
            post_restart = recent[last_restart_idx:]
            logger.debug(
                f"Restart boundary detected: discarding {last_restart_idx} pre-restart "
                f"samples; regressing on {len(post_restart)} post-restart samples."
            )
            if len(post_restart) >= self.MIN_SAMPLES:
                recent = post_restart
            else:
                return False, 0.0

        t0 = recent[0].timestamp
        x_vals = [(s.timestamp - t0).total_seconds() / 3600.0 for s in recent]
        y_vals = [s.memory_percent for s in recent]

        try:
            if np is not None:
                x = np.array(x_vals)
                y = np.array(y_vals)
                coeffs = np.polyfit(x, y, 1)
                slope_per_hour = float(coeffs[0])
            else:
                # Simple linear regression fallback
                n = len(x_vals)
                mean_x = sum(x_vals) / n
                mean_y = sum(y_vals) / n
                denom = sum((xi - mean_x) ** 2 for xi in x_vals)
                if denom < 1e-6:
                    slope_per_hour = 0.0
                else:
                    slope_per_hour = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x_vals, y_vals)) / denom
        except Exception:
            return False, 0.0

        is_leak = slope_per_hour > self.LEAK_SLOPE_THRESHOLD

        return is_leak, slope_per_hour

    async def detect_memory_leak(
        self,
        container_id: str,
        window_hours: float = 6.0,
    ) -> tuple[bool, float]:
        """
        Public async wrapper for memory leak detection.
        """
        minutes = int(window_hours * 60) + 5
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
    """
    if len(values) < 5:
        return False, 0.0

    if np is not None:
        arr = np.array(values, dtype=float)
        mean = float(np.mean(arr))
        std = float(np.std(arr))
    else:
        import statistics
        mean = statistics.mean(values)
        std = statistics.stdev(values) if len(values) > 1 else 0.0

    if std < 1e-6:
        return False, 0.0

    z = (current - mean) / std
    return abs(z) > threshold, round(z, 3)
