#!/usr/bin/env bash
# Trust Caddy's local root CA (used for https://dhandrishti.test) from the file on disk.
# Unlike `caddy trust`, this needs no running Caddy. Safe to re-run.
#   Chrome/Chromium: ~/.pki/nssdb (no sudo)
#   Firefox:         every profile with a cert9.db (no sudo; restart Firefox afterwards)
#   System store:    /usr/local/share/ca-certificates (sudo; used by curl, wget, ...)
set -euo pipefail
CA="${XDG_DATA_HOME:-$HOME/.local/share}/caddy/pki/authorities/local/root.crt"
NAME="DhanDrishti dev - Caddy Local Authority"

if [[ ! -f "$CA" ]]; then
  echo "No Caddy root CA yet at $CA. Run 'pnpm proxy' once (Ctrl-C after it starts), then retry." >&2
  exit 1
fi
command -v certutil >/dev/null || { echo "certutil missing: sudo apt install libnss3-tools" >&2; exit 1; }
echo "Trusting: $(openssl x509 -in "$CA" -noout -subject | sed 's/subject=//')"
echo "SHA-256:  $(openssl x509 -in "$CA" -noout -fingerprint -sha256 | cut -d= -f2)"

add_nss() { # $1 = NSS database dir, $2 = label
  certutil -d "sql:$1" -D -n "$NAME" >/dev/null 2>&1 || true   # replace any older copy
  certutil -d "sql:$1" -A -t "C,," -n "$NAME" -i "$CA"
  echo "  ok  $2"
}

mkdir -p "$HOME/.pki/nssdb"
[[ -f "$HOME/.pki/nssdb/cert9.db" ]] || certutil -d "sql:$HOME/.pki/nssdb" -N --empty-password
add_nss "$HOME/.pki/nssdb" "Chrome / Chromium"

shopt -s nullglob
for db in "$HOME"/.mozilla/firefox/*/cert9.db "$HOME"/snap/firefox/common/.mozilla/firefox/*/cert9.db; do
  add_nss "$(dirname "$db")" "Firefox profile $(basename "$(dirname "$db")")"
done

if [[ "${SKIP_SYSTEM:-0}" != "1" ]]; then
  echo "System store (asks for your password):"
  sudo install -m 0644 "$CA" /usr/local/share/ca-certificates/dhandrishti-caddy-local.crt
  sudo update-ca-certificates >/dev/null
  echo "  ok  /usr/local/share/ca-certificates/dhandrishti-caddy-local.crt"
fi
echo "Done. Restart the browser, then open https://dhandrishti.test"
