# Testing

Remote-Pulse uses **pytest** for both the agent and the server, plus a
small integration suite under the top-level `tests/`.

## Test taxonomy

| Layer | Where | Runs against |
|-------|-------|--------------|
| **Unit** | `agent/tests/`, `server/tests/` | Pure-Python; mocked Tailscale headers; SQLite or test Postgres. |
| **Integration** | `tests/` | docker-compose stack (Postgres+TimescaleDB) + server + agent. |
| **End-to-end** | manual (homelab) | Real Tailscale, real LXC 280, real fleet. |
| **Doc lint** | `docs/` | `mkdocs build --strict` in CI. |

## Running tests

### Server unit tests

```bash
cd server
uv run pytest -q
```

### Agent unit tests

```bash
cd agent
uv run pytest -q
```

### Integration

```bash
docker compose -f docker-compose.dev.yml up -d
cd server && uv run alembic upgrade head && uv run uvicorn rp_server.main:app &
cd ../agent && uv run pytest tests/integration/ -v
```

### Coverage

```bash
cd server && uv run pytest --cov=rp_server --cov-report=html
cd ../agent && uv run pytest --cov=rp --cov-report=html
```

Reports under each component's `htmlcov/`.

## Conventions

- **Async tests:** use `pytest-asyncio` with `asyncio_mode = "auto"`. Don't
  decorate every test.
- **Fixtures:** prefer module-scope fixtures for slow setup (DB
  containers); function-scope for state-dependent ones.
- **Mocking Tailscale identity:** in unit tests, use the `tailscale_user`
  fixture (defined in `server/tests/conftest.py`) which injects the
  identity header dependency.
- **Hypertables:** TimescaleDB-specific tests live under
  `server/tests/timescale/` and skip if the extension is unavailable.
- **Local-approval enforcement:** agent tests use a `tmp_path` fixture for
  the flag directory; never touch the real `/etc/rp/`.

## Targeted suites

```bash
# Just the auth / identity tests
uv run pytest server/tests/test_auth.py

# Just the SSH key lifecycle
uv run pytest server/tests/test_keys.py agent/tests/test_ssh_keys.py

# Just the local-policy tests
uv run pytest agent/tests/test_local_policy.py
```

## CI

GitHub Actions runs:

1. Ruff lint + format check.
2. Shellcheck on `scripts/`.
3. Server pytest matrix (Python 3.12, 3.13).
4. Agent pytest matrix (Python 3.12, 3.13; Linux/macOS/Windows runners).
5. `mkdocs build --strict` against this docs tree.
6. PyInstaller build smoke test (Linux x64) post-F7.

CI fails fast on any of the above. PRs cannot merge without all green.

## See also

- [Dev setup](dev-setup.md)
- [Code style](code-style.md)
