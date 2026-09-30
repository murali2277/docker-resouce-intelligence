"""Throttling actions for reducing CPU and memory."""

import asyncio
from typing import Optional, Dict, Any
import docker
from docker.models.containers import Container

from ..config import ThrottleConfig
from ..utils.logger import get_logger

logger = get_logger("throttle")


class ThrottleAction:
    """Apply CPU and memory throttling to containers."""

    def __init__(self, docker_client: docker.DockerClient):
        """
        Initialize throttle action.

        Args:
            docker_client: Docker client instance
        """
        self.client = docker_client

    async def throttle(
        self,
        container_id: str,
        config: ThrottleConfig,
    ) -> Dict[str, Any]:
        """
        Apply throttling to a container.

        Args:
            container_id: Container ID or name
            config: Throttle configuration

        Returns:
            Result dictionary with status and details
        """
        loop = asyncio.get_event_loop()

        def _apply_throttle() -> Dict[str, Any]:
            try:
                container = self.client.containers.get(container_id)

                # Prepare update parameters
                update_params = {}

                if config.cpu_shares:
                    update_params["cpu_shares"] = config.cpu_shares

                if config.cpu_quota:
                    update_params["cpu_quota"] = config.cpu_quota

                if config.memory_limit:
                    # Convert limit string (e.g., "512m") to bytes
                    update_params["memswap_limit"] = self._parse_memory_limit(
                        config.memory_limit
                    )
                    update_params["mem_limit"] = self._parse_memory_limit(
                        config.memory_limit
                    )

                if config.memory_reservation:
                    update_params["memory_reservation"] = self._parse_memory_limit(
                        config.memory_reservation
                    )

                if not update_params:
                    return {
                        "success": False,
                        "error": "No throttle parameters specified",
                    }

                container.update(**update_params)

                return {
                    "success": True,
                    "container_id": container_id,
                    "parameters": update_params,
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
            result = await loop.run_in_executor(None, _apply_throttle)
            logger.info(
                f"Throttle action completed container_id={container_id} success={result['success']}"
            )
            return result
        except Exception as e:
            logger.error(f"Throttle action failed: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _parse_memory_limit(limit: str) -> int:
        """
        Parse memory limit string to bytes.

        Examples:
            "512m" -> 512 * 1024 * 1024
            "1g" -> 1024 * 1024 * 1024
        """
        units = {
            "k": 1024,
            "m": 1024 ** 2,
            "g": 1024 ** 3,
        }

        limit = str(limit).lower().strip()
        for unit, multiplier in units.items():
            if limit.endswith(unit):
                try:
                    value = int(limit[:-1])
                    return value * multiplier
                except ValueError:
                    pass

        # Try to parse as plain integer (bytes)
        try:
            return int(limit)
        except ValueError:
            raise ValueError(f"Invalid memory limit: {limit}")
