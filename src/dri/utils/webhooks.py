"""Webhook dispatch utilities for DRI agent."""

import asyncio
import json
import time
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import aiohttp

from .logger import get_logger

logger = get_logger("webhooks")


class WebhookDispatcher:
    """
    Handle webhook dispatching for alerts and actions.

    Includes a **circuit breaker**: after ``circuit_breaker_threshold``
    consecutive failures to the same URL the dispatcher backs off for
    ``cooldown_seconds`` before attempting that URL again.  This prevents
    hammering an unavailable endpoint on every alert.
    """

    def __init__(
        self,
        timeout: int = 10,
        max_retries: int = 3,
        circuit_breaker_threshold: int = 5,
        cooldown_seconds: int = 300,
    ):
        """
        Args:
            timeout: Per-request timeout in seconds.
            max_retries: Retry attempts per dispatch call.
            circuit_breaker_threshold: Consecutive all-retry-exhausted failures
                that open the circuit for a URL.
            cooldown_seconds: How long (seconds) to keep the circuit open before
                allowing the next attempt.
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.cooldown_seconds = cooldown_seconds
        self._session: Optional[aiohttp.ClientSession] = None

        # Circuit-breaker state, keyed by webhook URL
        self._consecutive_failures: Dict[str, int] = {}
        self._circuit_open_until: Dict[str, float] = {}  # monotonic time

    async def init_session(self) -> None:
        """Initialize HTTP session."""
        if not self._session:
            self._session = aiohttp.ClientSession()

    async def close_session(self) -> None:
        """Close HTTP session."""
        if self._session:
            await self._session.close()

    def _is_circuit_open(self, webhook_url: str) -> bool:
        """Return True if the circuit for this URL is currently open (backing off)."""
        open_until = self._circuit_open_until.get(webhook_url, 0.0)
        if time.monotonic() < open_until:
            return True
        # Circuit has expired — reset and allow a retry
        if webhook_url in self._circuit_open_until:
            del self._circuit_open_until[webhook_url]
            self._consecutive_failures[webhook_url] = 0
        return False

    def _record_success(self, webhook_url: str) -> None:
        """Reset circuit breaker state on a successful dispatch."""
        self._consecutive_failures[webhook_url] = 0
        self._circuit_open_until.pop(webhook_url, None)

    def _record_failure(self, webhook_url: str) -> None:
        """Increment failure count and open the circuit if threshold is reached."""
        count = self._consecutive_failures.get(webhook_url, 0) + 1
        self._consecutive_failures[webhook_url] = count
        if count >= self.circuit_breaker_threshold:
            open_until = time.monotonic() + self.cooldown_seconds
            self._circuit_open_until[webhook_url] = open_until
            logger.warning(
                f"Circuit breaker OPEN for {webhook_url} after {count} consecutive "
                f"failures — backing off for {self.cooldown_seconds}s"
            )

    async def dispatch(
        self,
        webhook_url: str,
        event_type: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Dispatch webhook with retries and circuit-breaker protection.

        Args:
            webhook_url: Target webhook URL
            event_type: Type of event (alert, action, etc.)
            payload: Event payload
            headers: Optional additional headers

        Returns:
            True on success, False on failure or open circuit.
        """
        # ----------------------------------------------------------------
        # Circuit-breaker check — skip dispatch if URL is in cooldown
        # ----------------------------------------------------------------
        if self._is_circuit_open(webhook_url):
            logger.warning(
                f"Circuit breaker is OPEN for {webhook_url} — skipping dispatch"
            )
            return False

        if not self._session:
            await self.init_session()

        default_headers = {
            "Content-Type": "application/json",
            "User-Agent": "DRI-Agent/0.1.0",
        }
        if headers:
            default_headers.update(headers)

        webhook_payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "data": payload,
        }

        for attempt in range(self.max_retries):
            try:
                assert self._session is not None
                async with self._session.post(
                    webhook_url,
                    json=webhook_payload,
                    headers=default_headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as response:
                    if response.status < 400:
                        logger.info(
                            f"Webhook dispatched successfully: {webhook_url} "
                            f"(event={event_type}, status={response.status})"
                        )
                        self._record_success(webhook_url)
                        return True
                    else:
                        logger.warning(
                            f"Webhook returned error status {response.status} for {webhook_url}"
                        )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Webhook timeout (attempt {attempt + 1}/{self.max_retries}) for {webhook_url}"
                )
            except Exception as e:
                logger.error(
                    f"Webhook dispatch failed: {str(e)} (attempt {attempt + 1}) for {webhook_url}"
                )

            if attempt < self.max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff

        logger.error(
            f"Webhook dispatch failed after {self.max_retries} attempts for {webhook_url}"
        )
        self._record_failure(webhook_url)
        return False


async def dispatch_webhook(
    webhook_url: str,
    event_type: str,
    payload: Dict[str, Any],
) -> bool:
    """Convenience function for one-off webhook dispatch."""
    dispatcher = WebhookDispatcher()
    try:
        await dispatcher.init_session()
        result = await dispatcher.dispatch(webhook_url, event_type, payload)
        return result
    finally:
        await dispatcher.close_session()
