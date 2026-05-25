# GitHub Actions Workflows

This directory contains CI/CD workflows for Remote-Pulse.

## Workflows

### ci.yml
Runs on every push to `main` and on pull requests. Performs:
- Agent linting and testing (Python 3.12 on Linux/macOS/Windows)
- Server linting and testing (with PostgreSQL 16)
- Secrets scanning (trufflehog)

### release.yml
Triggers on Git tags matching `v*` (e.g., `v0.1.0`). Performs:
- Multi-OS binary builds (Linux x64/arm64, macOS x64/arm64, Windows x64)
- SHA256 checksum generation
- GitHub Release creation with all artifacts
- Automatic changelog from Git commits
- Prerelease detection (tags containing `alpha`, `beta`, or `rc`)

## Local Testing with act

[act](https://github.com/nektos/act) allows you to test GitHub Actions locally.

### Installation

```sh
# macOS
brew install act

# Linux
curl -s https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash

# Windows (via Scoop)
scoop install act
```

### Usage

```sh
# List available workflows
act -l

# Test CI workflow (simulates pull_request event)
act pull_request

# Test release workflow (simulates tag push)
act push --eventpath <(echo '{"ref": "refs/tags/v0.1.0"}')

# Run specific job
act -j build-linux-x64

# Dry-run (show what would run without executing)
act -n
```

### Limitations

- **Large runners**: GitHub provides larger runners for public repos with more CPU/memory. `act` uses Docker containers on your local machine, which may have different resource constraints.
- **QEMU emulation**: The `build-linux-arm64` job uses QEMU to emulate arm64 on x64 runners. This works in GitHub Actions but may be slow or fail locally depending on your Docker/QEMU setup.
- **Secrets**: `act` requires secrets to be configured locally via `.secrets` file or `-s` flags. The workflows don't use secrets (public repo), but future enhancements (code signing) will.
- **Artifacts**: `act` simulates artifact upload/download, but the behavior differs slightly from GitHub Actions.

### Recommended Local Testing

Instead of testing the full release workflow with `act`, prefer:

1. **Build locally** with the Makefile:
   ```sh
   cd agent
   make build-binary
   ```

2. **Run CI checks locally**:
   ```sh
   cd agent
   make lint
   make test
   ```

3. **Test on actual GitHub Actions** by pushing to a branch and opening a PR (CI runs automatically).

4. **Test releases** by pushing a lightweight tag to a test branch:
   ```sh
   git tag v0.0.0-test
   git push origin v0.0.0-test
   # Check Actions tab on GitHub
   # Delete test release and tag after verification
   ```

## Workflow Maintenance

- **Update runner versions**: When new Ubuntu/macOS/Windows runner images are available, update `runs-on` values in both workflows.
- **Pin action versions**: We use `@v4`, `@v3`, etc. for stability. Update major versions only after reviewing changelogs.
- **Cache uv**: The `enable-cache: true` in `setup-uv` action speeds up dependency installation. Monitor cache hit rates in Actions logs.

## Troubleshooting

### Build failures on Windows

- **PyInstaller warnings**: Windows builds may show warnings about missing DLLs (e.g., `ole32`, `shell32`). These are normal for cross-platform builds and don't affect the final binary.
- **Antivirus interference**: Windows Defender may quarantine PyInstaller binaries. The workflow runs on GitHub's runners with Defender exclusions configured.

### Arm64 build timeouts

- **QEMU emulation is slow**: The `build-linux-arm64` job uses QEMU to emulate arm64 on x64 runners. This can take 10-15 minutes. If it times out (15min limit), consider:
  - Using GitHub's native arm64 runners (if available in the future)
  - Cross-compiling instead of emulating (requires more setup)
  - Deferring arm64 support to post-v1.0

### Release artifacts missing

- **Check dependencies**: The `sha256sums` job depends on all build jobs. If any build fails, the entire release is blocked.
- **Artifact naming**: The `actions/upload-artifact@v4` and `actions/download-artifact@v4` must use matching names. We use `rp-{target}` for consistency.

## References

- [GitHub Actions documentation](https://docs.github.com/en/actions)
- [act documentation](https://github.com/nektos/act)
- [astral-sh/setup-uv action](https://github.com/astral-sh/setup-uv)
- [softprops/action-gh-release](https://github.com/softprops/action-gh-release)
