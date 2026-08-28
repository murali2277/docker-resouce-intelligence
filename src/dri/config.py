"""Configuration loading and validation for DRI agent."""

import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, field_validator
import yaml
import os

from .utils.logger import get_logger

logger = get_logger("config")


class ThresholdRule(BaseModel):
    """Threshold rule for policy evaluation."""
    metric: str  # "cpu", "memory", "growth_rate"
    operator: str  # ">", "<", ">="
    value: float
    duration_seconds: int = 60  # How long before triggering
    action: str  # "warning", "throttle", "isolate", "restart"

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v: str) -> str:
        if v not in [">", "<", ">=", "<=", "=="]:
            raise ValueError(f"Invalid operator: {v}")
        return v

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in ["warning", "throttle", "isolate", "restart", "webhook"]:
            raise ValueError(f"Invalid action: {v}")
        return v


class ContainerPolicy(BaseModel):
    """Policy for a container or image."""
    name: str
    selector: Dict[str, str] = Field(default_factory=dict)  # Labels or image patterns
    rules: List[ThresholdRule] = Field(default_factory=list)
    enabled: bool = True


class ThrottleConfig(BaseModel):
    """CPU/Memory throttling configuration."""
    cpu_shares: Optional[int] = None
    cpu_quota: Optional[int] = None  # microseconds
    memory_limit: Optional[str] = None  # e.g., "512m"
    memory_reservation: Optional[str] = None


class ActionConfig(BaseModel):
    """Configuration for actions."""
    throttle: ThrottleConfig = Field(default_factory=ThrottleConfig)
    isolate_cpuset: Optional[str] = None  # e.g., "0-1"
    webhook_url: Optional[str] = None
    restart_grace_period: int = 30  # seconds


class StorageConfig(BaseModel):
    """Storage backend configuration."""
    backend: str = "sqlite"
    
    sqlite_path: str = "/var/lib/dri/metrics.db"
    # Must be >= recommender lookback_days * 24; default matches 7-day lookback.
    retention_hours: int = 168

    # InfluxDB (legacy optional integration)
    influxdb_enabled: bool = False
    influxdb_url: Optional[str] = None
    influxdb_token: Optional[str] = None
    influxdb_org: Optional[str] = None
    influxdb_bucket: Optional[str] = None

    # TimescaleDB (optional alternative backend — Phase 6 spike)
    # Enable by setting backend: "timescaledb" and providing a DSN.
    # Requires: pip install "docker-resource-intelligence[timescaledb]"
    #
    # Example DSN: "postgresql://dri:secret@timescaledb:5432/dri"
    timescaledb_url: Optional[str] = None

    @field_validator("backend")
    @classmethod
    def validate_backend(cls, v: str) -> str:
        if v not in ["sqlite", "timescaledb"]:
            raise ValueError(f"Invalid storage backend: {v}")
        return v


class APIConfig(BaseModel):
    """HTTP API configuration."""
    host: str = "0.0.0.0"
    port: int = 8000
    enable_cors: bool = True
    prometheus_metrics: bool = True


class DRIConfig(BaseModel):
    """Main DRI configuration."""
    log_level: str = "INFO"
    log_json: bool = False
    log_file: Optional[str] = None

    collector_interval: int = 5  # seconds
    aggregator_interval: int = 10  # seconds
    policy_check_interval: int = 10  # seconds
    # How often (seconds) the background worker recomputes and caches
    # recommendations and forecasts for all known containers.
    recommendation_cache_interval: int = 3600  # 1 hour

    storage: StorageConfig = Field(default_factory=StorageConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    actions: ActionConfig = Field(default_factory=ActionConfig)

    # Global and per-container policies
    global_policy: ContainerPolicy = Field(default_factory=lambda: ContainerPolicy(name="global"))
    container_policies: List[ContainerPolicy] = Field(default_factory=list)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        if v not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            raise ValueError(f"Invalid log level: {v}")
        return v


def load_config(config_path: Optional[str] = None) -> DRIConfig:
    """
    Load DRI configuration from YAML file.

    Args:
        config_path: Path to config file. If None, uses DRI_CONFIG env var or default.

    Returns:
        Parsed DRIConfig instance
    """
    if not config_path:
        config_path = os.environ.get("DRI_CONFIG", "config/config.yaml")

    config_file = Path(config_path)

    if not config_file.exists():
        logger.warning(f"Config file not found: {config_file}, using defaults")
        return DRIConfig()

    logger.info(f"Loading config from {config_file}")

    try:
        with open(config_file, "r") as f:
            config_data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        raise

    try:
        config = DRIConfig(**config_data)
        logger.info(f"Config loaded successfully")
        return config
    except Exception as e:
        logger.error(f"Config validation failed: {e}")
        raise


async def watch_config(
    config_path: str,
    on_reload: Any,
    check_interval: int = 5,
) -> None:
    """
    Watch config file for changes and trigger reload callback.

    Args:
        config_path: Path to config file
        on_reload: Async callable to invoke on config change
        check_interval: Check interval in seconds
    """
    config_file = Path(config_path)
    last_mtime = config_file.stat().st_mtime if config_file.exists() else 0

    while True:
        try:
            await asyncio.sleep(check_interval)

            if not config_file.exists():
                continue

            current_mtime = config_file.stat().st_mtime
            if current_mtime > last_mtime:
                logger.info(f"Config file changed, reloading...")
                try:
                    new_config = load_config(str(config_file))
                    await on_reload(new_config)
                    last_mtime = current_mtime
                except Exception as e:
                    logger.error(f"Failed to reload config: {e}")
        except Exception as e:
            logger.error(f"Config watcher error: {e}")
            await asyncio.sleep(5)
