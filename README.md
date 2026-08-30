# Docker Resource Intelligence (DRI)

A lightweight, intelligent monitoring and self-healing agent that tracks, restricts, and optimizes container resource consumption on Docker hosts — preventing "noisy neighbors" and Out-Of-Memory (OOM) crashes.

---
 
## Features

- **Real-Time Metrics** — Stream CPU, memory, I/O, and network stats from Docker containers
- **Moving Averages** — 5, 15, and 60-minute windows to detect resource trends
- **Anomaly Detection** — Identify memory spikes and predict OOM conditions before they happen
- **Policy Engine** — YAML-based rules for per-image and per-container resource limits
- **Automated Actions**:
  - **Throttle** — Reduce CPU shares/quota and memory limits on offending containers
  - **Isolate** — Restrict containers to specific CPU sets
  - **Heal** — Gracefully restart containers before OOM crashes
  - **Webhooks** — Trigger custom HTTP callbacks on threshold events
- **REST API** — FastAPI-powered endpoints for metrics, policies, and action history
- **Dashboard** — React + Vite UI for visualizing container metrics in real time
- **Prometheus Integration** — Export agent metrics to Prometheus / Grafana
- **SQLite Storage** — Lightweight local metrics database (optional InfluxDB export)
- **Docker Event Tracking** — Monitor OOM, die, create, stop, and restart events

---

## Architecture

```
Docker Daemon
    |
    v
Stats Collector  -->  Docker Event Listener
    |
    v
Metrics Storage (SQLite)
    |
    v
Aggregator (Moving Averages & Anomaly Detection)
    |
    v
Policy Engine (Rule Evaluation)
    |
    v
Actions (Throttle / Isolate / Heal / Webhooks)
    |
    v
HTTP API (FastAPI :8000)  -->  Dashboard (Vite :5173)
    |
    v
Prometheus Metrics (:9090)
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.9 or newer |
| Docker Desktop / Engine | 20.10 or newer |
| Node.js (dashboard only) | 18 or newer |

> **Windows note**: Docker Desktop must be running before starting the agent. `uvloop` is Linux-only and is automatically skipped on Windows.

---

## Project Structure

```
docker-resouce-intelligence/
├── src/dri/
│   ├── core/          # Collector, storage, aggregator, policy engine
│   ├── actions/       # Throttle, isolate, heal action handlers
│   ├── events/        # Docker event listener
│   ├── api/           # FastAPI routes, models, server
│   ├── utils/         # Logger, metrics types, webhooks
│   ├── config.py      # Configuration loader & schema
│   └── main.py        # Agent entry point
├── config/
│   └── config.yaml    # Main configuration file
├── dashboard/         # React + Vite frontend
├── deployment/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── prometheus.yml
├── tests/             # Unit & integration tests
├── requirements.txt
└── pyproject.toml
```

---

## Setup & Run

### 1 — Clone the repository

```bash
git clone https://github.com/murali2277/docker-resouce-intelligence.git
cd docker-resouce-intelligence
```

---

### 2 — Install Python dependencies

> It is recommended to use a virtual environment.

```bash
# Create and activate a virtual environment (optional but recommended)
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# Install all dependencies
pip install -r requirements.txt
```

---

### 3 — Start Prometheus (optional but recommended)

Prometheus is provided as a Docker service. Start it before running the agent so metrics are scraped automatically:

```bash
cd deployment
docker-compose up -d
cd ..
```

This starts:
- `dri-prometheus` — Prometheus on **http://localhost:9090**

> The `dri-agent` Docker service in `docker-compose.yml` requires a full Docker image build. For local development it is easier to run the agent directly with Python (Step 4).

---

### 4 — Run the DRI agent

From the **project root**:

```bash
python -m dri.main --config config/config.yaml
```

Expected startup output:

```
[INFO] dri.config    - Loading config from config\config.yaml
[INFO] dri.config    - Config loaded successfully
[INFO] dri.main      - Initializing DRI agent...
[INFO] dri.main      - Connected to Docker daemon
[INFO] dri.storage   - Storage initialized at \var\lib\dri\metrics.db
[INFO] dri.collector - Connected to Docker daemon
[INFO] dri.main      - DRI agent initialized successfully
[INFO] dri.main      - Starting metrics collection (interval: 5s)
[INFO] dri.main      - Starting metrics aggregation (interval: 10s)
[INFO] dri.main      - Starting policy checks (interval: 10s)
[INFO] dri.main      - Starting Docker event listener
```

The agent REST API is available at **http://localhost:8000**

---

### 5 — Run the frontend dashboard

In a **separate terminal**:

```bash
cd dashboard
npm install
npm run dev
```

The frontend dashboard opens at **http://localhost:5173** and automatically proxies requests to the backend API at `http://localhost:8000`.

**Four Polling Views:**
- **Metrics** — live container metrics (`/api/v1/metrics`), polling interval 5–10s
- **Alerts** — active and acknowledged alert feed (`/api/v1/alerts`), polling interval 5–10s
- **Action History** — automated action log (`/api/v1/actions/history`), polling interval 5–10s
- **Policies** — active global & container policy rules (`/api/v1/policies`), polling interval 5–10s

To point the dashboard at a custom backend URL, set `VITE_API_BASE`:

```bash
VITE_API_BASE=http://192.168.1.10:8000 npm run dev
```

---


## Full Docker Deployment

To run the **entire stack** (agent + dashboard + Prometheus) as containers:

```bash
cd deployment
docker-compose up -d --build
```

The dashboard is now included in the default deployment.

| Service | URL |
|---|---|
| DRI Dashboard | http://localhost:5173 |
| DRI Agent API | http://localhost:8000 |
| Prometheus | http://localhost:9090 |

To stop all services:

```bash
docker-compose down
```

---

## Configuration

Edit `config/config.yaml` to customise the agent behaviour.

```yaml
log_level: INFO
log_json: false

collector_interval: 5       # seconds between metric samples
aggregator_interval: 10     # seconds between aggregations
policy_check_interval: 10   # seconds between policy evaluations

storage:
  sqlite_path: "/var/lib/dri/metrics.db"
  retention_hours: 24
  influxdb_enabled: false   # set true to enable InfluxDB export

api:
  host: "0.0.0.0"
  port: 8000
  enable_cors: true
  prometheus_metrics: true

actions:
  throttle:
    cpu_shares: 512
    memory_limit: "512m"
  isolate_cpuset: "0-1"
  webhook_url: null         # set a URL to receive alert payloads
  restart_grace_period: 30

global_policy:
  name: "global"
  enabled: true
  rules:
    - metric: "memory"
      operator: ">="
      value: 85.0
      duration_seconds: 60
      action: "warning"

    - metric: "memory"
      operator: ">="
      value: 95.0
      duration_seconds: 10
      action: "throttle"
```

### Per-container policy example

```yaml
container_policies:
  - name: "redis-policy"
    selector:
      image: "redis"
    enabled: true
    rules:
      - metric: "memory"
        operator: ">="
        value: 90.0
        duration_seconds: 30
        action: "throttle"
```

---

## REST API Reference

Base URL: `http://localhost:8000`

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Agent health check |
| `GET` | `/api/v1/metrics` | Current metrics for all containers |
| `GET` | `/api/v1/metrics?container_id=<id>` | Metrics for a specific container |
| `GET` | `/api/v1/alerts` | Recent triggered alerts |
| `GET` | `/api/v1/actions/history` | Action execution history |
| `GET` | `/api/v1/policies` | Active policies |
| `GET` | `/api/v1/forecast/<container_id>` | Resource usage forecast |
| `GET` | `/metrics` | Prometheus-format metrics |

### Quick examples

```bash
# Health check
curl http://localhost:8000/health

# All container metrics
curl http://localhost:8000/api/v1/metrics

# Filter by container ID (first 12 chars)
curl "http://localhost:8000/api/v1/metrics?container_id=abc123def456"

# Recent alerts
curl http://localhost:8000/api/v1/alerts

# Prometheus scrape endpoint
curl http://localhost:8000/metrics
```

---

## Development

### Install dev dependencies

```bash
pip install -e ".[dev]"
```

### Run tests

```bash
pytest tests/
```

### Run specific test phases

```bash
pytest tests/test_phase1.py  # Core collector & storage
pytest tests/test_phase2.py  # Aggregator & policy engine
pytest tests/test_phase3.py  # Actions
pytest tests/test_phase4.py  # API endpoints
```

### Lint & format

```bash
black src/        # auto-format
flake8 src/       # lint
mypy src/         # type check
```

### Dashboard development

```bash
cd dashboard
npm run lint      # run oxlint
npm run build     # production build into dist/
npm run preview   # preview the production build
```

---

## Optional Extras

### Enable InfluxDB export

```bash
pip install ".[influxdb]"
```

Then set in `config.yaml`:

```yaml
storage:
  influxdb_enabled: true
  influxdb_url: "http://influxdb:8086"
  influxdb_token: "<your-token>"
  influxdb_org: "dri"
  influxdb_bucket: "metrics"
```

### Enable forecasting (statsmodels)

```bash
pip install ".[forecasting]"
```

Enables ARIMA-based forecasting at `/api/v1/forecast/<container_id>`. Falls back to linear regression when not installed.

### Enable uvloop (Linux / macOS only)

```bash
pip install ".[perf]"
```

---

## Troubleshooting

### Agent fails to connect to Docker daemon

Make sure Docker Desktop (Windows/macOS) or the Docker daemon (Linux) is running:

```bash
docker info
```

On Linux, verify the socket is accessible:

```bash
ls -la /var/run/docker.sock
```

### `Event callback failed` errors

This was caused by passing extra keyword arguments to the standard Python logger. Fixed in the current version of `src/dri/main.py`. If you see this error, ensure you are on the latest code.

### Storage path errors on Windows

The default SQLite path `/var/lib/dri/metrics.db` uses a Unix-style path. On Windows, change `sqlite_path` in `config.yaml` to a valid Windows path:

```yaml
storage:
  sqlite_path: "C:/ProgramData/dri/metrics.db"
```

### High memory usage

Reduce the retention window in `config.yaml`:

```yaml
storage:
  retention_hours: 12
```

### High CPU / collection overhead

Increase collection intervals:

```yaml
collector_interval: 10
aggregator_interval: 15
policy_check_interval: 15
```

### Dashboard not loading data

Ensure the DRI agent is running and CORS is enabled:

```yaml
api:
  enable_cors: true
```

---

## Performance Characteristics

| Metric | Value |
|---|---|
| Agent memory | ~50–100 MB (scales with container count) |
| CPU overhead | < 1% on typical workloads (50–100 containers) |
| Metric latency | Sub-second collection, seconds for aggregation |
| Storage growth | ~1 KB/sample (24 h retention ≈ 2–5 GB) |

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Add tests for new functionality
4. Run the full test suite: `pytest tests/`
5. Submit a pull request

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Links

- **Issues**: https://github.com/murali2277/docker-resouce-intelligence/issues
- **Discussions**: https://github.com/murali2277/docker-resouce-intelligence/discussions
