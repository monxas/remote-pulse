# Install on Windows

Windows installs have three supported paths. The recommended one is
**winget**, because it sidesteps Windows Defender SmartScreen warnings
during the build-up of binary reputation.

## Path A — `winget` (recommended)

Open PowerShell (any user, no admin required):

```powershell
winget install Monxas.RemotePulse
```

After install, open an **elevated** PowerShell to enroll:

```powershell
rp install --token=<your-enrollment-token>
```

!!! tip
    The winget manifest is published in
    [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs) and is
    code-signed. No SmartScreen prompts.

## Path B — PyInstaller binary (fallback)

If your environment cannot use winget (corporate proxy, locked-down store):

```powershell
$env:RP_TOKEN = "<your-enrollment-token>"
iwr -useb https://rp.monxas.casa/install.ps1 | iex
```

This downloads a PyInstaller-bundled `rp.exe`, verifies the SHA256, installs
an NSSM service named `RemotePulse`, and enrolls.

!!! warning "Windows Defender SmartScreen"
    Until our EV code-signing reputation builds up (~6 months of downloads),
    PyInstaller binaries may trigger a SmartScreen prompt:

    > Windows protected your PC. Microsoft Defender SmartScreen prevented an
    > unrecognized app from starting.

    Click **More info → Run anyway** *only after verifying the SHA256
    against the value published on
    [`rp.monxas.casa/install.sha256`](https://rp.monxas.casa/install.sha256)*.

    Detailed guidance: [Windows Defender false positives](../troubleshooting/windows-defender.md).

## Path C — WSL (Windows power-users with Linux workflow)

If you already run WSL2 with Ubuntu/Debian, treat the WSL distro as a Linux
host and follow the [Linux install guide](install-unix.md). The Windows side
will not appear in the dashboard, only the WSL distro — useful for dev
machines, not for end-user laptops.

## Post-install verification

In PowerShell (elevated):

```powershell
rp status
rp version
Get-Service RemotePulse
```

In a regular PowerShell window:

```powershell
rp dash
```

## Uninstall

```powershell
rp uninstall --confirm
```

This stops and removes the `RemotePulse` Windows service, revokes the host's
SSH key on the server, and deletes `%PROGRAMDATA%\rp\`.

## Next steps

- [First connection walkthrough](first-connection.md)
- [Troubleshooting Windows Defender](../troubleshooting/windows-defender.md)
- [`rp` CLI reference](../guide/cli.md)
