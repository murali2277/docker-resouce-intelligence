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
