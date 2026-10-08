#!/usr/bin/env bash
# Download a pinned, checksum-verified Caddy binary into .tools/ (no root needed).
set -euo pipefail
VERSION="${CADDY_VERSION:-2.11.7}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="$ROOT/.tools"
ARCHIVE="caddy_${VERSION}_linux_amd64.tar.gz"
BASE="https://github.com/caddyserver/caddy/releases/download/v${VERSION}"

if [[ -x "$DEST/caddy" ]] && "$DEST/caddy" version | grep -q "v${VERSION}"; then
  echo "Caddy v${VERSION} already installed at $DEST/caddy"; exit 0
fi
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 -o "$TMP/$ARCHIVE" "$BASE/$ARCHIVE"
curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 -o "$TMP/checksums.txt" "$BASE/caddy_${VERSION}_checksums.txt"
(cd "$TMP" && grep " ${ARCHIVE}\$" checksums.txt | sha512sum -c -)
mkdir -p "$DEST"
tar -xzf "$TMP/$ARCHIVE" -C "$TMP" caddy
install -m 0755 "$TMP/caddy" "$DEST/caddy"
echo "Installed $("$DEST/caddy" version) at $DEST/caddy"
echo
echo "One-time, to let it serve HTTPS on port 443 without running as root:"
echo "  sudo setcap cap_net_bind_service=+ep $DEST/caddy"
