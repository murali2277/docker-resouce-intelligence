# TimescaleDB Migration Guide

This guide explains how to switch the Docker Resource Intelligence (DRI) agent from its default SQLite storage backend to TimescaleDB.

## Why TimescaleDB?
TimescaleDB is built on PostgreSQL and is optimized for time-series data. It natively supports partitioning data by time (hypertables) and managing data retention policies. This makes it ideal for high-volume, long-term metrics storage in production.

## 1. Setting up TimescaleDB
You can run TimescaleDB locally using Docker or connect to an existing TimescaleDB instance.

### Using Docker Compose
If you want to run it via docker compose, you can use the official image:
```yaml
services:
  timescaledb:
    image: timescale/timescaledb:latest-pg14
    environment:
      - POSTGRES_USER=dri
      - POSTGRES_PASSWORD=secret
      - POSTGRES_DB=dri
    ports:
      - "5432:5432"
```

### Manual Database Setup
If using an existing PostgreSQL server, ensure the `timescaledb` extension is enabled on the target database:
```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;
```

## 2. Configuration
The application reads the storage backend from `config/config.yaml`. To enable TimescaleDB, modify the `storage` section as follows:

```yaml
storage:
  backend: "timescaledb"
  timescaledb_url: "postgresql://dri:secret@localhost:5432/dri"
  retention_hours: 168 # 7 days
```

### Connection String Format
The `timescaledb_url` must follow the standard SQLAlchemy PostgreSQL connection string format:
`postgresql://[user]:[password]@[host]:[port]/[dbname]`

## 3. Dependencies
The TimescaleDB backend uses SQLAlchemy with the default `psycopg2` driver. Ensure you have the required dependencies installed (e.g., via the extra in your `pyproject.toml` or `requirements.txt`):
```bash
pip install psycopg2-binary
```
*(Or ensure you install the package with the `[timescaledb]` extra if configured).*

## Note on Data Migration
This switch **does not automatically migrate** existing data from SQLite to TimescaleDB. When you restart the agent with TimescaleDB enabled, it will begin collecting and storing new metrics in TimescaleDB. Old metrics in SQLite will remain untouched in your configured `sqlite_path`. If data backfill is required, it must be performed manually.
