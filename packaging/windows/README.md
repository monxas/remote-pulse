# Windows packaging — F7 TODO

This directory holds **stubs only** for F1-5. Real Windows packaging is scoped
to **F7** of ADR-0008 (`docs/architecture/adr/ADR-0008-remote-pulse.md`,
phase "F7: One-liner public + Windows installer honesto + Docs site").

## What F7 will deliver

1. **PyInstaller single-file exe** — `rp.exe` bundling the agent + uv-free
   Python runtime. Built on a Windows CI runner (no cross-compile shortcuts).
2. **winget package** — manifest under `monxas/remote-pulse` so users can run
   `winget install monxas.remote-pulse` from PowerShell admin.
3. **NSSM service wrapper** — wraps `rp.exe heartbeat --daemon` as a real
   Windows service with auto-start, stdout/stderr to
   `C:\ProgramData\RemotePulse\logs\`.
4. **One-liner installer** — `iwr ... | iex` style PowerShell bootstrap
   equivalent to `scripts/install.sh` on Unix, see ADR Apéndice A.

## Current state (F1-5)

- `install-nssm.ps1` / `uninstall-nssm.ps1` — print the F7 plan and exit 0.
  This lets `scripts/install.sh` (when ported to PS) detect the platform and
  fail loudly with a useful message, instead of silently doing nothing.

## Why not done now

F1 explicitly targets Linux + macOS only. ADR-0008 §F7 calls Windows packaging
"honesto" because a real installer requires CI infra (Windows runner), winget
manifest submission flow, and PyInstaller plumbing — non-trivial work.

See also: ADR-0008 line ~405 "Windows packaging (rediseñado)".
