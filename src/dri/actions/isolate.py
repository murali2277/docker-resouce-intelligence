"""CPU set isolation action for container resource limiting."""

import asyncio
from typing import Dict, Any
import docker

from ..utils.logger import get_logger

logger = get_logger("isolate")


class IsolateAction:
    """Isolate containers to specific CPU sets."""

    def __init__(self, docker_client: docker.DockerClient):
        """
        Initialize isolate action.

        Args:
            docker_client: Docker client instance
        """
        self.client = docker_client

    async def isolate(
        self,
        container_id: str,
        cpuset: str,
    ) -> Dict[str, Any]:
        """
        Isolate container to specific CPU set.

        Args:
            container_id: Container ID or name
            cpuset: CPU set string (e.g., "0-1", "0,2")

        Returns:
            Result dictionary with status and details
        """
        loop = asyncio.get_event_loop()

        def _apply_isolation() -> Dict[str, Any]:
            try:
                container = self.client.containers.get(container_id)

                # Update container with cpuset
                container.update(cpuset_cpus=cpuset)

                return {
                    "success": True,
                    "container_id": container_id,
                    "cpuset": cpuset,
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
            result = await loop.run_in_executor(None, _apply_isolation)
            logger.info(
                f"Isolation action completed",
                container_id=container_id,
                cpuset=cpuset,
                success=result["success"],
            )
            return result
        except Exception as e:
            logger.error(f"Isolation action failed: {e}")
            return {"success": False, "error": str(e)}
