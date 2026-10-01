#!/bin/sh
set -eu

DATA_DIR="${DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"

# Bind-mounted host volumes often keep root ownership / mode 600.
# Fix so the non-root app user can read and write durable JSON.
if [ "$(id -u)" = "0" ]; then
  chown -R bbi:bbi "$DATA_DIR" 2>/dev/null || true
  find "$DATA_DIR" -type d -exec chmod 775 {} \; 2>/dev/null || true
  find "$DATA_DIR" -type f -exec chmod 664 {} \; 2>/dev/null || true
  exec runuser -u bbi -- "$@"
fi

exec "$@"
