"""Metric definitions and structures for DRI agent."""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


class MetricType(Enum):
    """Supported metric types."""
    CPU_PERCENT = "cpu_percent"
    MEMORY_USAGE = "memory_usage"
    MEMORY_LIMIT = "memory_limit"
    MEMORY_PERCENT = "memory_percent"
    NET_IO_IN = "net_io_in"
    NET_IO_OUT = "net_io_out"
    BLOCK_IO_READ = "block_io_read"
    BLOCK_IO_WRITE = "block_io_write"
    PIDs = "pids"


@dataclass
class ContainerMetrics:
    """Container resource metrics snapshot."""
    container_id: str
    container_name: str
    timestamp: datetime

    # CPU metrics
    cpu_percent: float
    cpu_count: int

    # Memory metrics
    memory_usage: int  # bytes
    memory_limit: int  # bytes
    memory_percent: float

    # Network metrics
    net_io_in: int  # bytes
    net_io_out: int  # bytes

    # Block I/O metrics
    block_io_read: int  # bytes
    block_io_write: int  # bytes

    # Process metrics
    pids: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, serializing datetime."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class AggregatedMetrics:
    """Aggregated metrics with moving averages."""
    container_id: str
    container_name: str
    timestamp: datetime

    # Current values
    cpu_percent: float
    memory_percent: float

    # Moving averages (5, 15, 60 minutes)
    cpu_percent_5m: float
    cpu_percent_15m: float
    cpu_percent_60m: float

    memory_percent_5m: float
    memory_percent_15m: float
    memory_percent_60m: float

    # Growth rates
    memory_growth_rate_1m: float  # percent per minute
    memory_growth_rate_5m: float

    # Anomaly flags
    is_anomaly: bool = False
    anomaly_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, serializing datetime."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class Alert:
    """Resource alert for a container."""
    alert_id: str
    container_id: str
    container_name: str
    timestamp: datetime
    alert_type: str  # "warning", "critical"
    metric: str  # "cpu", "memory", "growth_rate", etc.
    current_value: float
    threshold: float
    message: str
    acknowledged: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, serializing datetime."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class Action:
    """Resource action taken on a container."""
    action_id: str
    container_id: str
    container_name: str
    timestamp: datetime
    action_type: str  # "throttle", "isolate", "restart", "webhook"
    reason: str
    details: Dict[str, Any]
    success: bool
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, serializing datetime."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data
