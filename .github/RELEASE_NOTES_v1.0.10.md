# Remote-Pulse v1.0.10 — short-code enrollment

Operator action required: `alembic upgrade head` (011, adds `short_code` column to `enrollments`).

## Highlights

- **Magic-links are now 6-character codes.** Instead of pasting a 250-character `?token=eyJ...` URL into a terminal (impossible to type, leaks via browser history + access logs + referer headers), the dashboard now emits a memorable code like `K7M-X3F`. The install command is generic:
  ```sh
  curl https://rp.monxas.casa/install | sh -s -- --code=K7M-X3F
  ```
- **Default TTL is 5 minutes** (was 24 hours). Operator picks 5min / 30min / 2h / 24h from a select. Configurable up to 24h max.
- **Backward compatible.** Existing agents installed via the long JWT URL keep working. The new `code` and the legacy `token` are mutually exclusive on `POST /v1/enroll` (422 on both/neither).

## Why

The old flow was awful in 3 ways:

1. **UX**: a 250-char string can't be typed or read over the phone.
2. **Security**: the JWT in the URL was logged by browser history, Caddy `access.log`, and any HTTP `Referer` header sent by 3rd-party stylesheets / fonts loaded on the install page.
3. **Trust**: the recipient had to trust an opaque blob. A 6-char code is auditable at a glance.

## Design

- **Alphabet**: `ABCDEFGHJKLMNPQRTUVWXY2346789` — 29 chars, no `0`/`O`/`o`, no `1`/`l`/`I`, no `S`/`5`, no `Z`. Avoids OCR/handwriting confusion.
- **Entropy**: 6 chars × log₂(29) ≈ 29.1 bits ≈ 590M possible codes. With 5-min TTL and a single use, collision/guess risk is negligible.
- **Display**: `XXX-XXX` with a dash for readability. Server normalizes to uppercase, no dash. Input is case-insensitive and dash-tolerant.
- **Server table**: new `short_code TEXT NULL` column on `enrollments` with a **partial unique index** on `(short_code) WHERE short_code IS NOT NULL AND used_count < max_uses`. The `used_count < max_uses` predicate ensures consumed codes free their slot for reuse. The `expires_at` predicate was deliberately omitted — Postgres rejects `now()` in `WHERE` of an index (non-IMMUTABLE), and at 5-min TTL the expired-but-unconsumed window is negligible.
- **Retry on collision**: code generation retries up to 5 times if the unique constraint fires.

## Changes

### Server

- `feat(server-enroll)` `auth.py`: `SHORT_CODE_ALPHABET`, `generate_short_code()`, `format_short_code()`, `normalize_short_code()` (uppercase + strip dash + tolerant of lowercase input).
- `feat(server-enroll)` `models.py`: `Enrollment.short_code: Mapped[str | None]` column.
- `feat(server-enroll)` `dash_enroll.py`:
  - `LinkCreateRequest` schema accepts `ttl_minutes` OR `ttl_hours` (both capped at 24h equivalent).
  - `create_enroll_link()` generates code + jti + JWT, persists both, retries up to 5× on collision.
  - Response includes `code`, `install_url` (ready to paste), plus legacy `url`/`token` for backward compat.
  - `list_enroll_links()` echoes `code` + `install_url_short` per row.
- `feat(server-enroll)` `enroll.py`: `POST /v1/enroll` branches on `code` (short-code lookup, 403 on miss) vs `token` (legacy JWT path). Both end up in the same `used_count` / `max_uses` / `expires_at` lifecycle.
- `feat(server-schemas)` `EnrollRequest` model validator enforces XOR (token XOR code, exactly one).
- `chore(server-alembic)` `011_enrollment_short_code.py` — adds column + partial unique index.
- `test(server)` 17 new tests in `test_short_code_enrollment.py` covering generation helpers, default 5-min TTL, 24h cap on both `ttl_minutes` and `ttl_hours`, happy path, expired / exhausted / unknown codes, XOR enforcement (422 on both/neither), lowercase + dash tolerance, retry-on-collision smoke, **legacy JWT path still works**.

### Install scripts

- `feat(install)` `scripts/install.sh` accepts `--code=XXX-XXX` (env `RP_CODE`) as an alternative to `--token=`. Mutually exclusive. POST payload uses whichever was provided. 403 differentiated as "Invalid or expired enrollment code".
- `feat(install)` `scripts/install.ps1` adds `-Code` parameter with the same semantics. WSL fallback forwards the right flag.

### Dashboard SPA

- `feat(web-enroll)` `/enroll` page redesigned. Result card now shows:
  - **Hero**: `K7M-X3F` in monospace at 5xl, click-to-copy, accent background.
  - **Install command**: one-liner string with copy button.
  - **Countdown**: live timer "Expires in 4m 23s" updates every second.
  - **Advanced (collapsible)**: legacy JWT URL for tooling that needs the old format.
- `feat(web-enroll)` TTL select with 4 presets: 5min (recommended) / 30min / 2h / 24h.
- `feat(web-enroll)` `Code` column in active links table (was the giant URL).

### Agent

- `chore` `__version__` + `pyproject.toml` → `1.0.10` (lockstep with server).

## Upgrade

```sh
cd /opt/rp/source
git pull
cd server
set -a; source /etc/rp/server.env; set +a
sudo -u rp env POSTGRES_URL="$POSTGRES_URL" JWT_SECRET="$JWT_SECRET" \
    /opt/rp/source/server/.venv/bin/alembic upgrade head
cd ..
scripts/build_dashboard.sh
systemctl restart rp-server
```

## Verifying

```sh
curl -sS https://rp.monxas.casa/health
# {"status":"healthy","version":"1.0.10"}

sudo -u postgres psql -d remote_pulse -c "\d enrollments" | grep short_code
# short_code | text
```

Try the new flow:
1. Open the dashboard `/enroll`.
2. Pick group + 5min TTL + submit.
3. You get a code like `K7M-X3F`.
4. On the target machine:
   ```sh
   curl https://rp.monxas.casa/install | sh -s -- --code=K7M-X3F
   ```

## Backward compatibility

- Existing magic-link URLs (`?token=eyJ...`) keep working — the `?token` query param is parsed by `install-bootstrap.sh` and forwarded to install.sh.
- `POST /v1/enroll` still accepts the JWT in the request body.
- `LinkCreateResponse` still includes `url` + `token` + `install_url_windows` (legacy) alongside the new `code` + `install_url`.

Agents installed pre-1.0.10 do not need to re-enroll.

## Known follow-ups (v1.0.11+)

- Bulk operations on Settings Users tab (multi-select role / group toggle) — captured as follow-up.
- Operator-with-host.delete-grant client-side gate (currently admin-only in UI, backend remains source of truth).
- Cancel 5 stale `release.yml` runs once the GH Actions incident closes.
