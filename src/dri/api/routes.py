"""FastAPI routes for DRI agent HTTP API."""

from datetime import datetime, timezone
from typing import Optional, List, Any
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram
import time

from ..core.storage_base import StorageBackend
from ..core.aggregator import MetricsAggregator
from ..core.engine import PolicyEngine
from .models import (
    MetricsResponse,
    ContainerMetricsListResponse,
    AlertResponse,
    AlertsResponse,
    ActionHistoryResponse,
    ActionHistoryListResponse,
    EventResponse,
    EventsResponse,
    PoliciesResponse,
    HealthCheckResponse,
    RecommendationResponse,
    RecommendationsListResponse,
    InsufficientDataResponse,
    ForecastResponse,
    ErrorResponse,
)

health_router = APIRouter(prefix="/api/v1", tags=["health"])
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
storage: Optional[StorageBackend] = None
aggregator: Optional[MetricsAggregator] = None
policy_engine: Optional[PolicyEngine] = None
agent: Optional[Any] = None         # DRIAgent reference for live counters
recommender: Optional[Any] = None   # ResourceRecommender
forecaster: Optional[Any] = None    # MetricsForecaster
start_time: float = time.time()


def set_dependencies(
    s: StorageBackend,
    a: MetricsAggregator,
    pe: PolicyEngine,
    ag: Optional[Any] = None,
    rec: Optional[Any] = None,
    fore: Optional[Any] = None,
    cfg: Optional[Any] = None,
) -> None:
    """Inject dependencies into routes."""
    global storage, aggregator, policy_engine, agent, recommender, forecaster
    storage = s
    aggregator = a
    policy_engine = pe
    agent = ag
    recommender = rec
    forecaster = fore
    if cfg is not None and getattr(cfg, "api", None) is not None:
        from .server import set_api_key
        set_api_key(cfg.api.api_key)


@health_router.get("/health", response_model=HealthCheckResponse)
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

        try:
            records = await storage.get_recent_alerts(limit=limit, offset=offset)
            total = await storage.count_alerts()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Storage error: {exc}") from exc

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

        try:
            records = await storage.get_recent_actions(limit=limit, offset=offset)
            total = await storage.count_actions()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Storage error: {exc}") from exc

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


@router.get("/events", response_model=EventsResponse)
async def get_events(
    container_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> EventsResponse:
    """
    Get Docker lifecycle events.

    Query Parameters:
        container_id: Optional container ID filter
        limit: Max number of events (default 100)
        offset: Offset for pagination (default 0)
    """
    metrics_requests.labels(method="GET", endpoint="events").inc()

    with metrics_latency.labels(endpoint="events").time():
        if not storage:
            raise HTTPException(status_code=500, detail="Storage not initialized")

        try:
            records = await storage.get_recent_events(
                container_id=container_id,
                limit=limit,
                offset=offset,
            )
            total = await storage.count_events(container_id=container_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Storage error: {exc}") from exc

        event_responses = []
        for r in records:
            import json
            attrs = {}
            if r.attributes:
                try:
                    attrs = json.loads(r.attributes) if isinstance(r.attributes, str) else r.attributes
                except Exception:
                    attrs = {}
            event_responses.append(
                EventResponse(
                    id=r.id,
                    container_id=r.container_id,
                    container_name=r.container_name,
                    event_type=r.event_type,
                    action=r.action,
                    timestamp=r.timestamp,
                    attributes=attrs,
                )
            )

        return EventsResponse(
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            events=event_responses,
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
# Phase 3: Recommendations — cache-first, ?force=true for synchronous recompute
# ---------------------------------------------------------------------------

@router.get("/recommendations", response_model=RecommendationsListResponse)
async def get_recommendations(
    lookback_days: int = Query(7, ge=1, le=30),
    safety_margin: float = Query(0.20, ge=0.05, le=1.0),
    force: bool = Query(False, description="Recompute synchronously, bypassing cache"),
) -> RecommendationsListResponse:
    """
    Get per-container resource limit recommendations.

    **Normal path**: Results are served from the background cache (updated
    hourly by default).  Each result includes a ``computed_at`` timestamp
    so callers can assess freshness.

    **Force recompute**: Add ``?force=true`` to bypass the cache and trigger
    synchronous recomputation.  Use this for debugging or immediately after
    a significant workload change.

    Query Parameters:
        lookback_days: Days of history to use (default 7, max 30)
        safety_margin: Fractional overhead on top of p95 (default 0.20 = +20%)
        force: Recompute synchronously (default false)
    """
    metrics_requests.labels(method="GET", endpoint="recommendations").inc()

    with metrics_latency.labels(endpoint="recommendations").time():
        if not recommender:
            raise HTTPException(status_code=503, detail="Recommender not initialized")
        if not storage:
            raise HTTPException(status_code=503, detail="Storage not initialized")

        # ----------------------------------------------------------------
        # Cache-first path (default)
        # ----------------------------------------------------------------
        if not force:
            cached = await storage.get_all_recommendation_caches()
            if cached:
                recs = []
                for payload in cached:
                    try:
                        recs.append(RecommendationResponse(**payload))
                    except Exception as e:
                        # Skip malformed cache entries gracefully
                        pass
                return RecommendationsListResponse(
                    timestamp=datetime.utcnow(),
                    recommendations=recs,
                    total_count=len(recs),
                )

        # ----------------------------------------------------------------
        # Synchronous recompute path (?force=true or empty cache)
        # ----------------------------------------------------------------
        if not aggregator:
            raise HTTPException(status_code=503, detail="Aggregator not initialized")

        container_ids = list(aggregator._windows.keys())

        from ..core.recommender import Recommendation, InsufficientDataResult

        recs = []
        for cid in container_ids:
            window = aggregator._windows.get(cid)
            cname = window[-1].container_name if window else ""
            result = await recommender.compute_recommendation(
                container_id=cid,
                container_name=cname,
                lookback_days=lookback_days,
                safety_margin=safety_margin,
            )
            if isinstance(result, Recommendation):
                payload = result.to_dict()
                recs.append(RecommendationResponse(**payload))

        return RecommendationsListResponse(
            timestamp=datetime.utcnow(),
            recommendations=recs,
            total_count=len(recs),
        )


# ---------------------------------------------------------------------------
# Phase 4: Forecasting — cache-first, ?force=true for synchronous recompute
# ---------------------------------------------------------------------------

@router.get("/forecast/{container_id}", response_model=ForecastResponse)
async def get_forecast(
    container_id: str,
    horizon_hours: int = Query(24, ge=1, le=168),
    metric: str = Query("memory_percent", pattern="^(cpu_percent|memory_percent)$"),
    force: bool = Query(False, description="Recompute synchronously, bypassing cache"),
) -> ForecastResponse:
    """
    Forecast CPU or memory usage N hours ahead for a container.

    **Normal path**: Served from background cache (updated hourly).
    **Force recompute**: Add ``?force=true`` to bypass cache.

    Path Parameters:
        container_id: Short container ID (12 chars)

    Query Parameters:
        horizon_hours: How many hours ahead to forecast (default 24, max 168)
        metric: 'cpu_percent' or 'memory_percent' (default memory_percent)
        force: Recompute synchronously (default false)
    """
    metrics_requests.labels(method="GET", endpoint="forecast").inc()

    with metrics_latency.labels(endpoint="forecast").time():
        if not forecaster:
            raise HTTPException(status_code=503, detail="Forecaster not initialized")
        if not storage:
            raise HTTPException(status_code=503, detail="Storage not initialized")

        # ----------------------------------------------------------------
        # Cache-first path
        # ----------------------------------------------------------------
        if not force:
            cached = await storage.get_forecast_cache(container_id, metric, horizon_hours)
            if cached:
                try:
                    return ForecastResponse(**cached)
                except Exception:
                    pass  # malformed cache — fall through to recompute

        # ----------------------------------------------------------------
        # Synchronous recompute
        # ----------------------------------------------------------------
        from ..core.forecaster import ForecastResult, InsufficientForecastData

        result = await forecaster.forecast(
            container_id=container_id,
            horizon_hours=horizon_hours,
            metric=metric,
        )

        if isinstance(result, InsufficientForecastData):
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Insufficient data for container '{container_id}': "
                    f"need {result.min_samples_required} samples, "
                    f"have {result.samples_available}"
                ),
            )

        if not isinstance(result, ForecastResult):
            raise HTTPException(
                status_code=404,
                detail=f"No forecast data for container '{container_id}' — insufficient history",
            )

        return ForecastResponse(**result.to_dict())
