#!/usr/bin/env bash
set -euo pipefail

# 第一引数が空かどうかを正しく判定
if [ $# -ge 1 ] && [ -n "$1" ]; then
  SCRIPT="$1"
else
  SCRIPT="shutdown_bot_modern.py"
fi

if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "PyInstallerが見つかりません。pip install pyinstaller を実行してください。" >&2
  exit 1
fi

pyinstaller \
  --onefile \
  --name shutdown-bot \
  --collect-all paramiko \
  --collect-all cryptography \
  --collect-all rich \
  "$SCRIPT"

echo "dist/shutdown-bot を生成しました。"
