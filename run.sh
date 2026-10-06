#!/usr/bin/env bash
# 开发用启动脚本：直接用仓库内的解释器运行（不安装），并保证单实例。
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PY="${KIMICODE_TPS_MAC_PYTHON:-$DIR/.venv/bin/python}"
if [[ ! -x "$PY" ]]; then
  echo "未找到 ${PY}，请先执行：" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 1
fi

pkill -f 'kimicode_tps_mac' 2>/dev/null || true
sleep 1
cd "$DIR"
PYTHONPATH="$DIR/src" nohup "$PY" -m kimicode_tps_mac "$@" >> hud.log 2>&1 &
disown
sleep 2
if pgrep -f 'kimicode_tps_mac' >/dev/null; then
  echo "kimicode-tps-mac 已启动（日志: $DIR/hud.log）"
  echo "应看到：菜单栏出现 ⚡ 图标"
else
  echo "启动失败，请查看 $DIR/hud.log" >&2
  exit 1
fi
