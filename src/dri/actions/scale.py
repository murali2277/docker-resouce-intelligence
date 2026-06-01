"""Container scaling and optimization actions."""

from typing import Dict, Any, List

from ..utils.logger import get_logger
from ..utils.metrics import AggregatedMetrics

logger = get_logger("scale")


class ScaleAction:
    """Identify and flag containers for scaling optimization."""

    @staticmethod
    def identify_idle_containers(
        metrics_list: List[AggregatedMetrics],
        idle_threshold_cpu: float = 1.0,
        idle_threshold_memory: float = 1.0,
    ) -> List[Dict[str, Any]]:
        """
        Identify idle containers for potential shutdown or downscaling.

        Args:
            metrics_list: List of aggregated metrics
            idle_threshold_cpu: CPU % threshold for idle detection
            idle_threshold_memory: Memory % threshold for idle detection

        Returns:
            List of idle containers
        """
        idle = []

        for metrics in metrics_list:
            # Check 60-minute average for sustained low usage
            if (
                metrics.cpu_percent_60m < idle_threshold_cpu and
                metrics.memory_percent_60m < idle_threshold_memory
            ):
                idle.append({
                    "container_id": metrics.container_id,
                    "container_name": metrics.container_name,
                    "cpu_avg_60m": metrics.cpu_percent_60m,
                    "memory_avg_60m": metrics.memory_percent_60m,
                    "recommendation": "Consider scaling down or stopping",
                })

        return idle
