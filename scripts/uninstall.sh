#!/usr/bin/env bash
# 卸载 kimicode-tps-mac：停掉自启、移除 LaunchAgent；加 --purge 一并删除安装目录。
set -euo pipefail

LABEL="com.kimicode.tps-mac"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"
PREFIX="${KIMICODE_TPS_MAC_PREFIX:-$HOME/.local/share/kimicode-tps-mac}"
PURGE=0

usage() {
  cat <<'EOF'
用法: scripts/uninstall.sh [选项]

选项:
  --purge    同时删除安装目录（默认只停自启、保留文件）
  --prefix DIR  指定安装目录（与安装时保持一致）
  -h, --help    显示本帮助
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge) PURGE=1; shift ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage; exit 1 ;;
  esac
done

if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
  echo "==> 停止自启任务"
  launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
elif [[ -f "$PLIST_PATH" ]]; then
  launchctl unload -w "$PLIST_PATH" 2>/dev/null || true
fi

if [[ -f "$PLIST_PATH" ]]; then
  echo "==> 删除 $PLIST_PATH"
  rm -f "$PLIST_PATH"
fi

# 清理可能残留的进程（只匹配本项目的入口）
pkill -f "kimicode_tps_mac" 2>/dev/null || true

if [[ $PURGE -eq 1 ]]; then
  echo "==> 删除安装目录 $PREFIX"
  rm -rf "$PREFIX"
else
  echo "保留安装目录 ${PREFIX}（加 --purge 可一并删除）"
fi

echo "完成。"
