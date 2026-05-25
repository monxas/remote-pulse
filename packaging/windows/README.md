# Windows packaging — F7 / ADR-0008

Real Windows install path landed in **F7** of ADR-0008. This directory ships
the **NSSM service wrapper** that turns `rp.exe heartbeat --daemon` into a
proper Windows service, plus matching uninstaller.

The user-facing bootstrap lives at `../../scripts/install.ps1`.

## Layout

```
packaging/windows/
├── install-nssm.ps1      # Install-RemotePulseService function (dot-sourced)
├── uninstall-nssm.ps1    # Standalone uninstaller
└── README.md             # This file
```

## What `install-nssm.ps1` does

Dot-sourced by `scripts/install.ps1`. Exposes the function
`Install-RemotePulseService -InstallDir <path> -DataDir <path> [-ServiceName <name>]`.

1. **Fetch NSSM 2.24** (cached at `<InstallDir>\nssm.exe`) — SHA256 pinned
   (`52897F28…`) against `nssm.cc/release/nssm-2.24.zip`.
2. **Create or update** Windows service `RemotePulseAgent`:
   - `Application = C:\Program Files\RemotePulse\rp.exe`
   - `AppParameters = heartbeat --daemon`
   - `AppDirectory = C:\Program Files\RemotePulse`
   - `Start = SERVICE_AUTO_START`
   - `ObjectName = LocalSystem`
   - `AppEnvironmentExtra = RP_CONFIG=...config.toml, RP_DATA_DIR=...`
3. **Recovery:** `AppExit Default Restart`, `AppRestartDelay 5000`,
   `AppThrottle 10000` — service restarts on crash with 5s back-off.
4. **Logging:** rotating stdout/stderr at `C:\ProgramData\RemotePulse\logs\`
   with `AppRotateOnline 1`, `AppRotateBytes 10MB`, `AppRotateSeconds 86400`.
5. **Idempotent:** stops service if running, then re-applies all config.
6. **Verify:** waits 2 s, checks `Get-Service RemotePulseAgent` is `Running`.

## Uninstall

```powershell
# preserve C:\ProgramData\RemotePulse (config, logs, sqlite queue)
.\uninstall-nssm.ps1

# full purge
.\uninstall-nssm.ps1 -PurgeData

# dry-run
.\uninstall-nssm.ps1 -WhatIf
```

Tailscale is intentionally **not** uninstalled (it is often shared with other
tools); a manual cleanup hint is printed.

---

## Windows Defender + SmartScreen troubleshooting

PyInstaller-built `rp.exe` is currently **unsigned**. Until F7's "EV code
signing" line item lands (Sectigo/DigiCert ≈ $300/yr, see ADR-0008 §F7
Path B), users will hit:

- **Windows SmartScreen** banner on first run: *"Windows protected your PC"*.
- **Microsoft Defender Antivirus** may flag the EXE as `Trojan:Win32/Wacatac.B!ml`
  (a generic ML heuristic that hits ~all PyInstaller binaries).
- **Defender SmartScreen** in Edge may block the download from GitHub Releases
  on freshly-published versions until reputation accrues.

### Why this happens

1. PyInstaller bootstraps Python by extracting compressed bytecode to TEMP and
   `LoadLibrary`-ing it. That pattern is shared with malware → ML heuristics
   trigger.
2. The binary has no Authenticode signature, so SmartScreen can't attribute
   reputation to a publisher.
3. New file hashes always start with **zero reputation** — even signed
   builds need ~thousands of downloads before SmartScreen relaxes.

### Workaround 1 (recommended) — use the `winget` path

```powershell
winget install Monxas.RemotePulse --silent
```

The `microsoft/winget-pkgs` repo manifests are reviewed and the SmartScreen
verdict is delegated to winget itself. **No Defender popup**, no exception
needed. This is why `install.ps1 -InstallMode auto` prefers `winget`.

### Workaround 2 — Add a Defender exclusion (only if you own this device)

```powershell
# Run from elevated PowerShell:
Add-MpPreference -ExclusionPath 'C:\Program Files\RemotePulse'
Add-MpPreference -ExclusionPath 'C:\ProgramData\RemotePulse'
Add-MpPreference -ExclusionProcess 'rp.exe'
```

Inspect existing exclusions:

```powershell
Get-MpPreference | Select-Object ExclusionPath, ExclusionProcess
```

Remove later:

```powershell
Remove-MpPreference -ExclusionPath 'C:\Program Files\RemotePulse'
Remove-MpPreference -ExclusionProcess 'rp.exe'
```

> Note: exclusions are tenant-policy-controlled on managed devices (Intune /
> AD GPO). Don't add exclusions on company laptops without IT approval.

### Workaround 3 — SmartScreen "Run anyway"

1. When the *"Windows protected your PC"* dialog appears, click **More info**.
2. Click the **Run anyway** button that appears.
3. The decision is cached per-hash; subsequent runs of the same binary skip
   the warning.

### Report a false positive to Microsoft

If Defender quarantines `rp.exe`:

1. Open the **Microsoft Security Intelligence** submission portal:
   <https://www.microsoft.com/wdsi/filesubmission>
2. Choose **Submit a file for analysis** → *Detected as malware (false positive)*.
3. Upload the quarantined `rp.exe` (recover from
   `C:\ProgramData\Microsoft\Windows Defender\Quarantine\` if needed,
   or re-download from GitHub Releases).
4. In the description, link the GitHub Release URL and mention
   "PyInstaller-built open-source agent, unsigned during build-up phase".
5. Microsoft typically resolves within 24–72 hours. After resolution, the
   ML signature is updated and future versions stop tripping the heuristic.

### Roadmap: EV code signing in v0.2.0

ADR-0008 §F7 commits to either:

- **Path A (preferred):** publish to `microsoft/winget-pkgs` and let
  Microsoft's manifest review build reputation (free, ~1–2 weeks per release).
- **Path B (fallback):** EV (Extended Validation) Authenticode certificate
  from Sectigo / DigiCert (≈ $300/year). EV certs receive **immediate**
  SmartScreen reputation, eliminating "Run anyway" prompts.

Decision deferred to **v0.2.0**: monitor false-positive rate during v0.1.x
build-up. If `winget`-path covers >80% of installs (target: family +
non-technical users), skip Path B and save the budget.

Tracking issue: `monxas/remote-pulse#F7-windows-codesign`.

---

## Air-gapped installs

`scripts/install.ps1 -Offline -LocalBinary C:\path\to\rp.exe -Token <JWT>`
skips all network downloads (Tailscale, NSSM, agent) except the
enrollment POST (`$Server/v1/enroll`, which **must** be reachable; pre-stage
a JWT on a USB key).

Pre-stage requirements on the target machine:

- `nssm.exe` already at `C:\Program Files\RemotePulse\nssm.exe`.
- `tailscale.exe` already installed (Tailscale MSI ran previously).
- `rp.exe` reachable via `-LocalBinary`.

See `scripts/README.md` § *Air-gapped install* for the full procedure.

---

## References

- ADR-0008 §3 — Python/PyInstaller dual distribution
- ADR-0008 §10 — Bootstrap one-liner
- ADR-0008 §F7 — Windows installer honesto + winget package
- NSSM: <https://nssm.cc/usage>
- winget manifest spec: <https://learn.microsoft.com/windows/package-manager/package/manifest>
