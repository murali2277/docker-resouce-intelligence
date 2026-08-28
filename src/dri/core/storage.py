"""SQLite storage backend for DRI metrics, alerts, actions, and caches."""

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

from sqlalchemy import (
    create_engine,
    Column,
    String,
    Float,
    Integer,
    DateTime,
    Boolean,
    Text,
    Index,
    event,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import sqlalchemy as sa

from ..utils.logger import get_logger
from ..utils.metrics import ContainerMetrics, AggregatedMetrics, Alert, Action
from .storage_base import StorageBackend

logger = get_logger("storage")

Base = declarative_base()


class MetricsSample(Base):
    """ORM model for metrics samples."""
    __tablename__ = "metrics_samples"

    id = Column(Integer, primary_key=True)
    container_id = Column(String(12), nullable=False)
    container_name = Column(String(256))
    timestamp = Column(DateTime, nullable=False)
    cpu_percent = Column(Float)
    memory_usage = Column(Integer)
    memory_limit = Column(Integer)
    memory_percent = Column(Float)
    net_io_in = Column(Integer)
    net_io_out = Column(Integer)
    block_io_read = Column(Integer)
    block_io_write = Column(Integer)
    pids = Column(Integer)

    # Composite index on the two columns used in every query's WHERE/ORDER BY.
    # Replaces the previous separate single-column indexes; SQLite can use this
    # composite index for (container_id,), (container_id, timestamp), and range
    # scans on timestamp within a given container.
    __table_args__ = (
        Index("ix_metrics_samples_cid_ts", "container_id", "timestamp"),
    )


class Container(Base):
    """ORM model for container metadata."""
    __tablename__ = "containers"

    id = Column(String(12), primary_key=True)
    name = Column(String(256), unique=True)
    image = Column(String(256))
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)


class AlertRecord(Base):
    """ORM model for alerts."""
    __tablename__ = "alerts"

    id = Column(String(36), primary_key=True)
    container_id = Column(String(12), index=True)
    container_name = Column(String(256))
    # timestamp is indexed for ORDER BY timestamp DESC queries in get_recent_alerts.
    timestamp = Column(DateTime, index=True)
    alert_type = Column(String(20))
    metric = Column(String(50))
    current_value = Column(Float)
    threshold = Column(Float)
    message = Column(Text)
    acknowledged = Column(Boolean, default=False)


class ActionRecord(Base):
    """ORM model for actions."""
    __tablename__ = "actions"

    id = Column(String(36), primary_key=True)
    container_id = Column(String(12), index=True)
    container_name = Column(String(256))
    # timestamp is indexed for ORDER BY timestamp DESC queries in get_recent_actions.
    timestamp = Column(DateTime, index=True)
    action_type = Column(String(50))
    reason = Column(Text)
    details = Column(Text)  # JSON serialized
    success = Column(Boolean)
    error_message = Column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Background computation cache tables (Item 3)
# ---------------------------------------------------------------------------


class RecommendationCache(Base):
    """Cached recommendation result per container, written by background worker."""
    __tablename__ = "recommendation_cache"

    container_id = Column(String(12), primary_key=True)
    computed_at = Column(DateTime, nullable=False)
    payload = Column(Text, nullable=False)  # JSON blob


class ForecastCache(Base):
    """Cached forecast result per (container, metric, horizon), written by background worker."""
    __tablename__ = "forecast_cache"

    container_id = Column(String(12), primary_key=True)
    metric = Column(String(50), primary_key=True)
    horizon_hours = Column(Integer, primary_key=True)
    computed_at = Column(DateTime, nullable=False)
    payload = Column(Text, nullable=False)  # JSON blob


class SqliteStorage(StorageBackend):
    """SQLite storage backend for metrics and alerts."""

    def __init__(self, db_path: str = "metrics.db"):
        """
        Initialize storage backend.

        Args:
            db_path: Path to SQLite database file, or ":memory:" for in-memory testing
        """
        self._in_memory = db_path == ":memory:"
        if not self._in_memory:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            db_url = f"sqlite:///{self.db_path}"
            connect_args: dict = {"check_same_thread": False}
        else:
            self.db_path = Path(":memory:")
            # Use a shared in-memory DB so all sessions share the same connection
            db_url = "sqlite:///:memory:"
            connect_args = {"check_same_thread": False}

        self.engine = create_engine(
            db_url,
            connect_args=connect_args,
            echo=False,
            # For in-memory, use StaticPool so all sessions share one connection
            **({
                "poolclass": __import__(
                    'sqlalchemy.pool', fromlist=['StaticPool']
                ).StaticPool
            } if self._in_memory else {}),
        )

        # Enable WAL mode for better concurrency (skip for in-memory)
        if not self._in_memory:
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_conn: Any, connection_record: Any) -> None:
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()

        self.SessionLocal = sessionmaker(bind=self.engine)
        self._initialized = False

    async def init(self) -> None:
        """Initialize database schema."""
        loop = asyncio.get_running_loop()

        def _create_tables() -> None:
            Base.metadata.create_all(self.engine)

        try:
            await loop.run_in_executor(None, _create_tables)
            self._initialized = True
            logger.info(f"Storage initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize storage: {e}")
            raise

    async def close(self) -> None:
        """Close database connection."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.engine.dispose)
        logger.info("Storage closed")

    @asynccontextmanager
    async def get_session(self):
        """Get async-wrapped database session."""
        loop = asyncio.get_running_loop()

        def _get_session() -> Session:
            return self.SessionLocal()

        session = await loop.run_in_executor(None, _get_session)
        try:
            yield session
        finally:
            def _close_session() -> None:
                session.close()
            await loop.run_in_executor(None, _close_session)

    async def save_metrics(self, metrics: ContainerMetrics) -> None:
        """Save container metrics sample."""
        async with self.get_session() as session:
            loop = asyncio.get_running_loop()

            def _save() -> None:
                sample = MetricsSample(
                    container_id=metrics.container_id,
                    container_name=metrics.container_name,
                    timestamp=metrics.timestamp,
                    cpu_percent=metrics.cpu_percent,
                    memory_usage=metrics.memory_usage,
                    memory_limit=metrics.memory_limit,
                    memory_percent=metrics.memory_percent,
                    net_io_in=metrics.net_io_in,
                    net_io_out=metrics.net_io_out,
                    block_io_read=metrics.block_io_read,
                    block_io_write=metrics.block_io_write,
                    pids=metrics.pids,
                )
                session.add(sample)
                session.commit()

            try:
                await loop.run_in_executor(None, _save)
            except Exception as e:
                logger.error(f"Failed to save metrics: {e}")

    async def get_recent_metrics(
        self,
        container_id: str,
        minutes: int = 60,
    ) -> List[MetricsSample]:
        """
        Get recent metrics for a container.

        Returns an empty list when no rows match (normal "no data" case).
        Raises on genuine storage/query failures so callers can surface a 500.
        """
        async with self.get_session() as session:
            loop = asyncio.get_running_loop()

            def _get() -> List[MetricsSample]:
                cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
                # Uses the composite index ix_metrics_samples_cid_ts
                return session.query(MetricsSample).filter(
                    MetricsSample.container_id == container_id,
                    MetricsSample.timestamp >= cutoff,
                ).order_by(MetricsSample.timestamp).all()

            # Let storage errors propagate — callers (routes, aggregator) must
            # distinguish "no data" (empty list) from "query failed" (exception).
            return await loop.run_in_executor(None, _get)

    async def save_alert(self, alert: Alert) -> None:
        """Save alert record."""
        async with self.get_session() as session:
            loop = asyncio.get_running_loop()

            def _save() -> None:
                record = AlertRecord(
                    id=alert.alert_id,
                    container_id=alert.container_id,
                    container_name=alert.container_name,
                    timestamp=alert.timestamp,
                    alert_type=alert.alert_type,
                    metric=alert.metric,
                    current_value=alert.current_value,
                    threshold=alert.threshold,
                    message=alert.message,
                    acknowledged=alert.acknowledged,
                )
                session.add(record)
                session.commit()

            try:
                await loop.run_in_executor(None, _save)
            except Exception as e:
                logger.error(f"Failed to save alert: {e}")

    async def save_action(self, action: Action) -> None:
        """Save action record."""
        async with self.get_session() as session:
            loop = asyncio.get_running_loop()

            def _save() -> None:
                record = ActionRecord(
                    id=action.action_id,
                    container_id=action.container_id,
                    container_name=action.container_name,
                    timestamp=action.timestamp,
                    action_type=action.action_type,
                    reason=action.reason,
                    details=json.dumps(action.details),
                    success=action.success,
                    error_message=action.error_message,
                )
                session.add(record)
                session.commit()

            try:
                await loop.run_in_executor(None, _save)
            except Exception as e:
                logger.error(f"Failed to save action: {e}")

    async def cleanup_old_data(self, retention_hours: int = 168) -> None:
        """Clean up metrics older than retention period."""
        async with self.get_session() as session:
            loop = asyncio.get_running_loop()

            def _cleanup() -> int:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
                deleted = session.query(MetricsSample).filter(
                    MetricsSample.timestamp < cutoff
                ).delete()
                session.commit()
                return deleted

            try:
                deleted = await loop.run_in_executor(None, _cleanup)
                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} old metric samples")
            except Exception as e:
                logger.error(f"Failed to cleanup old data: {e}")

    async def get_recent_alerts(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AlertRecord]:
        """
        Get recent alerts ordered newest-first.

        ORDER BY timestamp DESC uses the index on AlertRecord.timestamp.
        Returns empty list when no rows match.
        Raises on genuine storage/query failures.
        """
        async with self.get_session() as session:
            loop = asyncio.get_running_loop()

            def _get() -> List[AlertRecord]:
                return (
                    session.query(AlertRecord)
                    .order_by(AlertRecord.timestamp.desc())
                    .offset(offset)
                    .limit(limit)
                    .all()
                )

            # Propagate storage failures; empty list = valid "no alerts" state.
            return await loop.run_in_executor(None, _get)

    async def get_recent_actions(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ActionRecord]:
        """
        Get recent actions ordered newest-first.

        ORDER BY timestamp DESC uses the index on ActionRecord.timestamp.
        Returns empty list when no rows match.
        Raises on genuine storage/query failures.
        """
        async with self.get_session() as session:
            loop = asyncio.get_running_loop()

            def _get() -> List[ActionRecord]:
                return (
                    session.query(ActionRecord)
                    .order_by(ActionRecord.timestamp.desc())
                    .offset(offset)
                    .limit(limit)
                    .all()
                )

            # Propagate storage failures; empty list = valid "no actions" state.
            return await loop.run_in_executor(None, _get)

    async def count_alerts(self) -> int:
        """Return total number of stored alerts."""
        async with self.get_session() as session:
            loop = asyncio.get_running_loop()

            def _count() -> int:
                return session.query(AlertRecord).count()

            try:
                return await loop.run_in_executor(None, _count)
            except Exception as e:
                logger.error(f"Failed to count alerts: {e}")
                return 0

    async def count_actions(self) -> int:
        """Return total number of stored actions."""
        async with self.get_session() as session:
            loop = asyncio.get_running_loop()

            def _count() -> int:
                return session.query(ActionRecord).count()

            try:
                return await loop.run_in_executor(None, _count)
            except Exception as e:
                logger.error(f"Failed to count actions: {e}")
                return 0

    # -----------------------------------------------------------------------
    # Recommendation / Forecast cache CRUD (Item 3)
    # -----------------------------------------------------------------------

    async def save_recommendation_cache(
        self,
        container_id: str,
        payload: dict,
        computed_at: datetime,
    ) -> None:
        """Upsert a cached recommendation for a container."""
        async with self.get_session() as session:
            loop = asyncio.get_running_loop()

            def _save() -> None:
                existing = session.query(RecommendationCache).filter_by(
                    container_id=container_id
                ).first()
                if existing:
                    existing.payload = json.dumps(payload)
                    existing.computed_at = computed_at
                else:
                    session.add(RecommendationCache(
                        container_id=container_id,
                        computed_at=computed_at,
                        payload=json.dumps(payload),
                    ))
                session.commit()

            try:
                await loop.run_in_executor(None, _save)
            except Exception as e:
                logger.error(f"Failed to save recommendation cache for {container_id}: {e}")

    async def get_recommendation_cache(
        self,
        container_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Return cached recommendation dict (with ``computed_at`` injected) or None.
        """
        async with self.get_session() as session:
            loop = asyncio.get_running_loop()

            def _get() -> Optional[RecommendationCache]:
                return session.query(RecommendationCache).filter_by(
                    container_id=container_id
                ).first()

            try:
                row = await loop.run_in_executor(None, _get)
                if row is None:
                    return None
                data = json.loads(row.payload)
                data["computed_at"] = row.computed_at.isoformat()
                return data
            except Exception as e:
                logger.error(f"Failed to get recommendation cache for {container_id}: {e}")
                return None

    async def get_all_recommendation_caches(self) -> List[Dict[str, Any]]:
        """Return all cached recommendations (used by the list endpoint)."""
        async with self.get_session() as session:
            loop = asyncio.get_running_loop()

            def _get() -> List[RecommendationCache]:
                return session.query(RecommendationCache).all()

            try:
                rows = await loop.run_in_executor(None, _get)
                results = []
                for row in rows:
                    data = json.loads(row.payload)
                    data["computed_at"] = row.computed_at.isoformat()
                    results.append(data)
                return results
            except Exception as e:
                logger.error(f"Failed to get all recommendation caches: {e}")
                return []

    async def save_forecast_cache(
        self,
        container_id: str,
        metric: str,
        horizon_hours: int,
        payload: dict,
        computed_at: datetime,
    ) -> None:
        """Upsert a cached forecast result."""
        async with self.get_session() as session:
            loop = asyncio.get_running_loop()

            def _save() -> None:
                existing = session.query(ForecastCache).filter_by(
                    container_id=container_id,
                    metric=metric,
                    horizon_hours=horizon_hours,
                ).first()
                if existing:
                    existing.payload = json.dumps(payload)
                    existing.computed_at = computed_at
                else:
                    session.add(ForecastCache(
                        container_id=container_id,
                        metric=metric,
                        horizon_hours=horizon_hours,
                        computed_at=computed_at,
                        payload=json.dumps(payload),
                    ))
                session.commit()

            try:
                await loop.run_in_executor(None, _save)
            except Exception as e:
                logger.error(
                    f"Failed to save forecast cache for {container_id}/{metric}: {e}"
                )

    async def get_forecast_cache(
        self,
        container_id: str,
        metric: str,
        horizon_hours: int,
    ) -> Optional[Dict[str, Any]]:
        """Return cached forecast dict (with ``computed_at`` injected) or None."""
        async with self.get_session() as session:
            loop = asyncio.get_running_loop()

            def _get() -> Optional[ForecastCache]:
                return session.query(ForecastCache).filter_by(
                    container_id=container_id,
                    metric=metric,
                    horizon_hours=horizon_hours,
                ).first()

            try:
                row = await loop.run_in_executor(None, _get)
                if row is None:
                    return None
                data = json.loads(row.payload)
                data["computed_at"] = row.computed_at.isoformat()
                return data
            except Exception as e:
                logger.error(
                    f"Failed to get forecast cache for {container_id}/{metric}: {e}"
                )
                return None


# ---------------------------------------------------------------------------
# Backward-compatibility alias
# ---------------------------------------------------------------------------

#: ``MetricsStorage`` is kept as a public alias for ``SqliteStorage`` so that
#: all existing import sites (tests, main.py, etc.) continue to work without
#: any changes.  New code should prefer importing ``SqliteStorage`` directly.
MetricsStorage = SqliteStorage
