# Docker Resource Intelligence (DRI)

**Your containers, watched over, right-sized, and self-healing, with almost no overhead.**

DRI is a lightweight agent that runs beside your Docker daemon, learns how each container actually behaves, and then helps you keep every workload healthy: it catches noisy neighbors, predicts Out-Of-Memory (OOM) crashes before they happen, and tells you exactly what resource limits each container should have.

---

## Why DRI exists

Anyone who has run more than a handful of containers has met the same three problems:

1. **Noisy neighbors.** One greedy container quietly starves the others, and nobody notices until users do.
2. **Surprise OOM kills.** A slow memory leak or a sudden spike takes a service down at 3 a.m. and the only clue is an exit code of 137.
3. **Guesswork limits.** CPU and memory limits are usually copied from a blog post or set to "something big", so teams either overpay for idle capacity or get throttled and killed.

Full observability stacks can answer these questions, but they are heavy to deploy and they mostly *show* you graphs. You still have to interpret them and act.

**DRI was built to close that gap with one small agent that observes, decides, and acts:**

- It **measures** every container in real time.
- It **understands** behavior using moving averages, statistical anomaly detection, leak detection, and forecasting.
- It **recommends** right-sized limits based on real p95 usage, not guesses.
- It **acts** by throttling, isolating, or gracefully restarting containers, and notifying you through webhooks, so problems are fixed before they become incidents.

The goal is simple: **fewer pages, fewer wasted resources, and more confidence in your Docker hosts.**

---

## What you get

- **Real-Time Metrics**: CPU, memory, network, block I/O, and PIDs streamed from every running container, collected in parallel so one slow container never blocks the rest.
- **Trend Awareness**: 5, 15, and 60-minute moving averages backed by a memory + database hybrid, so long windows stay accurate.
- **Smart Anomaly Detection**: per-container z-score analysis, memory growth-rate spikes, and OOM prediction *before* the kill happens.
- **Right-Sizing Recommendations**: p95-based CPU and memory limits with a configurable safety margin, confidence tiers, data-completeness reporting, idle (scale-to-zero) detection, and restart-aware memory-leak detection.
- **Usage Forecasting**: project CPU or memory up to 7 days ahead with confidence intervals (Simple Exponential Smoothing, or linear regression as a zero-dependency fallback).
- **Policy Engine**: YAML rules with durations, per-image and per-container overrides, and hot-reload.
- **Automated Actions**:
  - **Throttle**: reduce CPU shares/quota and memory limits on offending containers
  - **Isolate**: pin containers to specific CPU sets
  - **Heal**: gracefully restart containers before they crash
  - **Webhooks**: trigger custom HTTP callbacks, protected by a circuit breaker so a dead endpoint is never hammered
- **Docker Event Tracking**: OOM, die, start, stop, create, and destroy events, plus automatic restart counting.
- **Container Lifecycle Awareness**: stopped containers are flagged and cleanly evicted after a grace period.
- **Modern Dashboard**: a React + Vite control-tower UI with seven live views.
- **REST API**: FastAPI with optional API-key auth, structured JSON errors, and cached recommendations/forecasts for instant responses.
- **Prometheus Integration**: export agent metrics to Prometheus / Grafana.
- **Pluggable Storage**: SQLite by default (zero setup), TimescaleDB for production-scale history, optional InfluxDB export.

---

## Architecture

```
Docker Daemon
    |
    v
Stats Collector (parallel)  -->  Docker Event Listener
    |                                   |
    v                                   v
Metrics Storage (SQLite / TimescaleDB) <-- Events & Restart Tracking
    |
    v
Aggregator (Moving Averages & Anomaly Detection)
    |
    +--> Recommender & Forecaster (background cache worker)
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
│   ├── core/          # Collector, storage (SQLite/Timescale), aggregator,
│   │                  # policy engine, recommender, forecaster, cache worker
│   ├── actions/       # Throttle, isolate, heal, scale action handlers
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
│   ├── Dockerfile.dashboard
│   ├── docker-compose.yml
│   └── prometheus.yml
├── docs/              # Guides (e.g. TimescaleDB migration)
├── tests/             # Unit & integration tests
├── requirements.txt
└── pyproject.toml
```

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/murali2277/docker-resouce-intelligence.git
cd docker-resouce-intelligence
```

### 2. Install Python dependencies

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Start Prometheus (optional but recommended)

```bash
cd deployment
docker-compose up -d prometheus
cd ..
```

Prometheus will be available at **http://localhost:9090**.

### 4. Run the DRI agent

From the project root:

```bash
python -m dri.main --config config/config.yaml
```

Expected startup output:

```
[INFO] dri.main      - Initializing DRI agent...
[INFO] dri.main      - Connected to Docker daemon
[INFO] dri.storage   - Storage initialized
[INFO] dri.collector - Connected to Docker daemon
[INFO] dri.main      - DRI agent initialized successfully
[INFO] dri.main      - Starting metrics collection (interval: 5s)
[INFO] dri.main      - Starting metrics aggregation (interval: 10s)
[INFO] dri.main      - Starting policy checks (interval: 10s)
[INFO] dri.main      - Starting Docker event listener
```

The REST API is now live at **http://localhost:8000** (interactive docs at `/docs`).

### 5. Open the dashboard

In a **separate terminal**:

```bash
cd dashboard
npm install
npm run dev
```

The dashboard opens at **http://localhost:5173**. To point it at a different backend:

```bash
VITE_API_BASE=http://192.168.1.10:8000 VITE_API_KEY=your-api-key npm run dev
```

**Dashboard views:**

| View | What it shows |
|---|---|
| **Overview** | Agent health, live per-container CPU/memory, I/O, restart counts, anomaly and stopped badges, with a click-through detail panel |
| **Alert Feed** | Sortable feed of policy violations |
| **Recommendations** | Right-sized CPU/memory limits, confidence tier, leak and idle signals |
| **Forecast** | On-demand CPU/memory projection with confidence intervals |
| **Actions History** | Everything DRI did automatically, and whether it worked |
| **Docker Events** | OOM / die / start / stop lifecycle stream with search |
| **Policies** | The active global and per-container rules |

The polling interval (5–60s) is adjustable from the dashboard's Settings panel.

---

## Full Docker Deployment

Run the **entire stack** (agent + dashboard + Prometheus) as containers:

```bash
cd deployment
docker-compose up -d --build
```

| Service | URL |
|---|---|
| DRI Dashboard | http://localhost:5173 |
| DRI Agent API | http://localhost:8000 |
| Prometheus | http://localhost:9090 |

Stop everything with `docker-compose down`.

---

## Configuration

Edit `config/config.yaml` to customise the agent.

```yaml
log_level: INFO
log_json: false

collector_interval: 5       # seconds between metric samples
aggregator_interval: 10     # seconds between aggregations
policy_check_interval: 10   # seconds between policy evaluations
container_status_interval: 15          # poll for stopped/started containers
container_status_cleanup_minutes: 5    # evict stopped containers after this long

storage:
  backend: "sqlite"         # or "timescaledb"
  sqlite_path: "metrics.db"
  retention_hours: 168      # keep >= recommender lookback (7 days)

api:
  host: "0.0.0.0"
  port: 8000
  enable_cors: true
  allowed_origins: ["*"]    # set explicit origins in production
  prometheus_metrics: true
  api_key: null             # set a secret to require X-Api-Key

actions:
  throttle:
    cpu_shares: 512
    memory_limit: "512m"
  isolate_cpuset: "0-1"
  webhook_url: null
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

    - metric: "memory_growth_rate_5m"
      operator: ">"
      value: 20.0
      duration_seconds: 30
      action: "warning"

    - metric: "memory"
      operator: ">="
      value: 95.0
      duration_seconds: 10
      action: "throttle"
```

Available policy metrics: `cpu`, `cpu_5m`, `cpu_15m`, `cpu_60m`, `memory`, `memory_5m`, `memory_15m`, `memory_60m`, `memory_growth_rate_1m`, `memory_growth_rate_5m`.

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

### Authentication

By default (`api_key: null`) authentication is off, which keeps local development frictionless. For any non-localhost deployment, set `api.api_key`. Then all `/api/v1/*` data endpoints and `/metrics` require an `X-Api-Key` header and return `401` otherwise. Health endpoints stay open so liveness probes keep working.

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/health`, `/api/v1/health` | No | Agent health and live counters |
| `GET` | `/api/v1/metrics[?container_id=<id>]` | When configured | Current metrics for all (or one) container |
| `GET` | `/api/v1/alerts` | When configured | Recent triggered alerts (paginated) |
| `GET` | `/api/v1/actions/history` | When configured | Action execution history (paginated) |
| `GET` | `/api/v1/events` | When configured | Docker lifecycle events (paginated, filterable) |
| `GET` | `/api/v1/policies` | When configured | Active policies |
| `GET` | `/api/v1/recommendations` | When configured | Right-sized limits per container (cached; `?force=true` to recompute) |
| `GET` | `/api/v1/forecast/<container_id>` | When configured | Usage forecast (cached; `?force=true` to recompute) |
| `GET` | `/metrics` | When configured | Prometheus-format metrics |

### Quick examples

```bash
curl http://localhost:8000/health

# With api_key configured:
curl -H "X-Api-Key: your-secret" http://localhost:8000/api/v1/metrics
curl -H "X-Api-Key: your-secret" "http://localhost:8000/api/v1/recommendations?lookback_days=7&safety_margin=0.2"
curl -H "X-Api-Key: your-secret" "http://localhost:8000/api/v1/forecast/abc123def456?horizon_hours=24&metric=memory_percent"
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

The suite covers the collector, storage, aggregation, policy engine, recommender, forecaster, auth/CORS, Docker events, and API caching. TimescaleDB integration tests run only when `TIMESCALE_TEST_URL` is set:

```bash
export TIMESCALE_TEST_URL=postgresql://dri:secret@localhost:5432/dri
pytest tests/test_timescale.py -v
```

### Lint & format

```bash
black src/
flake8 src/
mypy src/
```

### Dashboard development

```bash
cd dashboard
npm run lint      # oxlint
npm run build     # production build into dist/
npm run preview   # preview the production build
```

---

## Optional Extras

### TimescaleDB (production-scale history)

Switch to TimescaleDB for hypertable partitioning and native retention policies. See [docs/timescaledb-migration.md](docs/timescaledb-migration.md).

```bash
pip install ".[timescaledb]"
```

### InfluxDB export

```bash
pip install ".[influxdb]"
```

### Advanced forecasting (statsmodels)

```bash
pip install ".[forecasting]"
```

Enables Simple Exponential Smoothing; DRI falls back to linear regression when it is not installed.

### uvloop (Linux / macOS)

```bash
pip install ".[perf]"
```

---

## Troubleshooting

**Agent can't connect to Docker.** Make sure Docker is running (`docker info`). On Linux, check the socket: `ls -la /var/run/docker.sock`.

**Storage path errors on Windows.** Use a Windows-style path, e.g. `sqlite_path: "C:/ProgramData/dri/metrics.db"`.

**No recommendations yet.** Recommendations need at least 10 samples per container. They appear after a few minutes of collection, and confidence improves as more history builds up.

**High memory usage.** Lower `storage.retention_hours` (for example `12`), but keep it at or above your recommender lookback if you want full-window recommendations.

**High CPU / collection overhead.** Increase the intervals:

```yaml
collector_interval: 10
aggregator_interval: 15
policy_check_interval: 15
```

**Dashboard not loading data.** Confirm the agent is running, CORS is enabled, and `VITE_API_BASE` / `VITE_API_KEY` match your backend.

---

## Performance Characteristics

| Metric | Value |
|---|---|
| Agent memory | ~50–100 MB (scales with container count) |
| CPU overhead | < 1% on typical workloads (50–100 containers) |
| Metric latency | Sub-second collection, seconds for aggregation |
| API response | Recommendations and forecasts served from cache |
| Storage growth | ~150 bytes/sample; about 18 MB per container per 7 days at 5s sampling |

---

## Roadmap

- Smarter automated remediation (auto-apply accepted recommendations)
- Multi-host support with a central dashboard
- More notification channels (Slack, email, PagerDuty)
- Config-driven runtime API URL for the dashboard container

Ideas and contributions are very welcome.

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Add tests for new functionality
4. Run the full test suite: `pytest tests/`
5. Submit a pull request

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

## Links

- **Issues**: https://github.com/murali2277/docker-resouce-intelligence/issues
- **Discussions**: https://github.com/murali2277/docker-resouce-intelligence/discussions