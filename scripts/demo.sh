#!/usr/bin/env sh
set -eu

CANDLE_BIN="${CANDLE_CLI_BIN:-cargo run --quiet --}"

echo "[1/5] environment"
sh -c "$CANDLE_BIN doctor"
echo "[2/5] API mapping evidence"
sh -c "$CANDLE_BIN migrate map torch.add --pretty"
echo "[3/5] static migration scan"
sh -c "$CANDLE_BIN migrate scan examples/migration_demo --pretty"
echo "[4/5] deterministic patch preview (source is not modified)"
sh -c "$CANDLE_BIN migrate rewrite examples/migration_demo --pretty"
echo "[5/5] frozen security heldout"
sh -c "$CANDLE_BIN security-heldout"
