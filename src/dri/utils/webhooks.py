"""Webhook dispatch utilities for DRI agent."""

import asyncio
import json
from typing import Dict, Any, Optional
from datetime import datetime
import aiohttp

from .logger import get_logger

logger = get_logger("webhooks")


class WebhookDispatcher:
    """Handle webhook dispatching for alerts and actions."""

    def __init__(self, timeout: int = 10, max_retries: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self._session: Optional[aiohttp.ClientSession] = None

    async def init_session(self) -> None:
        """Initialize HTTP session."""
        if not self._session:
            self._session = aiohttp.ClientSession()

    async def close_session(self) -> None:
        """Close HTTP session."""
        if self._session:
            await self._session.close()

    async def dispatch(
        self,
        webhook_url: str,
        event_type: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Dispatch webhook with retries.

        Args:
            webhook_url: Target webhook URL
            event_type: Type of event (alert, action, etc.)
            payload: Event payload
            headers: Optional additional headers

        Returns:
            Success status
        """
        if not self._session:
            await self.init_session()

        default_headers = {
            "Content-Type": "application/json",
            "User-Agent": "DRI-Agent/0.1.0",
        }
        if headers:
            default_headers.update(headers)

        webhook_payload = {
            "timestamp": datetime.utcnow().isoformat(),
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
                            f"Webhook dispatched successfully",
                            webhook_url=webhook_url,
                            event_type=event_type,
                            status=response.status,
                        )
                        return True
                    else:
                        logger.warning(
                            f"Webhook returned error status",
                            webhook_url=webhook_url,
                            status=response.status,
                        )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Webhook timeout (attempt {attempt + 1}/{self.max_retries})",
                    webhook_url=webhook_url,
                )
            except Exception as e:
                logger.error(
                    f"Webhook dispatch failed: {str(e)}",
                    webhook_url=webhook_url,
                    attempt=attempt + 1,
                )

            if attempt < self.max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff

        logger.error(
            f"Webhook dispatch failed after {self.max_retries} attempts",
            webhook_url=webhook_url,
        )
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
