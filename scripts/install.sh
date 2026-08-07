#!/usr/bin/env sh
set -eu

WITH_PYTHON=0
if [ "${1:-}" = "--with-python" ]; then
  WITH_PYTHON=1
elif [ "$#" -gt 0 ]; then
  echo "usage: scripts/install.sh [--with-python]" >&2
  exit 2
fi

command -v cargo >/dev/null 2>&1 || {
  echo "cargo is required; install Rust stable from https://rustup.rs" >&2
  exit 1
}

cargo install --path . --locked

if [ "$WITH_PYTHON" -eq 1 ]; then
  PYTHON_BIN="${CANDLE_CLI_PYTHON:-python3}"
  "$PYTHON_BIN" -m pip install -r requirements.txt
fi

echo "installed candle-cli; run: candle-cli doctor"
