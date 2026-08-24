"""TimescaleDB storage backend for DRI metrics, alerts, actions, and caches.

Architecture
------------
* ``metrics_samples`` is a **TimescaleDB hypertable** partitioned by ``time``
  (column name required by Timescale).  A native retention policy replaces
  the manual DELETE used by SqliteStorage.
* All other tables (alerts, actions, recommendation/forecast caches) are plain
  Postgres tables managed through asyncpg as well — no SQLAlchemy ORM is used
  here; raw SQL keeps the dependency surface minimal and avoids the thread-pool
  wrapping needed for the sync ORM.
* A single ``asyncpg`` connection pool is shared across all operations.

Dependencies (optional extra)
------------------------------
    pip install "docker-resource-intelligence[timescaledb]"
    # or directly:
    pip install "asyncpg>=0.29.0"

Connection URL format
---------------------
    postgresql://user:password@host:5432/dbname
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger
from .storage_base import StorageBackend

logger = get_logger("storage.timescale")


# ---------------------------------------------------------------------------
# Lightweight row shim — lets asyncpg dicts quack like ORM records so that
# callers (aggregator, recommender, forecaster) can use attribute access.
# ---------------------------------------------------------------------------

class _Row:
    """Minimal ORM-row shim backed by an asyncpg Record / dict."""

    __slots__ = ("_data",)

    def __init__(self, data: dict) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(name)

    def __repr__(self) -> str:
        return f"<_Row {self._data!r}>"


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL_METRICS = """\
CREATE TABLE IF NOT EXISTS metrics_samples (
    time           TIMESTAMPTZ NOT NULL,
    container_id   TEXT        NOT NULL,
    container_name TEXT,
    cpu_percent    DOUBLE PRECISION,
    memory_usage   BIGINT,
    memory_limit   BIGINT,
    memory_percent DOUBLE PRECISION,
    net_io_in      BIGINT,
    net_io_out     BIGINT,
    block_io_read  BIGINT,
    block_io_write BIGINT,
    pids           INTEGER
);
"""

_DDL_ALERTS = """\
CREATE TABLE IF NOT EXISTS alerts (
    id             TEXT PRIMARY KEY,
    container_id   TEXT,
    container_name TEXT,
    timestamp      TIMESTAMPTZ,
    alert_type     TEXT,
    metric         TEXT,
    current_value  DOUBLE PRECISION,
    threshold      DOUBLE PRECISION,
    message        TEXT,
    acknowledged   BOOLEAN DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_alerts_ts ON alerts (timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_alerts_cid ON alerts (container_id);
"""

_DDL_ACTIONS = """\
CREATE TABLE IF NOT EXISTS actions (
    id             TEXT PRIMARY KEY,
    container_id   TEXT,
    container_name TEXT,
    timestamp      TIMESTAMPTZ,
    action_type    TEXT,
    reason         TEXT,
    details        TEXT,
    success        BOOLEAN,
    error_message  TEXT
);
CREATE INDEX IF NOT EXISTS ix_actions_ts ON actions (timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_actions_cid ON actions (container_id);
"""

_DDL_REC_CACHE = """\
CREATE TABLE IF NOT EXISTS recommendation_cache (
    container_id TEXT PRIMARY KEY,
    computed_at  TIMESTAMPTZ NOT NULL,
    payload      TEXT        NOT NULL
);
"""

_DDL_FORE_CACHE = """\
CREATE TABLE IF NOT EXISTS forecast_cache (
    container_id  TEXT    NOT NULL,
    metric        TEXT    NOT NULL,
    horizon_hours INTEGER NOT NULL,
    computed_at   TIMESTAMPTZ NOT NULL,
    payload       TEXT        NOT NULL,
    PRIMARY KEY (container_id, metric, horizon_hours)
);
"""


class TimescaleStorage(StorageBackend):
    """TimescaleDB storage backend using asyncpg.

    Args:
        dsn: asyncpg-compatible DSN, e.g.
             ``"postgresql://dri:secret@localhost:5432/dri"``
        retention_hours: How many hours of metric samples to retain.
            Passed to ``add_retention_policy`` on the hypertable.
            Set to 0 to disable automatic retention.
        pool_min_size: Minimum asyncpg pool connections.
        pool_max_size: Maximum asyncpg pool connections.
    """

    def __init__(
        self,
        dsn: str,
        retention_hours: int = 168,
        pool_min_size: int = 2,
        pool_max_size: int = 10,
    ) -> None:
        try:
            import asyncpg  # noqa: F401 — presence check at init time
        except ImportError as exc:
            raise ImportError(
                "asyncpg is required for TimescaleDB support. "
                "Install it with: pip install 'docker-resource-intelligence[timescaledb]'"
            ) from exc

        self._dsn = dsn
        self._retention_hours = retention_hours
        self._pool_min = pool_min_size
        self._pool_max = pool_max_size
        self._pool: Any = None  # asyncpg.Pool — typed as Any to avoid import at module level
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Create connection pool, tables, hypertable, and retention policy."""
        import asyncpg

        logger.info(f"Connecting to TimescaleDB: {self._dsn!r}")
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._pool_min,
            max_size=self._pool_max,
        )

        async with self._pool.acquire() as conn:
            # Plain tables
            await conn.execute(_DDL_ALERTS)
            await conn.execute(_DDL_ACTIONS)
            await conn.execute(_DDL_REC_CACHE)
            await conn.execute(_DDL_FORE_CACHE)

            # metrics_samples — create, then promote to hypertable
            await conn.execute(_DDL_METRICS)
            try:
                await conn.execute(
                    "SELECT create_hypertable("
                    "    'metrics_samples', by_range('time'), if_not_exists => TRUE"
                    ");"
                )
                logger.info("metrics_samples hypertable ready")
            except Exception as exc:
                # Log but don't fail — table still works as a plain table
                logger.warning(f"create_hypertable: {exc}")

            # Composite index on (container_id, time) for range queries
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_metrics_cid_time "
                "ON metrics_samples (container_id, time DESC);"
            )

            # Native retention policy (avoids periodic DELETE scans)
            if self._retention_hours > 0:
                try:
                    await conn.execute(
                        "SELECT add_retention_policy("
                        "    'metrics_samples',"
                        "    INTERVAL $1,"
                        "    if_not_exists => TRUE"
                        ");",
                        f"{self._retention_hours} hours",
                    )
                    logger.info(
                        f"Retention policy set: {self._retention_hours}h "
                        "on metrics_samples"
                    )
                except Exception as exc:
                    logger.warning(f"add_retention_policy: {exc} (policy may already exist)")

        self._initialized = True
        logger.info("TimescaleDB storage initialized")

    async def close(self) -> None:
        """Close the asyncpg connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
        logger.info("TimescaleDB storage closed")

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    async def save_metrics(self, metrics: Any) -> None:
        """INSERT a single ContainerMetrics sample into the hypertable."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO metrics_samples
                        (time, container_id, container_name,
                         cpu_percent, memory_usage, memory_limit, memory_percent,
                         net_io_in, net_io_out, block_io_read, block_io_write, pids)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    """,
                    metrics.timestamp,
                    metrics.container_id,
                    metrics.container_name,
                    metrics.cpu_percent,
                    metrics.memory_usage,
                    metrics.memory_limit,
                    metrics.memory_percent,
                    metrics.net_io_in,
                    metrics.net_io_out,
                    metrics.block_io_read,
                    metrics.block_io_write,
                    metrics.pids,
                )
        except Exception as exc:
            logger.error(f"save_metrics failed for {metrics.container_id}: {exc}")

    async def get_recent_metrics(
        self,
        container_id: str,
        minutes: int = 60,
    ) -> List[Any]:
        """SELECT metric rows for *container_id* going back *minutes*.

        Returns a list of ``_Row`` objects with the same attributes as the
        SQLite ``MetricsSample`` ORM rows so that the aggregator, recommender,
        and forecaster can use them without modification.
        """
        cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=minutes)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT time AS timestamp,
                       container_id, container_name,
                       cpu_percent, memory_usage, memory_limit, memory_percent,
                       net_io_in, net_io_out, block_io_read, block_io_write, pids
                FROM   metrics_samples
                WHERE  container_id = $1
                AND    time >= $2
                ORDER  BY time ASC
                """,
                container_id,
                cutoff,
            )
        return [_Row(dict(r)) for r in rows]

    async def cleanup_old_data(self, retention_hours: int = 168) -> None:
        """No-op: TimescaleDB retention policy handles pruning automatically.

        A manual DELETE is still performed as a fallback for deployments where
        ``add_retention_policy`` was not available (non-TimescaleDB Postgres).
        """
        if self._retention_hours > 0:
            # Retention policy already registered in init(); nothing to do.
            return

        # Fallback: plain DELETE for standard Postgres without the extension.
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=retention_hours)
        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM metrics_samples WHERE time < $1", cutoff
                )
            deleted = int(result.split()[-1])
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old metric samples (manual)")
        except Exception as exc:
            logger.error(f"cleanup_old_data failed: {exc}")

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    async def save_alert(self, alert: Any) -> None:
        """INSERT an alert (upsert on PK conflict)."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO alerts
                        (id, container_id, container_name, timestamp,
                         alert_type, metric, current_value, threshold,
                         message, acknowledged)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    alert.alert_id,
                    alert.container_id,
                    alert.container_name,
                    alert.timestamp,
                    alert.alert_type,
                    alert.metric,
                    alert.current_value,
                    alert.threshold,
                    alert.message,
                    getattr(alert, "acknowledged", False),
                )
        except Exception as exc:
            logger.error(f"save_alert failed: {exc}")

    async def get_recent_alerts(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Any]:
        """Return alerts newest-first with pagination."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, container_id, container_name, timestamp,
                       alert_type, metric, current_value, threshold,
                       message, acknowledged
                FROM   alerts
                ORDER  BY timestamp DESC
                LIMIT  $1 OFFSET $2
                """,
                limit,
                offset,
            )
        return [_Row(dict(r)) for r in rows]

    async def count_alerts(self) -> int:
        """Return total alert count."""
        try:
            async with self._pool.acquire() as conn:
                return await conn.fetchval("SELECT COUNT(*) FROM alerts")
        except Exception as exc:
            logger.error(f"count_alerts failed: {exc}")
            return 0

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def save_action(self, action: Any) -> None:
        """INSERT an action record (upsert on PK conflict)."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO actions
                        (id, container_id, container_name, timestamp,
                         action_type, reason, details, success, error_message)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    action.action_id,
                    action.container_id,
                    action.container_name,
                    action.timestamp,
                    action.action_type,
                    action.reason,
                    json.dumps(getattr(action, "details", {})),
                    action.success,
                    getattr(action, "error_message", None),
                )
        except Exception as exc:
            logger.error(f"save_action failed: {exc}")

    async def get_recent_actions(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Any]:
        """Return actions newest-first with pagination."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, container_id, container_name, timestamp,
                       action_type, reason, details, success, error_message
                FROM   actions
                ORDER  BY timestamp DESC
                LIMIT  $1 OFFSET $2
                """,
                limit,
                offset,
            )
        return [_Row(dict(r)) for r in rows]

    async def count_actions(self) -> int:
        """Return total action count."""
        try:
            async with self._pool.acquire() as conn:
                return await conn.fetchval("SELECT COUNT(*) FROM actions")
        except Exception as exc:
            logger.error(f"count_actions failed: {exc}")
            return 0

    # ------------------------------------------------------------------
    # Recommendation cache
    # ------------------------------------------------------------------

    async def save_recommendation_cache(
        self,
        container_id: str,
        payload: dict,
        computed_at: datetime,
    ) -> None:
        """Upsert a recommendation into the cache table."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO recommendation_cache (container_id, computed_at, payload)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (container_id) DO UPDATE
                        SET computed_at = EXCLUDED.computed_at,
                            payload     = EXCLUDED.payload
                    """,
                    container_id,
                    computed_at,
                    json.dumps(payload),
                )
        except Exception as exc:
            logger.error(f"save_recommendation_cache failed for {container_id}: {exc}")

    async def get_recommendation_cache(
        self,
        container_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return cached recommendation dict or None."""
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT payload, computed_at FROM recommendation_cache "
                    "WHERE container_id = $1",
                    container_id,
                )
            if row is None:
                return None
            data = json.loads(row["payload"])
            data["computed_at"] = row["computed_at"].isoformat()
            return data
        except Exception as exc:
            logger.error(f"get_recommendation_cache failed for {container_id}: {exc}")
            return None

    async def get_all_recommendation_caches(self) -> List[Dict[str, Any]]:
        """Return all cached recommendations."""
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT payload, computed_at FROM recommendation_cache"
                )
            results = []
            for row in rows:
                data = json.loads(row["payload"])
                data["computed_at"] = row["computed_at"].isoformat()
                results.append(data)
            return results
        except Exception as exc:
            logger.error(f"get_all_recommendation_caches failed: {exc}")
            return []

    # ------------------------------------------------------------------
    # Forecast cache
    # ------------------------------------------------------------------

    async def save_forecast_cache(
        self,
        container_id: str,
        metric: str,
        horizon_hours: int,
        payload: dict,
        computed_at: datetime,
    ) -> None:
        """Upsert a forecast result into the cache table."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO forecast_cache
                        (container_id, metric, horizon_hours, computed_at, payload)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (container_id, metric, horizon_hours) DO UPDATE
                        SET computed_at = EXCLUDED.computed_at,
                            payload     = EXCLUDED.payload
                    """,
                    container_id,
                    metric,
                    horizon_hours,
                    computed_at,
                    json.dumps(payload),
                )
        except Exception as exc:
            logger.error(f"save_forecast_cache failed for {container_id}/{metric}: {exc}")

    async def get_forecast_cache(
        self,
        container_id: str,
        metric: str,
        horizon_hours: int,
    ) -> Optional[Dict[str, Any]]:
        """Return cached forecast dict or None."""
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT payload, computed_at FROM forecast_cache "
                    "WHERE container_id = $1 AND metric = $2 AND horizon_hours = $3",
                    container_id,
                    metric,
                    horizon_hours,
                )
            if row is None:
                return None
            data = json.loads(row["payload"])
            data["computed_at"] = row["computed_at"].isoformat()
            return data
        except Exception as exc:
            logger.error(
                f"get_forecast_cache failed for {container_id}/{metric}: {exc}"
            )
            return None
