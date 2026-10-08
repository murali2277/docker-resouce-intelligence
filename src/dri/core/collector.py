"""Docker stats collector for streaming container metrics."""

import asyncio
import json
from datetime import datetime, timezone
from typing import AsyncIterator, Optional, Dict, Any, List, cast
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
        loop = asyncio.get_running_loop()

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
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.client.close)
            logger.info("Disconnected from Docker daemon")

    async def get_containers(self) -> list:
        """Get list of running containers."""
        if not self.client:
            raise RuntimeError("Not connected to Docker daemon")

        loop = asyncio.get_running_loop()

        def _get_containers() -> list:
            return self.client.containers.list()

        try:
            containers = await loop.run_in_executor(None, _get_containers)
            return containers
        except Exception as e:
            logger.error(f"Failed to get containers: {e}")
            return []

    async def get_all_containers(self) -> list:
        """Get list of ALL containers, including stopped/exited/paused ones.

        Each returned container object exposes a ``.status`` attribute whose
        value is one of the Docker lifecycle strings: ``'running'``,
        ``'exited'``, ``'paused'``, ``'created'``, ``'restarting'``, etc.

        This method is used exclusively by the status-poll loop in
        :class:`DRIAgent` to detect container lifecycle transitions.  The
        regular stats-collection path (``stream_metrics``) continues to use
        ``get_containers()`` which only returns running containers.

        Returns:
            List of :class:`docker.models.containers.Container` objects,
            possibly empty on error.
        """
        if not self.client:
            raise RuntimeError("Not connected to Docker daemon")

        loop = asyncio.get_running_loop()

        def _get_all() -> list:
            return self.client.containers.list(all=True)

        try:
            containers = await loop.run_in_executor(None, _get_all)
            return containers
        except Exception as e:
            logger.error(f"Failed to get all containers: {e}")
            return []

    async def collect_stats(self, container: Container) -> Optional[ContainerMetrics]:
        """
        Collect stats for a single container.

        Args:
            container: Docker container object

        Returns:
            ContainerMetrics or None if collection fails
        """
        loop = asyncio.get_running_loop()

        def _get_stats() -> Dict[str, Any]:
            try:
                stats = container.stats(stream=False)
                return cast(Dict[str, Any], stats)
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
        """Parse Docker stats response into ContainerMetrics.

        Docker Desktop (cgroup v2) may return explicit JSON ``null`` for any of
        the sub-keys below even though the key itself is present in the payload.
        ``dict.get(key, default)`` only substitutes the default when the key is
        *missing*; a key present with value ``None`` returns ``None``, which
        then crashes subsequent ``.values()`` / iteration calls.

        Every sub-dict / sub-list access is therefore guarded with ``or {}`` /
        ``or []`` so that an explicit ``null`` falls through to the safe default.
        """
        try:
            # CPU calculation
            cpu_stats    = stats.get("cpu_stats")    or {}
            precpu_stats = stats.get("precpu_stats") or {}

            cpu_usage    = cpu_stats.get("cpu_usage")    or {}
            precpu_usage = precpu_stats.get("cpu_usage") or {}

            current_cpu  = cpu_usage.get("total_usage", 0)    or 0
            previous_cpu = precpu_usage.get("total_usage", 0) or 0

            current_system  = cpu_stats.get("system_cpu_usage", 0)    or 0
            previous_system = precpu_stats.get("system_cpu_usage", 0) or 0

            percpu_usage = cpu_usage.get("percpu_usage") or []
            cpu_count = cpu_stats.get("online_cpus") or len(percpu_usage) or 1

            cpu_percent = 0.0
            if previous_system > 0:
                cpu_delta = current_cpu - previous_cpu
                system_delta = current_system - previous_system

                if system_delta > 0 and cpu_delta >= 0:
                    cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0

            # Memory calculation
            mem_stats = stats.get("memory_stats") or {}
            raw_usage = mem_stats.get("usage", 0) or 0
            detail    = mem_stats.get("stats")    or {}
            cache     = detail.get("cache", detail.get("inactive_file", 0)) or 0
            memory_usage  = max(0, raw_usage - cache)
            memory_limit  = mem_stats.get("limit", 0) or 0
            memory_percent = 0.0

            # Guard against unrealistically huge memory_limit (e.g. 9223372036854771712 for unlimited
            # containers). We set memory_percent to 0.0 when limit exceeds 1 PB because the percentage
            # of an unlimited memory pool is meaningless. Raw memory_usage is preserved for the UI.
            UNLIMITED_MEMORY_THRESHOLD = 1 << 50
            if 0 < memory_limit < UNLIMITED_MEMORY_THRESHOLD:
                memory_percent = (memory_usage / memory_limit) * 100.0

            # Network I/O — ``networks`` is None on host-network containers and
            # on Docker Desktop with certain network drivers.
            networks  = stats.get("networks") or {}
            net_io_in  = sum(n.get("rx_bytes", 0) or 0 for n in networks.values())
            net_io_out = sum(n.get("tx_bytes", 0) or 0 for n in networks.values())

            # Block I/O — ``io_service_bytes_recursive`` is None on cgroup v2.
            blkio_stats      = stats.get("blkio_stats") or {}
            io_service_bytes = blkio_stats.get("io_service_bytes_recursive") or []
            block_io_read  = sum(
                x.get("value", 0) or 0 for x in io_service_bytes if x.get("op") == "Read"
            )
            block_io_write = sum(
                x.get("value", 0) or 0 for x in io_service_bytes if x.get("op") == "Write"
            )

            # PIDs — ``pids_stats`` is None on some kernels.
            pids = (stats.get("pids_stats") or {}).get("current", 0) or 0

            image_str = container.attrs.get("Config", {}).get("Image", "") if hasattr(container, "attrs") else ""

            return ContainerMetrics(
                container_id=(container.id or "")[:12],
                container_name=container.name or "unknown",
                image=image_str,
                timestamp=datetime.now(timezone.utc),
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
            logger.error(f"Failed to parse stats for {container.name}: {e}", exc_info=True)
            return None

    async def stream_metrics(self, interval: int = 5) -> AsyncIterator[ContainerMetrics]:
        """
        Continuously stream container metrics.

        Per-container stats are collected in **parallel** via asyncio.gather so
        that a slow or unresponsive container does not block collection for the
        rest.  Each collect_stats() call has its own 5-second timeout (see
        collect_stats), so the total wall-clock time per tick is bounded by the
        slowest container rather than the sum of all containers.

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

                # Collect stats for all containers in parallel
                results: List[Optional[ContainerMetrics]] = await asyncio.gather(
                    *[self.collect_stats(c) for c in containers],
                    return_exceptions=False,
                )

                for metrics in results:
                    if metrics is not None:
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
