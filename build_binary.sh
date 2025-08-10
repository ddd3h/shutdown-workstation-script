#!/usr/bin/env bash
set -euo pipefail

SCRIPT="${1:-shutdown_bot_configured.py}"

if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "PyInstallerが見つかりません。pip install pyinstaller を実行してください。" >&2
  exit 1
fi

pyinstaller \
  --onefile \
  --name shutdown-bot \
  --collect-all paramiko \
  --collect-all cryptography \
  "$SCRIPT"

echo "dist/shutdown-bot を生成しました。"
