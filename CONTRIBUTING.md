# Contributing to Remote-Pulse

Remote-Pulse is pre-alpha. We're still implementing F1-F4 of [ADR-0008](https://docs.monxas.casa/architecture/adr/ADR-0008-remote-pulse/). PRs are deferred until v0.2 surface stabilises (~late 2026), but issues, design feedback, and security disclosures are very welcome now.

## Quick dev setup

```sh
git clone https://github.com/monxas/remote-pulse.git
cd remote-pulse

# Start local Postgres+TimescaleDB
docker compose -f docker-compose.dev.yml up -d

# Server
cd server
uv sync --all-extras --dev
uv run alembic upgrade head
uv run uvicorn rp_server.main:app --reload

# Agent (in another shell)
cd ../agent
uv sync --all-extras --dev
uv run rp --help
```

## Project layout

See [README.md § Repo layout](./README.md#repo-layout).

- `agent/` and `server/` are independent uv projects with their own `pyproject.toml`.
- `scripts/` is POSIX sh (no bash-isms — must run on Alpine `ash` and Debian `dash`).
- `packaging/` holds OS-specific service units.

## Code style

- **Python**: ruff (lint + format), Pydantic v2 syntax, async-first where it makes sense, type hints everywhere.
- **Shell**: POSIX `sh`. shellcheck clean. No `[[`, no arrays, no `local`.
- **Tests**: pytest + pytest-asyncio. Each component has its own `tests/` dir.
- **Commit messages**: imperative ("Add X", not "Added X"). Reference task IDs from the ADR (e.g. `F2-1: tailscale daemon`).

## Security

Found a vulnerability? **Do not open a public issue.** Email security@monxas.casa or DM the maintainer on Tailscale (`ramon@monxas`). PGP key TBD in `SECURITY.md`.

## License

By contributing, you agree your contributions are licensed under Apache-2.0.
