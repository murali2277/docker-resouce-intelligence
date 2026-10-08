"""Policy engine for evaluating resource thresholds and triggering actions."""

import asyncio
import uuid
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Callable, Any

from ..config import DRIConfig, ThresholdRule
from ..utils.logger import get_logger
from ..utils.metrics import AggregatedMetrics, Alert

logger = get_logger("engine")

_warned_metrics = set()

def _resolve_metric_value(metric_name: str, metrics: AggregatedMetrics) -> float:
    """Resolve metric name to its value, logging a warning if unknown."""
    metric_map = {
        "cpu": metrics.cpu_percent,
        "cpu_5m": metrics.cpu_percent_5m,
        "cpu_15m": metrics.cpu_percent_15m,
        "cpu_60m": metrics.cpu_percent_60m,
        "memory": metrics.memory_percent,
        "memory_5m": metrics.memory_percent_5m,
        "memory_15m": metrics.memory_percent_15m,
        "memory_60m": metrics.memory_percent_60m,
        "growth_rate_1m": metrics.memory_growth_rate_1m,
        "memory_growth_rate_1m": metrics.memory_growth_rate_1m,
        "growth_rate_5m": metrics.memory_growth_rate_5m,
        "memory_growth_rate_5m": metrics.memory_growth_rate_5m,
    }
    
    if metric_name not in metric_map:
        if metric_name not in _warned_metrics:
            logger.warning(f"Unknown metric '{metric_name}' in policy rule")
            _warned_metrics.add(metric_name)
        return 0.0
        
    return metric_map[metric_name]


class PolicyEngine:
    """Evaluate policies and generate alerts."""

    def __init__(self, config: DRIConfig):
        """
        Initialize policy engine.

        Args:
            config: DRI configuration with policies
        """
        self.config = config
        # violation_key -> first-breach timestamp (simplified: just rule.metric, no container_id prefix)
        self._violation_tracker: Dict[str, Dict[str, datetime]] = defaultdict(dict)
        # violation_key -> timestamp of last fired alert (for re-notify suppression)
        self._last_alerted: Dict[str, Dict[str, datetime]] = defaultdict(dict)
        self._alert_callbacks: List[Callable] = []

    def register_alert_callback(self, callback: Callable) -> None:
        """Register callback for generated alerts."""
        self._alert_callbacks.append(callback)

    async def _trigger_alert(self, alert: Alert) -> None:
        """Trigger alert callbacks."""
        for callback in self._alert_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(alert)
                else:
                    callback(alert)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")

    def _evaluate_metric(
        self,
        rule: ThresholdRule,
        metrics: AggregatedMetrics,
    ) -> bool:
        """
        Evaluate a single metric against a rule.

        Args:
            rule: Threshold rule to evaluate
            metrics: Container metrics

        Returns:
            True if threshold breached
        """
        current_value = _resolve_metric_value(rule.metric, metrics)

        if rule.operator == ">":
            return current_value > rule.value
        elif rule.operator == "<":
            return current_value < rule.value
        elif rule.operator == ">=":
            return current_value >= rule.value
        elif rule.operator == "<=":
            return current_value <= rule.value
        elif rule.operator == "==":
            return current_value == rule.value

        return False

    async def evaluate(
        self,
        metrics: AggregatedMetrics,
    ) -> Optional[List[Alert]]:
        """
        Evaluate policies against metrics.

        Args:
            metrics: Container metrics to evaluate

        Yields:
            Alert if threshold breached
        """
        # Get applicable policies (global + container-specific)
        applicable_policies = [self.config.global_policy]

        for policy in self.config.container_policies:
            if not policy.enabled:
                continue

            # Check if policy applies to this container
            for key, value in policy.selector.items():
                if key == "image":
                    image_str = getattr(metrics, "image", "") or ""
                    try:
                        if image_str and re.search(value, image_str):
                            applicable_policies.append(policy)
                    except re.error as e:
                        logger.error(f"Invalid regex in policy selector for image '{value}': {e}")
                elif key == "container_id" and value == metrics.container_id:
                    applicable_policies.append(policy)

        alerts = []
        now = datetime.now(timezone.utc)
        renotify_seconds: int = getattr(self.config, "alert_renotify_seconds", 300)

        for policy in applicable_policies:
            for rule in policy.rules:
                # Simplified violation key: just the metric name (container_id is the outer dict key)
                violation_key = rule.metric

                # Check if metric breaches threshold
                if self._evaluate_metric(rule, metrics):
                    cid = metrics.container_id

                    # --- Duration tracking ---
                    if violation_key not in self._violation_tracker[cid]:
                        # P0-4 fix: record start time on first breach
                        self._violation_tracker[cid][violation_key] = now

                    violation_start = self._violation_tracker[cid][violation_key]
                    violation_duration = (now - violation_start).total_seconds()

                    # P0-4 fix: duration_seconds==0 fires on first call (violation_duration==0 >= 0)
                    if violation_duration >= rule.duration_seconds:
                        # --- Re-notify suppression ---
                        last_fired = self._last_alerted[cid].get(violation_key)
                        if last_fired is not None and renotify_seconds > 0:
                            elapsed_since_fire = (now - last_fired).total_seconds()
                            if elapsed_since_fire < renotify_seconds:
                                continue  # still in cooldown — suppress

                        alert = Alert(
                            alert_id=str(uuid.uuid4()),
                            container_id=metrics.container_id,
                            container_name=metrics.container_name,
                            timestamp=now,
                            alert_type=rule.action,
                            metric=rule.metric,
                            current_value=self._get_metric_value(rule.metric, metrics),
                            threshold=rule.value,
                            message=f"{rule.metric} {rule.operator} {rule.value}% for {violation_duration:.0f}s",
                        )
                        alerts.append(alert)
                        self._last_alerted[cid][violation_key] = now
                        await self._trigger_alert(alert)
                else:
                    # Breach cleared — reset BOTH trackers so the next episode fires immediately
                    cid = metrics.container_id
                    self._violation_tracker[cid].pop(violation_key, None)
                    self._last_alerted[cid].pop(violation_key, None)

        return alerts if alerts else None

    def _get_metric_value(self, metric: str, metrics: AggregatedMetrics) -> float:
        """Get metric value by name."""
        return _resolve_metric_value(metric, metrics)

    def update_config(self, config: DRIConfig) -> None:
        """Hot-reload policy configuration."""
        self.config = config
        logger.info("Policy configuration reloaded")
