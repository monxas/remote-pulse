# winget Manifest Templates

This directory contains manifest templates for publishing Remote-Pulse to the [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs) repository.

## Files

- `Monxas.RemotePulse.yaml` - Version manifest (metadata)
- `Monxas.RemotePulse.installer.yaml` - Installer manifest (download URL, SHA256)
- `Monxas.RemotePulse.locale.en-US.yaml` - Locale manifest (descriptions, tags)

## Template Placeholders

The following placeholders need to be replaced before submission:

- `{VERSION}` - Package version (e.g., `0.1.0`)
- `{INSTALLER_URL}` - GitHub release download URL (e.g., `https://github.com/monxas/remote-pulse/releases/download/v0.1.0/rp-windows-x64.exe`)
- `{SHA256}` - SHA256 hash of the installer binary
- `{RELEASE_DATE}` - Release date in ISO 8601 format (e.g., `2026-05-25`)

## Submission Process (Manual - F7-2)

This is a **stub for F7-2**. The actual winget submission will be automated in ticket F7-2.

### Prerequisites

1. Install [winget-create](https://github.com/microsoft/winget-create):
   ```powershell
   winget install Microsoft.WingetCreate
   ```

2. Fork [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs)

### Steps

1. After a new release is published, download `SHA256SUMS` from GitHub Releases:
   ```sh
   curl -fsSL https://github.com/monxas/remote-pulse/releases/download/v{VERSION}/SHA256SUMS
   ```

2. Extract the SHA256 for `rp-windows-x64.exe`:
   ```sh
   grep rp-windows-x64.exe SHA256SUMS | awk '{print $1}'
   ```

3. Replace placeholders in the manifests:
   ```sh
   VERSION="0.1.0"
   INSTALLER_URL="https://github.com/monxas/remote-pulse/releases/download/v${VERSION}/rp-windows-x64.exe"
   SHA256="<extracted-hash>"
   RELEASE_DATE=$(date -u +%Y-%m-%d)

   sed -i "s/{VERSION}/${VERSION}/g" *.yaml
   sed -i "s|{INSTALLER_URL}|${INSTALLER_URL}|g" *.installer.yaml
   sed -i "s/{SHA256}/${SHA256}/g" *.installer.yaml
   sed -i "s/{RELEASE_DATE}/${RELEASE_DATE}/g" *.installer.yaml
   ```

4. Validate manifests:
   ```powershell
   winget validate --manifest .
   ```

5. Create PR to microsoft/winget-pkgs:
   ```sh
   # Copy manifests to winget-pkgs repo
   cp *.yaml ~/winget-pkgs/manifests/m/Monxas/RemotePulse/{VERSION}/

   # Commit and push
   cd ~/winget-pkgs
   git checkout -b remote-pulse-{VERSION}
   git add manifests/m/Monxas/RemotePulse/
   git commit -m "Add Monxas.RemotePulse version {VERSION}"
   git push origin remote-pulse-{VERSION}

   # Open PR on GitHub
   ```

6. Wait for winget-pkgs maintainers to review and merge (typically 1-3 days)

## Automation (Future - F7-2)

F7-2 will automate this process with a GitHub Action that:
1. Triggers on new releases
2. Downloads SHA256SUMS
3. Substitutes placeholders
4. Validates manifests
5. Opens PR to microsoft/winget-pkgs automatically

## References

- [winget manifest schema](https://github.com/microsoft/winget-pkgs/tree/master/doc/manifest)
- [winget-create docs](https://github.com/microsoft/winget-create/blob/main/doc/README.md)
- [Contribution guide](https://github.com/microsoft/winget-pkgs/blob/master/CONTRIBUTING.md)
