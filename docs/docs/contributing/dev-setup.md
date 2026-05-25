# Development setup

Remote-Pulse is pre-alpha. PRs are deferred until v0.2 stabilises, but the
dev workflow below is what the core maintainer uses day-to-day; you can
run it to reproduce issues or experiment.

## Prerequisites

- **Python 3.12+**.
- **uv** (the package manager). Install with `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **Docker + Docker Compose** for the local Postgres+TimescaleDB stack.
- **Tailscale** (optional, only needed for end-to-end testing the data plane).
- A reasonably modern terminal (Textual needs Unicode + truecolor support).

## Clone

```bash
git clone https://github.com/monxas/remote-pulse.git
cd remote-pulse
```

## Start Postgres + TimescaleDB

```bash
docker compose -f docker-compose.dev.yml up -d
```

This spins up:

- `timescaledb:2026-pg16` listening on `localhost:5432`.
- Default credentials are in `docker-compose.dev.yml` and `server/SETUP.md`.

## Server setup

```bash
cd server
uv sync --all-extras --dev
uv run alembic upgrade head
uv run uvicorn rp_server.main:app --reload
```

The API is now at `http://127.0.0.1:8080`. OpenAPI docs at
`http://127.0.0.1:8080/docs`.

## Agent setup (separate shell)

```bash
cd agent
uv sync --all-extras --dev
uv run rp --help
```

For local development you can install the agent in editable mode:

```bash
uv pip install -e .
```

…and then `rp install --server=http://127.0.0.1:8080 --token=<dev-token>`
points at the local server.

## Generating a dev enrollment token

```bash
cd server
uv run python -m rp_server.admin enroll --group=default --ttl=24h --max-uses=1
```

The CLI prints the JWT. Use it in the agent's `rp install --token=...`.

## Running the TUI against local server

```bash
cd agent
uv run rp dash --server=http://127.0.0.1:8080
```

## Testing

```bash
# Server
cd server && uv run pytest

# Agent
cd ../agent && uv run pytest

# Both with coverage
uv run pytest --cov=rp --cov=rp_server --cov-report=term-missing
```

See [Testing](testing.md) for the full test taxonomy.

## Docs (this site)

```bash
cd docs
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
mkdocs serve
```

Site available at `http://127.0.0.1:8000`.

## Project layout

```text
monxas-remote-pulse/
├── agent/         # rp Python CLI + daemon (installable as `pipx install remote-pulse`)
├── server/        # FastAPI + Postgres + Alembic (deployed via Ansible role privately)
├── scripts/       # install.sh, install.ps1, uninstall.sh (POSIX sh + PowerShell)
├── packaging/     # systemd unit / launchd plist / NSSM service stubs
├── docs/          # MkDocs site (rp.monxas.casa/docs after F7)
└── tests/         # integration tests (per-component tests live alongside code)
```

`agent/` and `server/` are independent uv projects with their own
`pyproject.toml` and `uv.lock`.

`scripts/` is POSIX `sh` (no bash-isms): the install scripts must run on
Alpine `ash` and Debian `dash` without modification.

## Pre-commit

```bash
pip install pre-commit
pre-commit install
```

Hooks: ruff (lint + format), shellcheck on `scripts/`, mkdocs strict build
on docs changes.

## See also

- [`CONTRIBUTING.md`](https://github.com/monxas/remote-pulse/blob/main/CONTRIBUTING.md) — top-level contributor guide
- [Testing](testing.md)
- [Code style](code-style.md)
