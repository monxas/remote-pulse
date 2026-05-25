# winget Manifests — Monxas.RemotePulse

Manifest templates + rendering pipeline for publishing Remote-Pulse to the
[microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs) community
repository. Implements ADR-0008 D2 (winget as primary Windows packaging).

## Files

| File | Purpose |
| ---- | ------- |
| `Monxas.RemotePulse.yaml` | Version manifest (top-level metadata) |
| `Monxas.RemotePulse.installer.yaml` | Installer manifest (URL + SHA256, portable EXE) |
| `Monxas.RemotePulse.locale.en-US.yaml` | Default locale (descriptions, tags) |
| `render-manifests.sh` | POSIX sh script that substitutes placeholders |

Schema: **winget-pkgs ManifestVersion 1.6.0** (latest stable as of 2026-05).

## Placeholders

| Placeholder | Replaced with |
| ----------- | ------------- |
| `{VERSION}` | Semver, e.g. `0.1.0` |
| `{INSTALLER_URL}` | `https://github.com/monxas/remote-pulse/releases/download/v{VERSION}/rp-windows-x64.exe` |
| `{SHA256}` | Lowercase hex SHA256 of the EXE asset |

## Rendering manifests

```sh
cd agent/packaging/winget
./render-manifests.sh 0.1.0 \
    https://github.com/monxas/remote-pulse/releases/download/v0.1.0/rp-windows-x64.exe \
    a3f4e5b6c7d8e9f0112233445566778899aabbccddeeff00112233445566778899 \
    /tmp/rp-manifests
```

The release workflow (`.github/workflows/release.yml`, job `submit-winget`)
invokes this script automatically on every `v*` tag.

## Versioning policy

| Track | Installer | Signing | Notes |
| ----- | --------- | ------- | ----- |
| `v0.X.Y` (pre-1.0) | Portable EXE (PyInstaller single-file) | None | SmartScreen warnings expected; users must accept |
| `v1.0.0+` | MSI installer (WiX) | EV code-signing certificate | Post-F8 hardening; eliminates SmartScreen warnings |

Portable type lets winget manage the EXE under
`%LOCALAPPDATA%\Microsoft\WinGet\Packages\` and adds `rp` to PATH automatically;
no admin elevation required for user-scope installs.

## Manual submission process (first release, pre-automation)

The first release should be submitted manually for human review by the
winget-pkgs maintainers. Subsequent releases will use the automated
`submit-winget` job.

### Prerequisites

1. Fork [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs) to
   your GitHub account (one-time).
2. Install [winget-create](https://github.com/microsoft/winget-create) on a
   Windows host (Windows 10 2004+ or Windows 11):
   ```powershell
   winget install Microsoft.WingetCreate
   ```

### Steps

1. **Render the manifests** for the release tag:
   ```sh
   VERSION=0.1.0
   URL="https://github.com/monxas/remote-pulse/releases/download/v${VERSION}/rp-windows-x64.exe"
   SHA=$(curl -fsSL "https://github.com/monxas/remote-pulse/releases/download/v${VERSION}/SHA256SUMS" \
         | grep rp-windows-x64.exe | awk '{print $1}')
   ./render-manifests.sh "$VERSION" "$URL" "$SHA" /tmp/rp-manifests
   ```

2. **Validate locally** with winget-create on a Windows host:
   ```powershell
   wingetcreate.exe show Monxas.RemotePulse
   winget validate --manifest C:\path\to\rp-manifests\
   ```

3. **(Optional) Sandbox install** on Windows 11 with Hyper-V enabled:
   ```powershell
   # Inside WinGet Sandbox (sandbox.exe from winget-pkgs/Tools/SandboxTest.ps1)
   winget install --manifest C:\path\to\rp-manifests\
   rp version  # Should print 0.1.0
   ```

4. **Copy into winget-pkgs fork** at the strict required path:
   ```sh
   git clone git@github.com:<your-user>/winget-pkgs.git
   cd winget-pkgs
   git checkout -b monxas-remote-pulse-v${VERSION}
   mkdir -p manifests/m/Monxas/RemotePulse/${VERSION}
   cp /tmp/rp-manifests/*.yaml manifests/m/Monxas/RemotePulse/${VERSION}/
   git add manifests/m/Monxas/RemotePulse/
   git commit -m "New version: Monxas.RemotePulse version ${VERSION}"
   git push -u origin monxas-remote-pulse-v${VERSION}
   ```

5. **Open the PR** to `microsoft/winget-pkgs:master`. CI in winget-pkgs runs
   schema validation + sandbox install + AV scan automatically. Expected
   review timeline: **1–3 business days**.

6. **After merge**, `winget install Monxas.RemotePulse` or `winget install rp`
   (via the `Moniker`) will work for all Windows 10 2004+ users.

## Automation (post-v0.1)

The `submit-winget` job in `.github/workflows/release.yml` calls
[`vedantmgoyal2009/winget-releaser`](https://github.com/vedantmgoyal2009/winget-releaser),
which:

1. Computes SHA256 of the published Windows EXE asset.
2. Renders manifests via this directory's templates.
3. Opens a PR against `microsoft/winget-pkgs` from a bot-owned fork.

Requires repo secret `WINGET_TOKEN` — a fine-grained PAT scoped to the
maintainer's `winget-pkgs` fork (`contents:write`, `pull-requests:write`).
For v0.1.0 the step is `continue-on-error: true` so manual submission is the
authoritative path; automation flips authoritative starting v0.2.0.

## References

- [winget Manifest spec v1.6](https://github.com/microsoft/winget-cli/blob/master/doc/ManifestSpecv1.6.md)
- [winget-pkgs contribution guide](https://github.com/microsoft/winget-pkgs/blob/master/CONTRIBUTING.md)
- [winget-create docs](https://github.com/microsoft/winget-create/blob/main/doc/README.md)
- ADR-0008 §3 D2 — Windows packaging decision rationale
