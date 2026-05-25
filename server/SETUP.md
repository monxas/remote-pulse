# Remote-Pulse Server Setup

Complete F1 implementation of ADR-0008 Remote-Pulse server component.

## Quick Start

1. **Install dependencies**:
```bash
cd /Users/ramonkamibayashicarrera/monxas-remote-pulse/server
uv sync --all-extras
```

2. **Configure environment** (copy and edit):
```bash
cp .env.example .env
# Edit .env with your PostgreSQL credentials and JWT secret
```

3. **Run migrations**:
```bash
uv run alembic upgrade head
```

4. **Start server**:
```bash
uv run uvicorn rp_server.main:app --reload --host 0.0.0.0 --port 8080
```

5. **Run tests**:
```bash
uv run pytest -v
```

## Helper Script

The `dev.sh` script provides convenient commands:

```bash
./dev.sh install   # Install dependencies
./dev.sh migrate   # Run migrations
./dev.sh run       # Start server
./dev.sh test      # Run tests
./dev.sh token     # Generate test enrollment token
./dev.sh shell     # Python shell with imports
```

## API Endpoints

### POST /v1/enroll
Enroll new agent with JWT token. Returns host_id and agent config.

### POST /v1/heartbeat
Receive agent heartbeat with metrics. Updates host.last_seen_at.

### GET /v1/hosts
List all registered hosts.

### GET /v1/hosts/{id}
Get host detail with last 100 heartbeats.

### GET /health
Health check endpoint.

## F1 Scope

Current implementation:
- JWT enrollment tokens (HS512)
- Host inventory management
- Heartbeat ingestion
- Basic authentication stubs for F2 Tailscale integration
- PostgreSQL with async SQLAlchemy 2.0
- Alembic migrations
- Pytest test suite with async fixtures

F2 TODO markers in code:
- `deps.py`: Uncomment Tailscale identity enforcement
- `routers/enroll.py`: Add Tailscale authkey generation
- `routers/heartbeat.py`: Verify Tailscale identity matches host

F3 TODO:
- Convert heartbeats/metric_samples to TimescaleDB hypertables
- WebSocket endpoints for real-time push
- Clock skew detection and alerting

## Database Schema

F1 minimal schema (see `alembic/versions/001_initial.py`):
- `hosts` - Host inventory
- `enrollments` - Token tracking
- `heartbeats` - Metrics time-series (designed for future TimescaleDB conversion)

## Development Notes

- All code uses async/await (asyncpg + SQLAlchemy 2.0 async)
- Pydantic v2 for validation
- Type hints required throughout
- Structured logging with structlog
- Tests use in-memory SQLite (switch to testcontainers for CI)

## Architecture

Follows ADR-0008 specifications:
- Server private (homelab-infra deployment target: LXC 280)
- Agent public (separate repo)
- Split authentication: JWT enrollment (bootstrap) + Tailscale identity (steady state) + PocketID OIDC (web)
