"""SQLite storage for metrics and alerts."""

import asyncio
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Boolean, Text, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import sqlalchemy as sa

from ..utils.logger import get_logger
from ..utils.metrics import ContainerMetrics, AggregatedMetrics, Alert, Action

logger = get_logger("storage")

Base = declarative_base()


class MetricsSample(Base):
    """ORM model for metrics samples."""
    __tablename__ = "metrics_samples"

    id = Column(Integer, primary_key=True)
    container_id = Column(String(12), index=True)
    container_name = Column(String(256))
    timestamp = Column(DateTime, index=True)
    cpu_percent = Column(Float)
    memory_usage = Column(Integer)
    memory_limit = Column(Integer)
    memory_percent = Column(Float)
    net_io_in = Column(Integer)
    net_io_out = Column(Integer)
    block_io_read = Column(Integer)
    block_io_write = Column(Integer)
    pids = Column(Integer)


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
    timestamp = Column(DateTime, index=True)
    action_type = Column(String(50))
    reason = Column(Text)
    details = Column(Text)  # JSON serialized
    success = Column(Boolean)
    error_message = Column(Text, nullable=True)


class MetricsStorage:
    """SQLite storage backend for metrics and alerts."""

    def __init__(self, db_path: str = "metrics.db"):
        """
        Initialize storage backend.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
            echo=False,
        )

        # Enable WAL mode for better concurrency
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
        loop = asyncio.get_event_loop()

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
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.engine.dispose)
        logger.info("Storage closed")

    @asynccontextmanager
    async def get_session(self):
        """Get async-wrapped database session."""
        loop = asyncio.get_event_loop()

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
            loop = asyncio.get_event_loop()

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
        """Get recent metrics for a container."""
        async with self.get_session() as session:
            loop = asyncio.get_event_loop()

            def _get() -> List[MetricsSample]:
                cutoff = datetime.utcnow() - timedelta(minutes=minutes)
                return session.query(MetricsSample).filter(
                    MetricsSample.container_id == container_id,
                    MetricsSample.timestamp >= cutoff,
                ).order_by(MetricsSample.timestamp).all()

            try:
                results = await loop.run_in_executor(None, _get)
                return results
            except Exception as e:
                logger.error(f"Failed to get metrics: {e}")
                return []

    async def save_alert(self, alert: Alert) -> None:
        """Save alert record."""
        async with self.get_session() as session:
            loop = asyncio.get_event_loop()

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
        import json

        async with self.get_session() as session:
            loop = asyncio.get_event_loop()

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

    async def cleanup_old_data(self, retention_hours: int = 24) -> None:
        """Clean up metrics older than retention period."""
        async with self.get_session() as session:
            loop = asyncio.get_event_loop()

            def _cleanup() -> int:
                cutoff = datetime.utcnow() - timedelta(hours=retention_hours)
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
