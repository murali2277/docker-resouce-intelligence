"""Pydantic models for HTTP API responses."""

from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class MetricsResponse(BaseModel):
    """Current container metrics response."""
    container_id: str
    container_name: str
    timestamp: datetime
    cpu_percent: float
    cpu_percent_5m: float
    cpu_percent_15m: float
    cpu_percent_60m: float
    memory_percent: float
    memory_percent_5m: float
    memory_percent_15m: float
    memory_percent_60m: float
    memory_growth_rate_1m: float
    memory_growth_rate_5m: float
    is_anomaly: bool = False
    anomaly_type: Optional[str] = None
    # Container lifecycle status surfaced from MetricsAggregator._stopped_at.
    # "running" while the container is live; "stopped" after the status-poll
    # loop detects it is no longer in the running set.
    # Defaults to "running" for backward compatibility with existing consumers.
    container_status: str = "running"
    net_io_in: int = 0
    net_io_out: int = 0
    block_io_read: int = 0
    block_io_write: int = 0
    pids: int = 0
    restart_count: int = 0


class ContainerMetricsListResponse(BaseModel):
    """List of container metrics."""
    timestamp: datetime
    containers: List[MetricsResponse]
    total_count: int


class AlertResponse(BaseModel):
    """Alert response."""
    alert_id: str
    container_id: str
    container_name: str
    timestamp: datetime
    alert_type: str
    metric: str
    current_value: float
    threshold: float
    message: str
    acknowledged: bool


class AlertsResponse(BaseModel):
    """List of alerts."""
    timestamp: datetime
    alerts: List[AlertResponse]
    total_count: int


class ActionHistoryResponse(BaseModel):
    """Action history record."""
    action_id: str
    container_id: str
    container_name: str
    timestamp: datetime
    action_type: str
    reason: str
    success: bool
    error_message: Optional[str] = None


class ActionHistoryListResponse(BaseModel):
    """List of action history."""
    timestamp: datetime
    actions: List[ActionHistoryResponse]
    total_count: int


class EventResponse(BaseModel):
    """Docker event response."""
    id: str
    container_id: str
    container_name: str
    event_type: str
    action: str
    timestamp: datetime
    attributes: Dict[str, Any] = Field(default_factory=dict)


class EventsResponse(BaseModel):
    """List of Docker events."""
    timestamp: datetime
    events: List[EventResponse]
    total_count: int


class PolicyResponse(BaseModel):
    """Policy rule response."""
    name: str
    enabled: bool
    selector: Dict[str, str]
    rules: List[Dict[str, Any]]


class PoliciesResponse(BaseModel):
    """List of policies."""
    timestamp: datetime
    policies: List[PolicyResponse]
    total_count: int


class HealthCheckResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    version: str
    timestamp: datetime
    uptime_seconds: float
    metrics_processed: int
    alerts_generated: int
    actions_executed: int


class ErrorResponse(BaseModel):
    """Error response."""
    status_code: int
    error: str
    message: str
    timestamp: datetime


# ---------------------------------------------------------------------------
# Phase 3: Recommendations
# ---------------------------------------------------------------------------

class RecommendationResponse(BaseModel):
    """Resource limit recommendation for a single container."""
    container_id: str
    container_name: str
    recommended_cpu_pct: float = Field(
        description="Recommended CPU limit as % (p95 + safety margin)"
    )
    recommended_memory_bytes: int = Field(
        description="Recommended memory limit in bytes"
    )
    p95_cpu: float
    p95_memory_bytes: int
    p95_memory_pct: float

    # Data quality / completeness signals
    sample_count: int
    lookback_days: int
    lookback_actual_days: float = Field(
        description="Actual span of available data in days"
    )
    safety_margin: float
    data_completeness: Optional[str] = Field(
        None,
        description='e.g. "3.2 of 7.0 days available"',
    )
    confidence_tier: str = Field(
        "low",
        description='"low" (<50 samples), "medium" (<300), or "high" (>=300)',
    )

    # Memory anomalies
    is_memory_leak: bool = False
    memory_leak_slope_pct_per_hour: float = 0.0

    # Idle / scale-to-zero signal (merged from ScaleAction)
    is_idle: bool = False
    idle_recommendation: Optional[str] = None

    # Cache metadata — present when served from background cache
    computed_at: Optional[datetime] = None


class RecommendationsListResponse(BaseModel):
    """List of per-container resource recommendations."""
    timestamp: datetime
    recommendations: List[RecommendationResponse]
    total_count: int


# ---------------------------------------------------------------------------
# Insufficient-data response
# ---------------------------------------------------------------------------

class InsufficientDataResponse(BaseModel):
    """Returned for containers where there is not enough history yet."""
    container_id: str
    container_name: str = ""
    status: str = "insufficient_data"
    min_samples_required: int
    samples_available: int


# ---------------------------------------------------------------------------
# Phase 4: Forecasting
# ---------------------------------------------------------------------------

class ForecastResponse(BaseModel):
    """Resource usage forecast for a container."""
    container_id: str
    metric: str = Field(description="'cpu_percent' or 'memory_percent'")
    horizon_hours: int
    current_value: float
    predicted_value: float
    confidence_low: float
    confidence_high: float
    predicted_at: datetime
    method_used: str = Field(description="'linear_regression' or 'ses'")
    sample_count: int

    # Cache metadata — present when served from background cache
    computed_at: Optional[datetime] = None
