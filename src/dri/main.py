"""Main DRI agent orchestrator."""

import asyncio
import signal
import sys
from datetime import datetime
from typing import Optional
import docker

from .config import DRIConfig, load_config, watch_config, StorageConfig
from .core.collector import DockerStatsCollector
from .core.storage import MetricsStorage
from .core.storage_base import StorageBackend
from .core.aggregator import MetricsAggregator
from .core.engine import PolicyEngine
from .events.listener import DockerEventListener
from .actions.throttle import ThrottleAction
from .actions.isolate import IsolateAction
from .actions.heal import HealAction
from .api.server import DRIAPIServer
from .utils.logger import setup_logging, get_logger
from .utils.metrics import Action
from .utils.webhooks import WebhookDispatcher

logger_module = get_logger("main")


def _create_storage(cfg: StorageConfig) -> StorageBackend:
    """Storage factory: returns the backend selected by config.

    Selection logic:
      1. TimescaleDB if ``backend == 'timescaledb'`` AND a DSN is provided.
      2. SQLite (default) otherwise.

    No calling code changes are required when switching backends — both
    implement :class:`StorageBackend` and expose an identical async interface.
    """
    if cfg.backend == "timescaledb" and cfg.timescaledb_url:
        from .core.storage_timescale import TimescaleStorage  # lazy import
        logger_module.info(
            f"Storage backend: TimescaleDB ({cfg.timescaledb_url!r})"
        )
        return TimescaleStorage(
            dsn=cfg.timescaledb_url,
            retention_hours=cfg.retention_hours,
        )

    logger_module.info(
        f"Storage backend: SQLite ({cfg.sqlite_path!r})"
    )
    return MetricsStorage(cfg.sqlite_path)


class DRIAgent:
    """Main Docker Resource Intelligence agent."""

    def __init__(self, config: DRIConfig):
        """
        Initialize DRI agent.

        Args:
            config: DRI configuration
        """
        self.config = config
        self.running = False

        # Initialize components
        self.docker_client: Optional[docker.DockerClient] = None
        self.collector: Optional[DockerStatsCollector] = None
        self.storage: Optional[StorageBackend] = None
        self.aggregator: Optional[MetricsAggregator] = None
        self.policy_engine: Optional[PolicyEngine] = None
        self.event_listener: Optional[DockerEventListener] = None
        self.api_server: Optional[DRIAPIServer] = None
        self.webhook_dispatcher: Optional[WebhookDispatcher] = None

        # Action handlers
        self.throttle_action: Optional[ThrottleAction] = None
        self.isolate_action: Optional[IsolateAction] = None
        self.heal_action: Optional[HealAction] = None

        # Counters for monitoring
        self.metrics_processed = 0
        self.alerts_generated = 0
        self.actions_executed = 0

        # Event & restart tracking
        self.restart_counts: dict[str, int] = {}
        self._container_died: set[str] = set()

    async def initialize(self) -> None:
        """Initialize all agent components."""
        logger_module.info("Initializing DRI agent...")

        try:
            # Docker client
            self.docker_client = docker.from_env()
            logger_module.info("Connected to Docker daemon")

            # Storage — backend determined by config flag
            self.storage = _create_storage(self.config.storage)
            await self.storage.init()

            # Aggregator
            self.aggregator = MetricsAggregator(self.storage)

            # Policy engine
            self.policy_engine = PolicyEngine(self.config)
            self.policy_engine.register_alert_callback(self._on_alert)

            # Collector
            self.collector = DockerStatsCollector()
            await self.collector.connect()

            # Event listener
            self.event_listener = DockerEventListener(self.docker_client)
            self.event_listener.register_callback(self._on_docker_event)

            # Webhook dispatcher
            self.webhook_dispatcher = WebhookDispatcher()
            await self.webhook_dispatcher.init_session()

            # Action handlers
            self.throttle_action = ThrottleAction(self.docker_client)
            self.isolate_action = IsolateAction(self.docker_client)
            self.heal_action = HealAction(self.docker_client, self.webhook_dispatcher)

            # API server
            assert self.storage is not None
            assert self.aggregator is not None
            assert self.policy_engine is not None
            self.api_server = DRIAPIServer(
                self.config,
                self.storage,
                self.aggregator,
                self.policy_engine,
                self,  # agent reference for live counters
            )

            logger_module.info("DRI agent initialized successfully")

        except Exception as e:
            logger_module.error(f"Failed to initialize agent: {e}")
            raise

    async def _on_alert(self, alert) -> None:
        """Handle generated alerts."""
        self.alerts_generated += 1
        logger_module.warning(
            f"Alert generated: {alert.alert_type} "
            f"[container={alert.container_id}, metric={alert.metric}, value={alert.current_value}]"
        )

        # Save to storage
        if self.storage:
            await self.storage.save_alert(alert)

    async def _on_docker_event(self, event) -> None:
        """Handle Docker events.

        Persists event record to storage and tracks container restarts.
        Definition of restart count: A container restart is counted when a
        ``die`` event for a container_id is followed by a subsequent ``start``
        event for the same container_id.
        """
        logger_module.info(
            f"Docker event: {event.action} "
            f"[container={event.container_id}, name={event.container_name}]"
        )

        if self.storage:
            await self.storage.save_event(event)

        cid = getattr(event, "container_id", "")
        action = getattr(event, "action", "")

        if cid:
            if action == "die":
                self._container_died.add(cid)
            elif action == "start":
                if cid in self._container_died:
                    self.restart_counts[cid] = self.restart_counts.get(cid, 0) + 1
                    self._container_died.remove(cid)
                    if self.aggregator:
                        self.aggregator.update_restart_count(cid, self.restart_counts[cid])

    async def _collect_metrics_loop(self) -> None:
        """Continuously collect metrics."""
        if not self.collector:
            return

        logger_module.info(
            f"Starting metrics collection (interval: {self.config.collector_interval}s)"
        )

        try:
            async for metrics in self.collector.stream_metrics(
                interval=self.config.collector_interval
            ):
                if not self.running:
                    break

                # Store metrics
                self.metrics_processed += 1
                if self.storage:
                    await self.storage.save_metrics(metrics)

                # Add to aggregator window
                if self.aggregator:
                    self.aggregator.add_metrics(metrics)

        except Exception as e:
            logger_module.error(f"Metrics collection error: {e}")

    async def _aggregate_metrics_loop(self) -> None:
        """Continuously aggregate metrics."""
        logger_module.info(
            f"Starting metrics aggregation (interval: {self.config.aggregator_interval}s)"
        )

        while self.running:
            try:
                await asyncio.sleep(self.config.aggregator_interval)

                if not self.aggregator:
                    continue

                # Aggregate all metrics
                all_metrics = await self.aggregator.aggregate_all()

                # Cleanup old data periodically (every 100 metrics processed by agent)
                if self.metrics_processed % 100 == 0 and self.metrics_processed > 0:
                    if self.storage:
                        await self.storage.cleanup_old_data(
                            self.config.storage.retention_hours
                        )

            except Exception as e:
                logger_module.error(f"Aggregation error: {e}")

    async def _policy_check_loop(self) -> None:
        """Continuously evaluate policies."""
        logger_module.info(
            f"Starting policy checks (interval: {self.config.policy_check_interval}s)"
        )

        while self.running:
            try:
                await asyncio.sleep(self.config.policy_check_interval)

                if not self.aggregator or not self.policy_engine:
                    continue

                # Evaluate policies for all containers
                all_metrics = await self.aggregator.aggregate_all()

                for container_id, metrics in all_metrics.items():
                    alerts = await self.policy_engine.evaluate(metrics)
                    if alerts:
                        # Handle actions based on alert types
                        for alert in alerts:
                            await self._handle_alert_action(alert)

            except Exception as e:
                logger_module.error(f"Policy check error: {e}")

    async def _handle_alert_action(self, alert) -> None:
        """Handle actions triggered by alerts."""
        try:
            if alert.alert_type == "throttle":
                # Apply throttling
                if self.throttle_action and self.config.actions.throttle:
                    result = await self.throttle_action.throttle(
                        alert.container_id,
                        self.config.actions.throttle,
                    )
                    if result["success"]:
                        self.actions_executed += 1
                        action = Action(
                            action_id=str(alert.alert_id),
                            container_id=alert.container_id,
                            container_name=alert.container_name,
                            timestamp=datetime.utcnow(),
                            action_type="throttle",
                            reason=alert.message,
                            details=result,
                            success=True,
                        )
                        if self.storage:
                            await self.storage.save_action(action)

            elif alert.alert_type == "isolate":
                # Apply CPU isolation
                if self.isolate_action and self.config.actions.isolate_cpuset:
                    result = await self.isolate_action.isolate(
                        alert.container_id,
                        self.config.actions.isolate_cpuset,
                    )
                    if result["success"]:
                        self.actions_executed += 1
                        action = Action(
                            action_id=str(alert.alert_id),
                            container_id=alert.container_id,
                            container_name=alert.container_name,
                            timestamp=datetime.utcnow(),
                            action_type="isolate",
                            reason=alert.message,
                            details=result,
                            success=True,
                        )
                        if self.storage:
                            await self.storage.save_action(action)

            elif alert.alert_type == "webhook":
                # Trigger webhook
                if self.heal_action and self.config.actions.webhook_url:
                    success = await self.heal_action.trigger_webhook(
                        self.config.actions.webhook_url,
                        "resource_alert",
                        alert.to_dict(),
                    )
                    if success:
                        self.actions_executed += 1

        except Exception as e:
            logger_module.error(f"Failed to handle alert action: {e}")

    async def _event_listener_loop(self) -> None:
        """Listen to Docker events."""
        if not self.event_listener:
            return

        logger_module.info("Starting Docker event listener")

        try:
            async for event in self.event_listener.stream_events():
                if not self.running:
                    break

                # Handle specific events
                if event.action == "oom":
                    logger_module.critical(
                        f"OOM event detected "
                        f"[container={event.container_id}, name={event.container_name}]"
                    )

        except Exception as e:
            logger_module.error(f"Event listener error: {e}")

    async def _recommendation_cache_loop(self) -> None:
        """Run the background recommendation/forecast cache worker."""
        if not self.api_server:
            return
        await self.api_server.cache_worker.run()

    async def _container_status_loop(self) -> None:
        """Periodically poll all containers (incl. stopped) to detect lifecycle
        transitions and keep the aggregator's stopped-at registry up-to-date.

        Runs every ``config.container_status_interval`` seconds.  On each tick:

        1. Calls ``collector.get_all_containers()`` to obtain the full list
           including stopped/exited containers.
        2. Diffs the running subset against ``_known_running`` to detect
           containers that have stopped or restarted since the last tick.
        3. Calls ``aggregator.mark_container_stopped()`` /
           ``unmark_container_stopped()`` accordingly.
        4. Calls ``aggregator.cleanup_stopped_containers()`` to evict windows
           that have been stopped longer than the configured grace period.
        """
        if not self.collector or not self.aggregator:
            return

        logger_module.info(
            f"Starting container status poll "
            f"(interval: {self.config.container_status_interval}s, "
            f"cleanup after: {self.config.container_status_cleanup_minutes}m)"
        )

        # 12-char IDs of containers that were running on the previous tick.
        _known_running: set = set()

        while self.running:
            try:
                await asyncio.sleep(self.config.container_status_interval)

                if not self.running:
                    break

                all_containers = await self.collector.get_all_containers()

                # Build the current running set (12-char IDs).
                current_running: set = {
                    (c.id or "")[:12]
                    for c in all_containers
                    if getattr(c, "status", "") == "running"
                }

                # Containers that just stopped (were running, now absent from
                # the running set, but still have a window in the aggregator).
                newly_stopped = (
                    _known_running - current_running
                ) & set(self.aggregator._windows.keys())

                for cid in newly_stopped:
                    self.aggregator.mark_container_stopped(cid)

                # Containers that restarted (were stopped, now running again).
                newly_running = current_running - _known_running
                for cid in newly_running:
                    self.aggregator.unmark_container_stopped(cid)

                # Evict windows for containers stopped longer than the grace period.
                self.aggregator.cleanup_stopped_containers(
                    max_stopped_minutes=self.config.container_status_cleanup_minutes
                )

                _known_running = current_running

            except Exception as e:
                logger_module.error(f"Container status poll error: {e}")

    async def run(self) -> None:
        """Run the DRI agent."""
        self.running = True
        logger_module.info("Starting DRI agent...")

        # Setup signal handlers
        def signal_handler(sig, frame):
            logger_module.info(f"Received signal {sig}, shutting down...")
            self.running = False

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        try:
            # Concurrently run all agent loops + the HTTP API server
            tasks = [
                self._collect_metrics_loop(),
                self._aggregate_metrics_loop(),
                self._policy_check_loop(),
                self._event_listener_loop(),
                self._recommendation_cache_loop(),
                self._container_status_loop(),
            ]

            if self.api_server:
                logger_module.info(
                    f"Starting API server on "
                    f"{self.config.api.host}:{self.config.api.port}"
                )
                tasks.append(self.api_server.start())

            await asyncio.gather(*tasks)

        except Exception as e:
            logger_module.error(f"Agent error: {e}")
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Shutdown the agent gracefully."""
        logger_module.info("Shutting down DRI agent...")

        try:
            if self.collector:
                self.collector.stop()
                await self.collector.disconnect()

            if self.event_listener:
                self.event_listener.stop()

            if self.storage:
                await self.storage.close()

            if self.webhook_dispatcher:
                await self.webhook_dispatcher.close_session()

            if self.docker_client:
                self.docker_client.close()

            logger_module.info("DRI agent shut down successfully")

        except Exception as e:
            logger_module.error(f"Shutdown error: {e}")


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Docker Resource Intelligence Agent")
    parser.add_argument(
        "--config",
        help="Path to configuration file",
        default="config/config.yaml",
    )
    parser.add_argument(
        "--log-level",
        help="Logging level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    parser.add_argument(
        "--api-port",
        help="API server port",
        type=int,
        default=8000,
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(level=args.log_level)

    # Load configuration
    config = load_config(args.config)
    config.api.port = args.api_port

    # Initialize and run agent
    agent = DRIAgent(config)
    await agent.initialize()
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
