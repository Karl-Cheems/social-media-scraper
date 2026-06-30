#!/bin/bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
case "$OS" in
    linux*)  PLAT=linux ;;
    darwin*) PLAT=macos ;;
    *) echo "Windows: run: powershell -File setup.ps1"; exit 1 ;;
esac
OUT="$DIR/lark-cli"
cat "$DIR"/lark-cli-"$PLAT".dat.* > "$OUT"
chmod +x "$OUT"
echo "Done: $OUT"
