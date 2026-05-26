# Runbook — Serve the install bootstrap + tarball through Caddy

**Context:** The canonical Remote-Pulse install pattern is

```sh
curl -fsSL https://rp.monxas.casa/install | sh -s -- --token=<JWT>
```

After the F1/Agent C fix (v1.0.1), `scripts/install.sh` depends on sibling
files under `packaging/{linux,macos}/`. A single-file curl pipe cannot carry
that multi-file payload. Solution: serve a thin wrapper
(`install-bootstrap.sh`) at `/install` that downloads and verifies a
release tarball (`rp-install-<version>.tar.gz`) then exec's the bundled
installer.

Caddy on LXC 270/271 already serves the install assets from
`/var/lib/caddy/rp-install/`. We just need to (a) widen the
`@install_files` matcher to cover the new tarball + sha256 filenames and
(b) place the new artefacts in that directory.

## 1. Caddyfile change

### Before

```caddyfile
@install_files path /install /install.sh /install.ps1 /install.sha256 /enroll-family.sh /reinstall-family.sh /persist-family.sh /tag-family.sh
handle @install_files {
    root * /var/lib/caddy/rp-install
    file_server
}
```

### After

```caddyfile
# ADR-0008 install bootstrap: /install must serve install-bootstrap.sh (the
# single-file curl-pipe wrapper). The wrapper downloads
# /install/rp-install-<version>.tar.gz, verifies the SHA256 against the
# sibling .sha256 file, and exec's the bundled scripts/install.sh.
@install_files path /install /install.sh /install.ps1 /install.sha256 \
    /install/rp-install-*.tar.gz /install/rp-install-*.tar.gz.sha256 \
    /install-bootstrap.sh \
    /enroll-family.sh /reinstall-family.sh /persist-family.sh /tag-family.sh
handle @install_files {
    root * /var/lib/caddy/rp-install
    file_server
}

# /install (no extension) returns install-bootstrap.sh — overrides any
# previous mapping that pointed it at install.sh.
@install_root path /install
handle @install_root {
    root * /var/lib/caddy/rp-install
    rewrite * /install-bootstrap.sh
    file_server
}
```

Notes:

- The `@install_root` block is only needed if the existing setup mapped
  `/install` to `install.sh` via a `rewrite`. If `/install` was already
  resolving to a file literally named `install` (the bootstrap copied to
  that name), instead deploy `install-bootstrap.sh` to
  `/var/lib/caddy/rp-install/install` and keep `@install_files` as the
  single matcher — no `@install_root` needed.
- The glob `/install/rp-install-*.tar.gz` matches every version published
  to the directory, so future releases need no further Caddyfile edits.

## 2. Deploy the artefacts

On a build host (or CI):

```sh
# In the monxas-remote-pulse checkout:
scripts/build-install-tarball.sh                 # uses version from pyproject.toml
# or: scripts/build-install-tarball.sh 1.0.2

ls dist/
# rp-install-1.0.2.tar.gz
# rp-install-1.0.2.tar.gz.sha256
# rp-install-latest.tar.gz
# rp-install-latest.tar.gz.sha256
```

Copy to **both** Caddy LXCs (270 and 271 — they share the keepalived VIP
`.250` but each serves from its own local filesystem):

```sh
# Tarball + sha256 sidecars
for host in 192.168.0.246 192.168.0.247; do   # adjust to current LXC IPs
    scp dist/rp-install-1.0.2.tar.gz \
        dist/rp-install-1.0.2.tar.gz.sha256 \
        dist/rp-install-latest.tar.gz \
        dist/rp-install-latest.tar.gz.sha256 \
        root@${host}:/var/lib/caddy/rp-install/install/
done

# Bootstrap wrapper (overwrites previous /install file)
for host in 192.168.0.246 192.168.0.247; do
    scp scripts/install-bootstrap.sh \
        root@${host}:/var/lib/caddy/rp-install/install-bootstrap.sh
    # If /install is the bare path with no extension, symlink it:
    ssh root@${host} \
        "cp /var/lib/caddy/rp-install/install-bootstrap.sh \
            /var/lib/caddy/rp-install/install \
         && chown caddy:caddy /var/lib/caddy/rp-install/install*"
done
```

## 3. Apply

The Caddyfile is rendered by Ansible (`homelab-infra`, role
`roles/caddy_lxc`). Edit
`roles/caddy_lxc/templates/rp.monxas.casa.j2`, commit, then re-run the
play. For an out-of-band hot-fix:

```sh
# On each Caddy LXC (270 and 271), as root:
sudoedit /etc/caddy/sites/rp.monxas.casa
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

## 4. Validate

```sh
# Bootstrap wrapper served at /install
curl -fsSL https://rp.monxas.casa/install | head -3
# Expect: shebang + "Remote-Pulse install bootstrap wrapper"

# Tarball download
curl -fsSLO https://rp.monxas.casa/install/rp-install-latest.tar.gz
curl -fsSL  https://rp.monxas.casa/install/rp-install-latest.tar.gz.sha256

# End-to-end (audit mode, no token required)
curl -fsSL https://rp.monxas.casa/install | sh -s -- --show
# Expect: "Remote-Pulse installer plan" banner
```

## 5. Rollback

Revert the Caddyfile matcher block and `systemctl reload caddy`. The old
single-file `/install.sh` (and the legacy `/install` mapping) remain on
disk and continue to serve — note that any client following the new
multi-file install.sh will still fail until the tarball path is
re-introduced.

## Related

- ADR-0008 Remote-Pulse, F1 installer.
- `scripts/install-bootstrap.sh` — the wrapper served at `/install`.
- `scripts/build-install-tarball.sh` — the build pipeline.
- `tests/test_install_bootstrap.sh` — smoke tests.
