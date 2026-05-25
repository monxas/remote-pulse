# Code style

Rules of thumb. The CI enforces them via ruff, shellcheck and mkdocs
strict-build.

## Python

- **Formatter:** `ruff format` (Black-compatible style).
- **Linter:** `ruff check` (replaces flake8, isort, pyupgrade, etc.).
- **Type hints:** everywhere. `from __future__ import annotations` is OK.
  `mypy` runs in strict mode on the server and lenient on the agent.
- **Pydantic v2.** Use `model_config`, not the v1 `class Config:` syntax.
- **Async-first** where it makes sense; explicit sync helpers when not.
- **Imports:** absolute (`from rp.commands.local import ...`), never relative.
- **Docstrings:** Google-style. Required on public modules, classes and
  functions; optional on internal helpers.

### Naming

- Modules: `snake_case`.
- Classes: `PascalCase`.
- Functions / variables: `snake_case`.
- Constants: `UPPER_SNAKE`.
- CLI commands: `kebab-case` (e.g. `rp keys configure-sshd`).

## Shell

- **POSIX `sh`.** Must run on Alpine `ash` and Debian `dash`.
- No `[[`, no arrays, no `local`. shellcheck must be clean (CI fails
  otherwise).
- Always `set -eu`. Use `set -o pipefail` only if the script targets bash
  (none of ours do).
- Quote every variable expansion. Use `printf` instead of `echo -e`.

## PowerShell

- Target PowerShell 5.1+ (ships with Windows 10+).
- Prefer `Invoke-WebRequest -UseBasicParsing` over `Invoke-RestMethod` for
  binary downloads.
- Use approved verb prefixes (`Get-`, `Set-`, `Install-`, …) for functions.

## Commit messages

Imperative mood; reference the ADR-0008 task ID where relevant.

Good:

```text
F2-1: implement tailscaled daemon bootstrap
F4-3: add rp keys rotate command
docs: clarify local-approval TTL semantics
```

Bad:

```text
Updated some files
fix
WIP
```

## File and module boundaries

- One CLI subcommand per file in `agent/src/rp/commands/`.
- Routers in `server/src/rp_server/routers/` mirror REST namespaces 1:1.
- Pydantic schemas in `server/src/rp_server/schemas.py`. Don't sprinkle
  schemas into router files.
- Database models in `server/src/rp_server/models.py`. Alembic migrations
  in `server/alembic/versions/`.
- Tests mirror the source tree under each component's `tests/` directory.

## Logging

- **Agent:** `structlog` configured in `agent/src/rp/cli.py`. Use
  `structlog.get_logger().info("event_name", key=value)`. Never use
  f-string interpolation inside log calls.
- **Server:** `structlog` integrated with Uvicorn's logging. Same rules.

## Error handling

- Catch only what you can handle. Let unexpected exceptions propagate and
  show up in the audit log.
- For agent-side rejections (signature, local policy, version skew),
  always log `event="command_rejected"` with `reason=...`.

## Documentation

- Markdown follows GitHub-flavoured Markdown plus the
  [pymdownx.tabbed / details / superfences extensions](https://facelessuser.github.io/pymdown-extensions/).
- Headings: H1 = page title, H2 = section, H3 = subsection. Avoid H4+.
- Internal links are relative (`[CLI reference](../guide/cli.md)`), never
  absolute URLs of the same site.
- Mermaid diagrams where they add clarity. Don't draw ASCII art when a
  diagram would do.

## See also

- [Dev setup](dev-setup.md)
- [Testing](testing.md)
