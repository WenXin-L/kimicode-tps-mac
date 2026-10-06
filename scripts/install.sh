#!/usr/bin/env bash
# 安装 kimicode-tps-mac：建独立虚拟环境并安装本仓库，可选装 macOS 登录自启（LaunchAgent）。
set -euo pipefail

LABEL="com.kimicode.tps-mac"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${KIMICODE_TPS_MAC_PREFIX:-$HOME/.local/share/kimicode-tps-mac}"
LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENT_DIR/$LABEL.plist"
WITH_LAUNCH_AGENT=0
PYTHON_BIN="${KIMICODE_TPS_MAC_PYTHON:-}"

usage() {
  cat <<'EOF'
用法: scripts/install.sh [选项]

选项:
  --with-launch-agent   安装登录自启（LaunchAgent），崩溃自动拉起
  --prefix DIR          安装目录（默认 ~/.local/share/kimicode-tps-mac）
  --python PATH         指定 python3 解释器（需 >= 3.10）
  -h, --help            显示本帮助
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-launch-agent) WITH_LAUNCH_AGENT=1; shift ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --python) PYTHON_BIN="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "错误: 本项目依赖 macOS 菜单栏（rumps/AppKit），当前系统不是 Darwin。" >&2
  exit 1
fi

# --- 选择解释器 ---
if [[ -z "$PYTHON_BIN" ]]; then
  for cand in python3.13 python3.12 python3.11 python3.10 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    if command -v "$cand" >/dev/null 2>&1; then PYTHON_BIN="$(command -v "$cand")"; break; fi
  done
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "错误: 找不到可用的 python3，请用 --python 指定。" >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "错误: 需要 Python >= 3.10，当前为 $("$PYTHON_BIN" -V 2>&1)。" >&2
  exit 1
fi

echo "==> 安装目录: $PREFIX"
echo "==> 解释器:   $PYTHON_BIN ($("$PYTHON_BIN" -V 2>&1))"

mkdir -p "$PREFIX"
echo "==> 创建虚拟环境"
"$PYTHON_BIN" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/python" -m pip install --quiet --upgrade pip
echo "==> 安装 kimicode-tps-mac（来自 ${REPO_DIR}）"
"$PREFIX/venv/bin/python" -m pip install --quiet "$REPO_DIR"

EXEC="$PREFIX/venv/bin/kimicode-tps-mac"
echo "==> 已安装: $("$EXEC" --version)"

if [[ $WITH_LAUNCH_AGENT -eq 1 ]]; then
  echo "==> 安装登录自启（LaunchAgent）"
  mkdir -p "$LAUNCH_AGENT_DIR"
  sed -e "s|__LABEL__|$LABEL|g" \
      -e "s|__EXEC__|$EXEC|g" \
      -e "s|__LOG__|$PREFIX/hud.out.log|g" \
      -e "s|__ERRLOG__|$PREFIX/hud.err.log|g" \
      "$REPO_DIR/scripts/com.kimicode.tps-mac.plist.template" > "$PLIST_PATH"

  # 已加载时先卸载，避免重复
  launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
  if ! launchctl bootstrap "gui/$UID" "$PLIST_PATH" 2>/dev/null; then
    launchctl load -w "$PLIST_PATH"
  fi
  echo "==> 自启已启用（日志: $PREFIX/hud.out.log）"
  echo "    关闭自启: scripts/uninstall.sh"
else
  echo
  echo "完成。手动启动：$EXEC"
  echo "加 --with-launch-agent 可安装登录自启。"
fi
