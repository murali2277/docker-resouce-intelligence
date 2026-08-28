"""Docker event listener for tracking container lifecycle events."""

import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator, Dict, Any, Optional, Callable, List
import docker

from ..utils.logger import get_logger

logger = get_logger("events")


class EventType:
    """Docker event types of interest."""
    OOM = "oom"
    DIE = "die"
    CREATE = "create"
    DESTROY = "destroy"
    START = "start"
    STOP = "stop"
    HEALTH_STATUS = "health_status"


class ContainerEvent:
    """Docker container event wrapper."""

    def __init__(self, event_data: Dict[str, Any]):
        self.timestamp = datetime.now(timezone.utc).replace(tzinfo=None)
        self.event_type = event_data.get("Type", "")
        self.action = event_data.get("Action", "")
        self.actor = event_data.get("Actor", {})
        self.container_id = self.actor.get("ID", "")[:12]
        self.container_name = self.actor.get("Attributes", {}).get("name", "unknown")
        self.attributes = self.actor.get("Attributes", {})

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "action": self.action,
            "container_id": self.container_id,
            "container_name": self.container_name,
            "attributes": self.attributes,
        }


class DockerEventListener:
    """Listen to and process Docker events."""

    INTERESTING_EVENTS = [
        EventType.OOM,
        EventType.DIE,
        EventType.CREATE,
        EventType.DESTROY,
        EventType.START,
        EventType.STOP,
        EventType.HEALTH_STATUS,
    ]

    def __init__(self, docker_client: docker.DockerClient):
        """
        Initialize event listener.

        Args:
            docker_client: Docker client instance
        """
        self.client = docker_client
        self._running = False
        self._callbacks: List[Callable] = []

    def register_callback(self, callback: Callable) -> None:
        """Register callback for events."""
        self._callbacks.append(callback)

    async def _trigger_callbacks(self, event: ContainerEvent) -> None:
        """Trigger event callbacks."""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                logger.error(f"Event callback failed: {e}")

    async def stream_events(self) -> AsyncIterator[ContainerEvent]:
        """
        Stream Docker events without blocking the asyncio event loop.

        The Docker SDK's ``client.events()`` returns a blocking HTTP streaming
        iterator.  Iterating it directly in a coroutine (``for event in
        stream``) holds the event loop thread and starves every other
        coroutine (collector, aggregator, etc.).

        Fix: push the blocking iteration into a daemon thread via
        ``loop.run_in_executor`` and route events back to the async world
        through an ``asyncio.Queue``.  The coroutine then does a non-blocking
        ``await queue.get()`` so the event loop stays free between events.

        Yields:
            ContainerEvent for each interesting container event
        """
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)

        _SENTINEL = object()  # signals the thread finished

        def _push_events() -> None:
            """Run in a thread — iterate the blocking stream and enqueue events."""
            try:
                stream = self.client.events(
                    filters={"type": "container"},
                    decode=True,
                )
                for event_data in stream:
                    if not self._running:
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, event_data)
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

        self._running = True
        consecutive_errors = 0
        max_consecutive_errors = 5

        while self._running:
            import threading
            thread = threading.Thread(target=_push_events, daemon=True,
                                      name="docker-events")
            thread.start()

            try:
                while self._running:
                    item = await queue.get()

                    if item is _SENTINEL:
                        break  # thread finished — restart outer loop

                    if isinstance(item, Exception):
                        raise item  # re-raise in async context

                    try:
                        event = ContainerEvent(item)
                        if event.action in self.INTERESTING_EVENTS:
                            logger.debug(
                                f"Docker event: {event.action} ({event.container_id})"
                            )
                            yield event
                            await self._trigger_callbacks(event)
                    except Exception as e:
                        logger.error(f"Failed to process event: {e}")

                consecutive_errors = 0

            except Exception as e:
                consecutive_errors += 1
                logger.error(
                    f"Error in event stream: {e} (attempt {consecutive_errors})"
                )
                if consecutive_errors >= max_consecutive_errors:
                    logger.error("Too many consecutive errors, reconnecting...")
                    await asyncio.sleep(5)
                    consecutive_errors = 0
                else:
                    await asyncio.sleep(min(2 ** consecutive_errors, 30))

    def stop(self) -> None:
        """Stop listening to events."""
        self._running = False
        logger.info("Event listener stopped")
