# Windows Defender false positives

Windows Defender SmartScreen and the on-access scanner sometimes flag
freshly published `rp.exe` PyInstaller binaries. This is **a generic
PyInstaller signal**, not a true detection — until the binary builds up
enough download reputation, SmartScreen warns by default for unknown
publishers.

This page explains why it happens, how to verify, and the recommended
workarounds.

## Why it happens

| Cause | Detail |
|-------|--------|
| **PyInstaller boot loader** | Bundles a small ELF/PE loader that unpacks the Python runtime. Many malware families also use PyInstaller, so static heuristics flag it. |
| **No EV code signing yet** | Extended Validation (EV) code-signing certs cost ~$300/year. We have it budgeted for v1.0.0 GA; in the meantime, downloads accumulate reputation. |
| **Fresh release** | Each new GitHub Release is a "new" file from SmartScreen's perspective until ≥1,000-ish downloads. |
| **Aggressive ASR rules** | Some corporate Defender policies block any unsigned process from `%TEMP%`. |

## Recommended path: use `winget`

The `winget install Monxas.RemotePulse` path uses a **signed installer**
published through the Microsoft Store ingestion pipeline. It does **not**
trigger SmartScreen.

```powershell
winget install Monxas.RemotePulse
```

If your environment allows winget, this is the path of least friction.
See the [Windows install guide](../quickstart/install-windows.md).

## If you must use the PyInstaller binary

### Verify the SHA256

The published anchor lives at `https://rp.monxas.casa/install.sha256`.
Cross-check before approving the binary:

```powershell
$expected = (Invoke-WebRequest -UseBasicParsing https://rp.monxas.casa/install.sha256).Content.Trim()
Get-FileHash C:\Users\$env:USERNAME\Downloads\rp.exe -Algorithm SHA256
```

The output of `Get-FileHash` should match `$expected`.

### Approve via SmartScreen

When the prompt appears:

> Windows protected your PC. Microsoft Defender SmartScreen prevented an
> unrecognized app from starting.

1. Click **More info**.
2. The publisher line should read `Unknown publisher`. That's expected.
3. Click **Run anyway** *only if you have verified the SHA256*.

### Add a Defender exclusion (advanced)

If your Defender configuration scans every execution and lags the install,
add `rp.exe` to the path exclusions:

```powershell
# Run as Administrator
Add-MpPreference -ExclusionPath "C:\Program Files\RemotePulse"
Add-MpPreference -ExclusionProcess "rp.exe"
```

!!! warning
    Path exclusions reduce protection. Use only on workstations where the
    operator understands the trade-off.

### Report as false positive to Microsoft

You can help future users by reporting the binary as clean. From the
[Microsoft Security Intelligence portal](https://www.microsoft.com/en-us/wdsi/filesubmission):

1. Choose **"Software developer"**.
2. Submit `rp.exe` (or the installer `rp-setup.exe`).
3. Mark **"This file should not be detected"**.
4. Paste the SHA256 from `rp.monxas.casa/install.sha256` in the comments.

Microsoft typically responds within a few business days; once the binary
is whitelisted, future SmartScreen prompts disappear.

## What we are doing about it

| Action | Status |
|--------|--------|
| Publish to winget | <span class="rp-badge planned">F7</span> |
| EV code signing for PyInstaller binaries | Budgeted, ~v0.9 |
| Cosign signatures on GitHub Releases | Planned F8 |
| Microsoft Defender ATP partner submission | Post-GA |

## See also

- [Install on Windows](../quickstart/install-windows.md)
- [Common errors](common-errors.md)
