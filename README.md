# Docker Resource Intelligence

A lightweight, intelligent monitoring and self-healing agent that tracks, restricts, and optimizes container resource consumption on Docker hosts to prevent "noisy neighbors" and Out-Of-Memory (OOM) crashes.

## Features

- **Real-Time Metrics**: Stream CPU, memory, I/O, and network metrics from Docker containers
- **Moving Averages**: Calculate 5, 15, and 60-minute moving averages to detect trends
- **Anomaly Detection**: Identify memory spikes and predict OOM conditions
- **Policy Engine**: YAML-based rules for per-image and per-container resource policies
- **Dynamic Actions**:
  - **Throttle**: Reduce CPU shares/quota and memory limits
  - **Isolate**: Restrict containers to specific CPU sets
  - **Heal**: Gracefully restart containers before OOM crashes
  - **Webhooks**: Trigger custom actions via HTTP callbacks
- **HTTP API**: RESTful API for metrics, policies, and action history
- **Prometheus Integration**: Export agent metrics for monitoring
- **SQLite Storage**: Lightweight local metrics database with optional InfluxDB export
- **Event Tracking**: Monitor Docker daemon events (OOM, die, create, etc.)

## Architecture

```
Docker Daemon
    ↓
Stats Collector (Docker API)
    ↓
Metrics Storage (SQLite)
    ↓
Aggregator (Moving Averages & Anomaly Detection)
    ↓
Policy Engine (Rule Evaluation)
    ↓
Actions (Throttle, Isolate, Heal, Webhooks)
    ↓
HTTP API (Metrics, Policies, History)
```

## Quick Start

### Prerequisites

- Docker 20.10+
- Python 3.9+ (or use the Docker image)
- Linux host (supports Docker)

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/murali2277/docker-resouce-intelligence.git
   cd docker-resouce-intelligence
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure policies in `config/config.yaml`

4. Run the agent:
   ```bash
   python -m dri.main --config config/config.yaml
   ```

### Docker Deployment

Run as a container with docker-compose:

```bash
cd deployment
docker-compose up -d
```

The agent will be available at `http://localhost:8000`

## Configuration

Edit `config/config.yaml` to customize:

- **Thresholds**: CPU/memory limits for warnings, throttling, isolation
- **Actions**: Define what happens when thresholds are exceeded
- **Storage**: Local SQLite or optional InfluxDB export
- **API**: Server port and CORS settings

Example policy:

```yaml
global_policy:
  name: "global"
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

## API Endpoints

- `GET /health` - Health check
- `GET /api/v1/metrics` - Current container metrics
- `GET /api/v1/alerts` - Recent alerts
- `GET /api/v1/actions/history` - Action execution history
- `GET /api/v1/policies` - Current policies
- `GET /metrics` - Prometheus metrics

## Monitoring Metrics

Access the HTTP API:

```bash
# Current metrics
curl http://localhost:8000/api/v1/metrics

# Specific container
curl http://localhost:8000/api/v1/metrics?container_id=abc123

# Alerts
curl http://localhost:8000/api/v1/alerts

# Prometheus metrics
curl http://localhost:8000/metrics
```

## Development

Install development dependencies:

```bash
pip install -e .[dev]
```

Run tests:

```bash
pytest tests/
```

Format code:

```bash
black src/
```

## Project Structure

```
docker-resouce-intelligence/
├── src/dri/
│   ├── core/              # Core components (collector, storage, engine)
│   ├── actions/           # Action handlers (throttle, isolate, heal)
│   ├── events/            # Docker event listener
│   ├── api/               # HTTP API (FastAPI)
│   ├── utils/             # Utilities (logger, metrics, webhooks)
│   ├── config.py          # Configuration loader
│   └── main.py            # Agent entry point
├── config/                # Configuration files
├── deployment/            # Docker & K8s deployment
├── tests/                 # Unit & integration tests
└── docs/                  # Documentation
```

## Performance Characteristics

- **Memory**: ~50-100 MB base usage (grows with container count)
- **CPU**: <1% on typical workloads (50-100 containers)
- **Latency**: Sub-second metric collection, seconds for aggregation
- **Storage**: ~1 KB per metric sample (SQLite with 24h retention = ~2-5 GB)

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## Troubleshooting

### Agent not connecting to Docker daemon

Ensure the Docker socket is accessible:

```bash
ls -la /var/run/docker.sock
```

### Memory usage growing

Check retention settings and cleanup old data:

```python
# Adjust retention_hours in config
storage:
  retention_hours: 12  # Reduce retention period
```

### High CPU usage

Increase metric collection intervals:

```yaml
collector_interval: 10  # seconds
aggregator_interval: 15 # seconds
policy_check_interval: 15 # seconds
```

## License

MIT License - See LICENSE file for details

## Authors

DevOps Team

## Support

- Documentation: [docs/](docs/)
- Issues: [GitHub Issues](https://github.com/murali2277/docker-resouce-intelligence/issues)
- Discussions: [GitHub Discussions](https://github.com/murali2277/docker-resouce-intelligence/discussions)