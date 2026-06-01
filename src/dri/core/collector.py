"""Docker stats collector for streaming container metrics."""

import asyncio
import json
from datetime import datetime
from typing import AsyncIterator, Optional, Dict, Any
import docker
from docker.models.containers import Container

from ..utils.logger import get_logger
from ..utils.metrics import ContainerMetrics

logger = get_logger("collector")


class DockerStatsCollector:
    """Stream and collect Docker container statistics."""

    def __init__(self, docker_host: Optional[str] = None):
        """
        Initialize stats collector.

        Args:
            docker_host: Docker daemon URL. If None, uses default.
        """
        self.docker_host = docker_host
        self.client: Optional[docker.DockerClient] = None
        self._running = False

    async def connect(self) -> None:
        """Connect to Docker daemon."""
        loop = asyncio.get_event_loop()

        def _connect() -> docker.DockerClient:
            if self.docker_host:
                return docker.DockerClient(base_url=self.docker_host)
            return docker.from_env()

        try:
            self.client = await loop.run_in_executor(None, _connect)
            logger.info("Connected to Docker daemon")
        except Exception as e:
            logger.error(f"Failed to connect to Docker: {e}")
            raise

    async def disconnect(self) -> None:
        """Disconnect from Docker daemon."""
        if self.client:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.client.close)
            logger.info("Disconnected from Docker daemon")

    async def get_containers(self) -> list:
        """Get list of running containers."""
        if not self.client:
            raise RuntimeError("Not connected to Docker daemon")

        loop = asyncio.get_event_loop()

        def _get_containers() -> list:
            return self.client.containers.list()

        try:
            containers = await loop.run_in_executor(None, _get_containers)
            return containers
        except Exception as e:
            logger.error(f"Failed to get containers: {e}")
            return []

    async def collect_stats(self, container: Container) -> Optional[ContainerMetrics]:
        """
        Collect stats for a single container.

        Args:
            container: Docker container object

        Returns:
            ContainerMetrics or None if collection fails
        """
        loop = asyncio.get_event_loop()

        def _get_stats() -> Dict[str, Any]:
            try:
                stats = container.stats(stream=False)
                return stats
            except Exception as e:
                logger.debug(f"Failed to collect stats for {container.name}: {e}")
                return {}

        try:
            stats_data = await asyncio.wait_for(
                loop.run_in_executor(None, _get_stats),
                timeout=5
            )

            if not stats_data:
                return None

            return self._parse_stats(container, stats_data)
        except asyncio.TimeoutError:
            logger.warning(f"Stats collection timeout for {container.name}")
            return None
        except Exception as e:
            logger.error(f"Error collecting stats: {e}")
            return None

    def _parse_stats(self, container: Container, stats: Dict[str, Any]) -> Optional[ContainerMetrics]:
        """Parse Docker stats response into ContainerMetrics."""
        try:
            # CPU calculation
            cpu_delta = stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
            system_delta = stats.get("cpu_stats", {}).get("system_cpu_usage", 0)
            cpu_count = len(stats.get("cpu_stats", {}).get("cpus", []))

            cpu_percent = 0.0
            if system_delta > 0 and cpu_count > 0:
                cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0

            # Memory calculation
            memory_usage = stats.get("memory_stats", {}).get("usage", 0)
            memory_limit = stats.get("memory_stats", {}).get("limit", 0)
            memory_percent = 0.0
            if memory_limit > 0:
                memory_percent = (memory_usage / memory_limit) * 100.0

            # Network I/O
            networks = stats.get("networks", {})
            net_io_in = sum(n.get("rx_bytes", 0) for n in networks.values())
            net_io_out = sum(n.get("tx_bytes", 0) for n in networks.values())

            # Block I/O
            blkio_stats = stats.get("blkio_stats", {})
            io_service_bytes = blkio_stats.get("io_service_bytes_recursive", [])
            block_io_read = sum(x.get("value", 0) for x in io_service_bytes if x.get("op") == "Read")
            block_io_write = sum(x.get("value", 0) for x in io_service_bytes if x.get("op") == "Write")

            # PIDs
            pids = stats.get("pids_stats", {}).get("current", 0)

            return ContainerMetrics(
                container_id=container.id[:12],
                container_name=container.name,
                timestamp=datetime.utcnow(),
                cpu_percent=round(cpu_percent, 2),
                cpu_count=cpu_count,
                memory_usage=memory_usage,
                memory_limit=memory_limit,
                memory_percent=round(memory_percent, 2),
                net_io_in=net_io_in,
                net_io_out=net_io_out,
                block_io_read=block_io_read,
                block_io_write=block_io_write,
                pids=pids,
            )
        except Exception as e:
            logger.error(f"Failed to parse stats: {e}")
            return None

    async def stream_metrics(self, interval: int = 5) -> AsyncIterator[ContainerMetrics]:
        """
        Continuously stream container metrics.

        Args:
            interval: Collection interval in seconds

        Yields:
            ContainerMetrics for each container
        """
        if not self.client:
            await self.connect()

        self._running = True
        consecutive_errors = 0
        max_consecutive_errors = 5

        while self._running:
            try:
                containers = await self.get_containers()
                consecutive_errors = 0

                for container in containers:
                    metrics = await self.collect_stats(container)
                    if metrics:
                        yield metrics

                await asyncio.sleep(interval)

            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Error in metrics stream: {e} (attempt {consecutive_errors})")

                if consecutive_errors >= max_consecutive_errors:
                    logger.error("Too many consecutive errors, reconnecting...")
                    try:
                        await self.disconnect()
                        await asyncio.sleep(5)
                        await self.connect()
                        consecutive_errors = 0
                    except Exception as e:
                        logger.error(f"Reconnection failed: {e}")
                else:
                    await asyncio.sleep(min(2 ** consecutive_errors, 30))

    def stop(self) -> None:
        """Stop streaming metrics."""
        self._running = False
        logger.info("Stats collector stopped")
