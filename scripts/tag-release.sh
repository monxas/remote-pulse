#!/usr/bin/env sh
# Tag and push v1.0.0 release. Run from main branch clean working tree.
set -eu

VERSION="${1:?usage: $0 <version> (e.g. 1.0.0)}"

# Verify clean tree
[ -z "$(git status --porcelain)" ] || { echo "ERR working tree not clean"; exit 1; }

# Verify on main
[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || { echo "ERR not on main"; exit 1; }

# Create annotated tag
git tag -a "v${VERSION}" -m "Release v${VERSION}

See .github/RELEASE_NOTES_v${VERSION}.md for details."

# Push tag
git push origin "v${VERSION}"

echo "✓ Tagged v${VERSION} and pushed. GitHub Actions release.yml will trigger."
echo ""
echo "Next steps:"
echo "  1. Wait for GitHub Actions to build binaries"
echo "  2. Edit release notes at https://github.com/monxas/remote-pulse/releases/tag/v${VERSION}"
echo "  3. Attach .github/RELEASE_NOTES_v${VERSION}.md content to release"
echo "  4. Publish release (uncheck 'draft' if auto-drafted)"
