"""FastAPI routes for DRI agent HTTP API."""

from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from prometheus_client import Counter, Histogram
import time

from ..core.storage import MetricsStorage
from ..core.aggregator import MetricsAggregator
from ..core.engine import PolicyEngine
from .models import (
    MetricsResponse,
    ContainerMetricsListResponse,
    AlertsResponse,
    ActionHistoryListResponse,
    PoliciesResponse,
    HealthCheckResponse,
)

router = APIRouter(prefix="/api/v1", tags=["metrics"])

# Metrics for monitoring the agent itself
metrics_requests = Counter(
    "dri_api_requests_total",
    "Total API requests",
    ["method", "endpoint"],
)
metrics_latency = Histogram(
    "dri_api_request_duration_seconds",
    "API request latency",
    ["endpoint"],
)

# References (will be injected by server)
storage: Optional[MetricsStorage] = None
aggregator: Optional[MetricsAggregator] = None
policy_engine: Optional[PolicyEngine] = None
start_time: float = time.time()


def set_dependencies(
    s: MetricsStorage,
    a: MetricsAggregator,
    pe: PolicyEngine,
) -> None:
    """Inject dependencies into routes."""
    global storage, aggregator, policy_engine
    storage = s
    aggregator = a
    policy_engine = pe


@router.get("/health", response_model=HealthCheckResponse)
async def health_check() -> HealthCheckResponse:
    """Health check endpoint."""
    metrics_requests.labels(method="GET", endpoint="health").inc()

    with metrics_latency.labels(endpoint="health").time():
        uptime = time.time() - start_time
        return HealthCheckResponse(
            status="healthy",
            version="0.1.0",
            timestamp=datetime.utcnow(),
            uptime_seconds=uptime,
            metrics_processed=0,  # TODO: track this
            alerts_generated=0,  # TODO: track this
            actions_executed=0,  # TODO: track this
        )


@router.get("/metrics", response_model=ContainerMetricsListResponse)
async def get_metrics(
    container_id: Optional[str] = Query(None),
) -> ContainerMetricsListResponse:
    """
    Get current container metrics.

    Query Parameters:
        container_id: Optional container ID to filter
    """
    metrics_requests.labels(method="GET", endpoint="metrics").inc()

    with metrics_latency.labels(endpoint="metrics").time():
        if not aggregator:
            raise HTTPException(status_code=500, detail="Aggregator not initialized")

        # Get all aggregated metrics
        all_metrics = await aggregator.aggregate_all()

        # Filter if container_id specified
        if container_id and container_id in all_metrics:
            metrics_list = [all_metrics[container_id]]
        else:
            metrics_list = list(all_metrics.values())

        # Convert to response models
        metric_responses = [
            MetricsResponse(**m.to_dict())
            for m in metrics_list
        ]

        return ContainerMetricsListResponse(
            timestamp=datetime.utcnow(),
            containers=metric_responses,
            total_count=len(metric_responses),
        )


@router.get("/alerts", response_model=AlertsResponse)
async def get_alerts(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> AlertsResponse:
    """
    Get recent alerts.

    Query Parameters:
        limit: Max number of alerts to return (default 100)
        offset: Offset for pagination (default 0)
    """
    metrics_requests.labels(method="GET", endpoint="alerts").inc()

    with metrics_latency.labels(endpoint="alerts").time():
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not initialized")

        # TODO: Implement alert retrieval from storage
        return AlertsResponse(
            timestamp=datetime.utcnow(),
            alerts=[],
            total_count=0,
        )


@router.get("/actions/history", response_model=ActionHistoryListResponse)
async def get_action_history(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> ActionHistoryListResponse:
    """
    Get action execution history.

    Query Parameters:
        limit: Max number of records (default 100)
        offset: Offset for pagination (default 0)
    """
    metrics_requests.labels(method="GET", endpoint="actions_history").inc()

    with metrics_latency.labels(endpoint="actions_history").time():
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not initialized")

        # TODO: Implement action history retrieval from storage
        return ActionHistoryListResponse(
            timestamp=datetime.utcnow(),
            actions=[],
            total_count=0,
        )


@router.get("/policies", response_model=PoliciesResponse)
async def get_policies() -> PoliciesResponse:
    """Get current policies."""
    metrics_requests.labels(method="GET", endpoint="policies").inc()

    with metrics_latency.labels(endpoint="policies").time():
        if not policy_engine:
            raise HTTPException(status_code=500, detail="Policy engine not initialized")

        # Build policy responses
        policies = []

        # Add global policy
        global_policy = policy_engine.config.global_policy
        policies.append({
            "name": global_policy.name,
            "enabled": global_policy.enabled,
            "selector": global_policy.selector,
            "rules": [r.dict() for r in global_policy.rules],
        })

        # Add per-container policies
        for policy in policy_engine.config.container_policies:
            policies.append({
                "name": policy.name,
                "enabled": policy.enabled,
                "selector": policy.selector,
                "rules": [r.dict() for r in policy.rules],
            })

        return PoliciesResponse(
            timestamp=datetime.utcnow(),
            policies=policies,
            total_count=len(policies),
        )
