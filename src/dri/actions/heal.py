"""Self-healing actions for OOM prediction and recovery."""

import asyncio
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
import docker

from ..utils.logger import get_logger
from ..utils.metrics import Action, AggregatedMetrics
from ..utils.webhooks import WebhookDispatcher

logger = get_logger("heal")


class HealAction:
    """Self-healing actions for OOM prediction and recovery."""

    def __init__(
        self,
        docker_client: docker.DockerClient,
        webhook_dispatcher: Optional[WebhookDispatcher] = None,
    ):
        """
        Initialize heal action.

        Args:
            docker_client: Docker client instance
            webhook_dispatcher: Optional webhook dispatcher
        """
        self.client = docker_client
        self.webhook_dispatcher = webhook_dispatcher

    async def predict_oom(
        self,
        metrics: AggregatedMetrics,
        prediction_threshold: float = 0.95,
    ) -> Dict[str, Any]:
        """
        Predict if container will OOM soon.

        Args:
            metrics: Container metrics
            prediction_threshold: Memory percent threshold for warning

        Returns:
            Prediction result with risk level
        """
        risk_level = "low"
        reason = ""

        # Check current memory usage
        if metrics.memory_percent >= prediction_threshold * 100:
            risk_level = "critical"
            reason = f"Memory at {metrics.memory_percent}% of limit"
        elif metrics.memory_percent >= 80:
            # Check growth rate
            if metrics.memory_growth_rate_5m > 20.0:
                risk_level = "high"
                reason = f"High growth rate ({metrics.memory_growth_rate_5m}%/min)"
            elif metrics.memory_percent_60m and metrics.memory_percent > metrics.memory_percent_60m + 30:
                risk_level = "high"
                reason = f"Rapid memory increase from 60m average"
            else:
                risk_level = "medium"
                reason = f"Memory at {metrics.memory_percent}%"

        return {
            "container_id": metrics.container_id,
            "container_name": metrics.container_name,
            "risk_level": risk_level,
            "memory_percent": metrics.memory_percent,
            "growth_rate_5m": metrics.memory_growth_rate_5m,
            "reason": reason,
        }

    async def graceful_restart(
        self,
        container_id: str,
        stop_timeout: int = 30,
        reason: str = "OOM prevention",
    ) -> Dict[str, Any]:
        """
        Gracefully restart a container.

        Args:
            container_id: Container ID or name
            stop_timeout: Timeout for graceful stop (seconds)
            reason: Reason for restart

        Returns:
            Result dictionary
        """
        loop = asyncio.get_event_loop()

        def _restart() -> Dict[str, Any]:
            try:
                container = self.client.containers.get(container_id)

                logger.info(
                    f"Gracefully restarting container",
                    container_id=container_id,
                    reason=reason,
                )

                # Stop container gracefully
                container.stop(timeout=stop_timeout)

                # Small delay before restart
                time.sleep(2)

                # Restart container
                container.start()

                return {
                    "success": True,
                    "container_id": container_id,
                    "action": "graceful_restart",
                    "reason": reason,
                }
            except docker.errors.NotFound:
                return {
                    "success": False,
                    "error": f"Container not found: {container_id}",
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                }

        try:
            result = await loop.run_in_executor(None, _restart)
            logger.info(f"Restart action completed", success=result["success"])
            return result
        except Exception as e:
            logger.error(f"Restart action failed: {e}")
            return {"success": False, "error": str(e)}

    async def trigger_webhook(
        self,
        webhook_url: str,
        event_type: str,
        payload: Dict[str, Any],
    ) -> bool:
        """
        Trigger webhook for custom actions.

        Args:
            webhook_url: Target webhook URL
            event_type: Type of event
            payload: Event payload

        Returns:
            Success status
        """
        if not self.webhook_dispatcher:
            logger.warning("Webhook dispatcher not configured")
            return False

        return await self.webhook_dispatcher.dispatch(
            webhook_url,
            event_type,
            payload,
        )
