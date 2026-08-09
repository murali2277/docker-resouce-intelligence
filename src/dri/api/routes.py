"""FastAPI routes for DRI agent HTTP API."""

from datetime import datetime
from typing import Optional, List, Any
from fastapi import APIRouter, HTTPException, Query
from prometheus_client import Counter, Histogram
import time

from ..core.storage import MetricsStorage
from ..core.aggregator import MetricsAggregator
from ..core.engine import PolicyEngine
from .models import (
    MetricsResponse,
    ContainerMetricsListResponse,
    AlertResponse,
    AlertsResponse,
    ActionHistoryResponse,
    ActionHistoryListResponse,
    PoliciesResponse,
    HealthCheckResponse,
    RecommendationResponse,
    RecommendationsListResponse,
    ForecastResponse,
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
agent: Optional[Any] = None         # DRIAgent reference for live counters
recommender: Optional[Any] = None   # ResourceRecommender
forecaster: Optional[Any] = None    # MetricsForecaster
start_time: float = time.time()


def set_dependencies(
    s: MetricsStorage,
    a: MetricsAggregator,
    pe: PolicyEngine,
    ag: Optional[Any] = None,
    rec: Optional[Any] = None,
    fore: Optional[Any] = None,
) -> None:
    """Inject dependencies into routes."""
    global storage, aggregator, policy_engine, agent, recommender, forecaster
    storage = s
    aggregator = a
    policy_engine = pe
    agent = ag
    recommender = rec
    forecaster = fore


@router.get("/health", response_model=HealthCheckResponse)
async def health_check() -> HealthCheckResponse:
    """Health check endpoint."""
    metrics_requests.labels(method="GET", endpoint="health").inc()

    with metrics_latency.labels(endpoint="health").time():
        uptime = time.time() - start_time

        # Read real counters from the DRIAgent if available
        metrics_processed = agent.metrics_processed if agent else 0
        alerts_generated = agent.alerts_generated if agent else 0
        actions_executed = agent.actions_executed if agent else 0

        return HealthCheckResponse(
            status="healthy",
            version="0.1.0",
            timestamp=datetime.utcnow(),
            uptime_seconds=uptime,
            metrics_processed=metrics_processed,
            alerts_generated=alerts_generated,
            actions_executed=actions_executed,
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

        records = await storage.get_recent_alerts(limit=limit, offset=offset)
        total = await storage.count_alerts()

        alert_responses = [
            AlertResponse(
                alert_id=r.id,
                container_id=r.container_id,
                container_name=r.container_name,
                timestamp=r.timestamp,
                alert_type=r.alert_type,
                metric=r.metric,
                current_value=r.current_value,
                threshold=r.threshold,
                message=r.message,
                acknowledged=r.acknowledged,
            )
            for r in records
        ]

        return AlertsResponse(
            timestamp=datetime.utcnow(),
            alerts=alert_responses,
            total_count=total,
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

        records = await storage.get_recent_actions(limit=limit, offset=offset)
        total = await storage.count_actions()

        action_responses = [
            ActionHistoryResponse(
                action_id=r.id,
                container_id=r.container_id,
                container_name=r.container_name,
                timestamp=r.timestamp,
                action_type=r.action_type,
                reason=r.reason,
                success=r.success,
                error_message=r.error_message,
            )
            for r in records
        ]

        return ActionHistoryListResponse(
            timestamp=datetime.utcnow(),
            actions=action_responses,
            total_count=total,
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
            "rules": [r.model_dump() for r in global_policy.rules],
        })

        # Add per-container policies
        for policy in policy_engine.config.container_policies:
            policies.append({
                "name": policy.name,
                "enabled": policy.enabled,
                "selector": policy.selector,
                "rules": [r.model_dump() for r in policy.rules],
            })

        return PoliciesResponse(
            timestamp=datetime.utcnow(),
            policies=policies,
            total_count=len(policies),
        )


# ---------------------------------------------------------------------------
# Phase 3: Recommendations
# ---------------------------------------------------------------------------

@router.get("/recommendations", response_model=RecommendationsListResponse)
async def get_recommendations(
    lookback_days: int = Query(7, ge=1, le=30),
    safety_margin: float = Query(0.20, ge=0.05, le=1.0),
) -> RecommendationsListResponse:
    """
    Get per-container resource limit recommendations.

    Recommendations are based on p95 CPU and memory usage over the lookback
    window, plus the specified safety margin.

    Query Parameters:
        lookback_days: Days of history to use (default 7, max 30)
        safety_margin: Fractional overhead on top of p95 (default 0.20 = +20%)
    """
    metrics_requests.labels(method="GET", endpoint="recommendations").inc()

    with metrics_latency.labels(endpoint="recommendations").time():
        if not recommender:
            raise HTTPException(status_code=503, detail="Recommender not initialized")
        if not aggregator:
            raise HTTPException(status_code=503, detail="Aggregator not initialized")

        # Get all known containers from the aggregator's in-memory windows
        container_ids = list(aggregator._windows.keys())

        # Also query storage for any containers not in current windows
        # (containers that were active historically but not right now)
        recs = []
        for cid in container_ids:
            window = aggregator._windows.get(cid)
            cname = window[-1].container_name if window else ""
            rec = await recommender.compute_recommendation(
                container_id=cid,
                container_name=cname,
                lookback_days=lookback_days,
                safety_margin=safety_margin,
            )
            if rec:
                recs.append(RecommendationResponse(**rec.to_dict()))

        return RecommendationsListResponse(
            timestamp=datetime.utcnow(),
            recommendations=recs,
            total_count=len(recs),
        )


# ---------------------------------------------------------------------------
# Phase 4: Forecasting
# ---------------------------------------------------------------------------

@router.get("/forecast/{container_id}", response_model=ForecastResponse)
async def get_forecast(
    container_id: str,
    horizon_hours: int = Query(24, ge=1, le=168),
    metric: str = Query("memory_percent", pattern="^(cpu_percent|memory_percent)$"),
) -> ForecastResponse:
    """
    Forecast CPU or memory usage N hours ahead for a container.

    Path Parameters:
        container_id: Short container ID (12 chars)

    Query Parameters:
        horizon_hours: How many hours ahead to forecast (default 24, max 168)
        metric: 'cpu_percent' or 'memory_percent' (default memory_percent)
    """
    metrics_requests.labels(method="GET", endpoint="forecast").inc()

    with metrics_latency.labels(endpoint="forecast").time():
        if not forecaster:
            raise HTTPException(status_code=503, detail="Forecaster not initialized")

        result = await forecaster.forecast(
            container_id=container_id,
            horizon_hours=horizon_hours,
            metric=metric,
        )

        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"No forecast data for container '{container_id}' — insufficient history",
            )

        return ForecastResponse(**result.to_dict())
