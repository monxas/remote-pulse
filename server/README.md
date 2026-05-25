# Remote-Pulse Server

FastAPI server for Remote-Pulse agent fleet monitoring (ADR-0008 F1/F2 implementation).

## Requirements

- Python 3.12+
- uv package manager
- PostgreSQL 16 (local or remote)

## Development Setup

1. Install dependencies:
```bash
uv sync
```

2. Configure environment:
```bash
export POSTGRES_URL="postgresql+asyncpg://user:pass@localhost/rp"
export JWT_SECRET="your-secret-here"
```

3. Run migrations:
```bash
uv run alembic upgrade head
```

4. Start server:
```bash
uv run uvicorn rp_server.main:app --reload --host 0.0.0.0 --port 8080
```

## Testing

```bash
uv run pytest
```

## Database Schema

F1 minimal schema: `hosts`, `enrollments`, `heartbeats` (normal tables, TimescaleDB conversion in F3).

## API Endpoints (F1)

- `POST /v1/enroll` - Agent enrollment with JWT token
- `POST /v1/heartbeat` - Agent heartbeat + metrics
- `GET /v1/hosts` - List all hosts
- `GET /v1/hosts/{id}` - Host detail with recent heartbeats

## Architecture Notes

- Async everything (asyncpg + SQLAlchemy 2.0 async)
- Pydantic v2 for validation
- Tailscale identity enforcement stub ready for F2
- JWT enrollment tokens HS512

See ADR-0008 for complete specification.
