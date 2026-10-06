# 部署与排错指南

面向安装、自启配置与故障排查。日常使用与功能说明见 [README](../README.md)。

## 1. 环境要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | **必须 macOS**（`install.sh` 用 `uname -s` 检查，非 Darwin 直接报错退出）。依赖 AppKit/rumps，其他系统无法运行。 |
| macOS 版本 | 需要图形登录会话。`launchctl` 的 `bootstrap` / `bootout` 需 macOS 10.11+，建议 macOS 11 及以上。开发验证环境为 macOS 27.0.1（arm64）。 |
| 架构 | Apple Silicon 与 Intel 均可（依赖均有对应 wheel）。 |
| Python | **>= 3.10**（`pyproject.toml` 中 `requires-python`，安装脚本也会校验）。验证使用 Python 3.12.15。 |
| 依赖 | 运行时：`rumps>=0.4.0`、`pyobjc-framework-Cocoa>=9.0`、`websockets>=13.0`；开发可选：`ruff>=0.5`、`pytest>=8.0`。 |
| 权限 | 不需要屏幕录制、辅助功能、麦克风等任何系统权限。只读 `~/.kimi-code` 下的文件，并连接本机 `127.0.0.1` 上的本地守护进程。 |
| 磁盘 | 安装目录（含独立虚拟环境）约几十 MB。 |

注意事项：

- LaunchAgent 只在图形会话（`Aqua`）里加载，通过 SSH 登录的会话里 `launchctl bootstrap gui/$UID ...` 可能失败——请在本地终端或图形会话中安装自启。
- 菜单栏空间不足（刘海屏 + 菜单栏项过多）时图标可能被系统隐藏，见 [5.1](#51-菜单栏没有图标)。

## 2. 三种部署方式

| 方式 | 适用场景 | 独立环境 | 自带 LaunchAgent | 升级方式 |
| --- | --- | --- | --- | --- |
| A. `scripts/install.sh` | 普通使用，推荐 | 是（`<prefix>/venv`） | 可选（`--with-launch-agent`） | 重新拉代码后再跑一次脚本 |
| B. `pipx` / `uv tool` | 已经用它们管理命令行工具 | 是 | 否，需手写 plist | `pipx upgrade kimicode-tps-mac` / `uv tool upgrade kimicode-tps-mac` |
| C. 源码开发模式 | 改代码、提 PR | 是（仓库内 `.venv`） | 否 | 改完即生效（editable 安装） |

### 方式 A：脚本安装（推荐）

```bash
git clone https://github.com/WenXin-L/kimicode-tps-mac.git
cd kimicode-tps-mac

scripts/install.sh                        # 只安装
scripts/install.sh --with-launch-agent    # 安装 + 登录自启
```

脚本做了什么：

1. 校验系统为 Darwin、解释器为 Python >= 3.10；
2. 在 `${KIMICODE_TPS_MAC_PREFIX:-$HOME/.local/share/kimicode-tps-mac}` 下创建虚拟环境 `<prefix>/venv`；
3. 升级 pip 并安装本仓库（`pip install <仓库目录>`）；
4. 打印 `<prefix>/venv/bin/kimicode-tps-mac --version` 的安装结果；
5. 若带 `--with-launch-agent`，生成并加载 `~/Library/LaunchAgents/com.kimicode.tps-mac.plist`。

可选参数：

```bash
scripts/install.sh --prefix "$HOME/Applications/kimicode-tps-mac"   # 自定义安装目录
scripts/install.sh --python /opt/homebrew/bin/python3.12        # 指定解释器
scripts/install.sh --help
```

安装后手动启动：

```bash
~/.local/share/kimicode-tps-mac/venv/bin/kimicode-tps-mac               # 启动菜单栏图标
```

如果执行过 `--prefix`，请把这个路径记下来：卸载时要用同样的 `--prefix`（或同样的 `KIMICODE_TPS_MAC_PREFIX`），否则脚本找不到安装目录。

### 方式 B：pipx / uv

```bash
cd kimicode-tps-mac
pipx install .          # 或：uv tool install .
kimicode-tps-mac            # 直接启动
```

升级：

```bash
pipx upgrade kimicode-tps-mac      # 或：uv tool upgrade kimicode-tps-mac
```

这两种方式不会安装 LaunchAgent。若要登录自启，把下面的 plist 存为 `~/Library/LaunchAgents/com.kimicode.tps-mac.plist`（先把 `ProgramArguments` 里的路径换成 `which kimicode-tps-mac` 的输出），然后按 [3.3](#33-常用管理命令) 加载：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.kimicode.tps-mac</string>
  <key>ProgramArguments</key><array><string>/Users/你的用户名/.local/bin/kimicode-tps-mac</string></array>
  <key>RunAtLoad</key><true/>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
  <key>ProcessType</key><string>Interactive</string>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>/tmp/kimicode-tps-mac.out.log</string>
  <key>StandardErrorPath</key><string>/tmp/kimicode-tps-mac.err.log</string>
</dict>
</plist>
```

### 方式 C：源码开发模式

```bash
cd kimicode-tps-mac
python3 -m venv .venv
.venv/bin/pip install -e .            # 需要测试/lint：.venv/bin/pip install -e '.[dev]'

.venv/bin/kimicode-tps-mac           # 直接跑（菜单栏）
./run.sh                             # 或用开发脚本：杀旧进程 → nohup 启动 → 日志写 hud.log
./run.sh --title-units                # 参数会原样透传给程序
```

`run.sh` 的行为：用仓库内 `.venv`（可用 `KIMICODE_TPS_MAC_PYTHON` 覆盖解释器），带 `PYTHONPATH=src`，把命令行参数原样透传给程序（例如 `./run.sh --title-units`），启动前先 `pkill -f kimicode_tps_mac` 保证单实例，2 秒后检查进程是否存活，日志追加到仓库根的 `hud.log`。因为 `.venv` 里是 editable 安装，改完代码重启进程即可生效；editable 安装有个 iCloud 同步导致的坑，见 5.6。

## 3. LaunchAgent 登录自启

### 3.1 文件位置

| 内容 | 路径 |
| --- | --- |
| LaunchAgent 定义 | `~/Library/LaunchAgents/com.kimicode.tps-mac.plist` |
| 模板（仓库内） | `scripts/com.kimicode.tps-mac.plist.template` |
| 可执行文件 | `${KIMICODE_TPS_MAC_PREFIX:-$HOME/.local/share/kimicode-tps-mac}/venv/bin/kimicode-tps-mac` |
| 标准输出日志 | `<安装目录>/hud.out.log` |
| 标准错误日志 | `<安装目录>/hud.err.log` |

`install.sh` 会用 `sed` 把模板里的 `__LABEL__` / `__EXEC__` / `__LOG__` / `__ERRLOG__` 替换成真实值再写入 `~/Library/LaunchAgents/`。

### 3.2 各字段含义

| 字段 | 值 | 含义 |
| --- | --- | --- |
| `Label` | `com.kimicode.tps-mac` | 任务标识，`launchctl` 命令里都要用它 |
| `ProgramArguments` | `[<安装目录>/venv/bin/kimicode-tps-mac]` | 启动命令。要加参数（如 `--title-units`、`--no-ws`）就在这里追加 `<string>` |
| `RunAtLoad` | `true` | 加载时立即启动（登录后随会话加载） |
| `LimitLoadToSessionType` | `Aqua` | 只在 macOS 图形会话中加载，SSH/后台会话不加载 |
| `ProcessType` | `Interactive` | 告知系统这是交互式进程，便于调度 |
| `KeepAlive.SuccessfulExit` | `false` | 只有**异常退出**才自动拉起；从菜单点「退出」是正常退出，不会被重启 |
| `StandardOutPath` | `<安装目录>/hud.out.log` | 标准输出。数据源切换等诊断信息会打印在这里 |
| `StandardErrorPath` | `<安装目录>/hud.err.log` | 标准错误。启动失败、依赖缺失等问题看这里 |
| `EnvironmentVariables.PATH` | homebrew + 系统路径 | 保证子进程能找到 `open` 等系统命令 |

要点：**从菜单点「退出」不会触发重启**（这正是 `SuccessfulExit=false` 的效果），下次登录时 `RunAtLoad` 会再启动一次。想临时停用请用 `bootout`（见下）。

### 3.3 常用管理命令

```bash
# 查看是否已加载、最近状态、PID、最后退出码
launchctl print gui/$UID/com.kimicode.tps-mac

# 只列本任务的关键字段
launchctl print gui/$UID/com.kimicode.tps-mac | grep -E "state|pid|last exit|program"

# 临时停用（本次登录不再启动；文件保留）
launchctl bootout gui/$UID/com.kimicode.tps-mac

# 重新启用
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.kimicode.tps-mac.plist

# 重启进程（改完配置后）
launchctl kickstart -k gui/$UID/com.kimicode.tps-mac

# 看日志
tail -f ~/.local/share/kimicode-tps-mac/hud.out.log
tail -n 50 ~/.local/share/kimicode-tps-mac/hud.err.log
```

老版本 macOS 上也可以使用 `launchctl load -w <plist>` / `launchctl unload -w <plist>`，安装脚本在 `bootstrap` 失败时会自动回退到这条路径。

如果日志路径不是默认安装目录，请把上面的 `~/.local/share/kimicode-tps-mac` 换成你安装时用的 `--prefix`。

### 3.4 修改自启配置

例如想让自启实例的标题带上单位：

```bash
# 1) 编辑 plist，在 ProgramArguments 里追加参数
open -e ~/Library/LaunchAgents/com.kimicode.tps-mac.plist
```

```xml
  <key>ProgramArguments</key>
  <array>
    <string>/Users/你的用户名/.local/share/kimicode-tps-mac/venv/bin/kimicode-tps-mac</string>
    <string>--title-units</string>
  </array>
```

```bash
# 2) 让改动生效
launchctl bootout gui/$UID/com.kimicode.tps-mac
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.kimicode.tps-mac.plist
```

环境变量同理，写在 plist 的 `EnvironmentVariables` 字典里（例如 `KIMICODE_TPS_MAC_LIVE_WINDOW_MS`）。注意：**在终端里 `export` 的环境变量对 LaunchAgent 启动的进程无效**，因为那不是同一个启动环境。

## 4. 配置项详解

### 4.1 命令行参数

| 参数 | 默认 | 说明与调优建议 |
| --- | --- | --- |
| （无参数） | — | 启动菜单栏应用（默认行为） |
| `--version` | — | 打印 `kimicode-tps-mac <版本>` 后退出 |
| `--live SECONDS` | — | 无界面打印实时流式指标，验证 WS 通道。建议 30 秒，足够覆盖一次问答 |
| `--probe SECONDS` | — | 只用 `wire.jsonl` 兜底源观察，验证文件通道。建议 10 秒 |
| `--selftest` | — | 启动菜单栏、打印自检信息后退出（检查菜单栏项与激活策略，约 2.5 秒） |
| `--no-ws` | 关 | 强制只读 `wire.jsonl`。适合守护进程不稳定、只想看每步精确值的场景 |
| `--title-units` | 关 | 标题带 `t/s`。会让标题更长、跳动更明显，仅在不在意这点时使用 |
| `--state-file PATH` | 空 | 持续把指标写入 JSON。排错神器，见 4.4 |
| `--kimi-home PATH` | `~/.kimi-code` | 覆盖 Kimi Code 数据目录。用多个数据目录（如测试环境）时才需要 |

### 4.2 运行时环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `KIMI_CODE_HOME` | `~/.kimi-code` | Kimi Code 数据目录；`--kimi-home` 覆盖它 |
| `KIMICODE_TPS_MAC_STATE_FILE` | 空 | 等价于 `--state-file PATH` |
| `KIMICODE_TPS_MAC_NO_WS` | 未设置 | 真值（`1` / `true` / `yes` / `on`，大小写不敏感）等价于 `--no-ws`；`0` / `false` / `no` / `off` 视为假 |
| `KIMICODE_TPS_MAC_TITLE_UNITS` | 未设置 | 真值等价于 `--title-units` |
| `KIMICODE_TPS_MAC_LIVE_WINDOW_MS` | `3000` | 实时速度的滚动窗口，单位毫秒 |
| `KIMICODE_TPS_MAC_REFRESH_MS` | `500` | 菜单栏标题与菜单项的刷新间隔，单位毫秒 |

`KIMICODE_TPS_MAC_LIVE_WINDOW_MS` 调优：

- **调大**（如 `10000`）：实时值更平滑稳定，但变化迟钝，刚开口或刚收尾时会明显滞后。
- **调小**（如 `1000`）：反应快，能看出瞬时爆发，但数字抖动明显、可读性下降。
- 默认 3000ms 是平滑与灵敏的折中。不管怎么调，**精确值都以「最近一步」为准**——那是用真实 token 数除以真实流式耗时算出来的。

`KIMICODE_TPS_MAC_REFRESH_MS` 影响菜单栏刷新的频率：调小（如 `250`）更跟手，代价是略多 CPU；调大（如 `1000`）更省电，但数字更新会一顿一顿。注意它不改变数据的采样方式，只改变显示刷新。

命令行参数的优先级高于环境变量，所以临时实验可以直接：

```bash
KIMICODE_TPS_MAC_LIVE_WINDOW_MS=1000 kimicode-tps-mac
kimicode-tps-mac --title-units --no-ws
```

### 4.3 安装脚本的环境变量

| 变量 | 作用 |
| --- | --- |
| `KIMICODE_TPS_MAC_PREFIX` | 覆盖安装目录（等价于 `--prefix`）。`install.sh` 与 `uninstall.sh` 都会读，两处必须一致 |
| `KIMICODE_TPS_MAC_PYTHON` | 覆盖解释器路径（等价于 `--python`）。`run.sh` 也读它来决定用哪个 python |

### 4.4 `--state-file` 输出字段

每个刷新周期原子写入一次（先写 `PATH.tmp` 再 `os.replace`），字段如下：

| 字段 | 含义 |
| --- | --- |
| `title` | 当前菜单栏标题字符串 |
| `phase` | `idle` / `waiting` / `thinking` / `output` |
| `model` | 当前模型名 |
| `session` / `agent` | 当前会话 ID 与 agent 名 |
| `out_tps` / `think_tps` | 实时估算速度（输出 / 思考） |
| `out_tokens` / `think_tokens` | 本步已累计的估算 token |
| `last_step_tps` / `last_step_tokens` / `last_step_ttft_ms` | 最近一步的精确 TPS、token 数、首字延迟（毫秒） |
| `session_steps` / `session_tokens` / `session_avg_tps` | 本会话步数、输出 token 总数、精确平均 TPS |
| `cache_hit_pct` | 输入缓存命中率（百分比，四舍五入到整数） |
| `source` / `error` | 当前数据源与错误摘要 |
| `updated_at` | 写入时刻（Unix 时间戳） |

用法示例：

```bash
kimicode-tps-mac --state-file /tmp/kimi-hud-state.json
watch -n1 'python3 -m json.tool /tmp/kimi-hud-state.json'
```

## 5. 排错

### 5.1 菜单栏没有图标

按顺序排查：

```bash
# 1) 进程在不在？（用进程名匹配，不看 Dock）
pgrep -fl kimicode_tps_mac

# 2) 手动前台启动，看终端输出（会同时验证依赖是否齐全）
~/.local/share/kimicode-tps-mac/venv/bin/kimicode-tps-mac

# 3) 看自启日志
tail -n 50 ~/.local/share/kimicode-tps-mac/hud.err.log
tail -n 50 ~/.local/share/kimicode-tps-mac/hud.out.log

# 4) 看 LaunchAgent 状态与最后退出码
launchctl print gui/$UID/com.kimicode.tps-mac

# 5) 用自检确认 UI 层能不能真的建出菜单栏项
~/.local/share/kimicode-tps-mac/venv/bin/kimicode-tps-mac --selftest
```

常见原因：

- **进程根本没起来**：`pgrep` 无输出。看 `hud.err.log`；若是 `ModuleNotFoundError: rumps`，说明安装不完整，重跑 `scripts/install.sh`。
- **菜单栏被系统隐藏**：刘海屏且菜单栏项过多时，系统会把放不下的项藏起来。退掉几个菜单栏应用，或把菜单栏项拖到更靠左的位置。`--selftest` 会打印 `NSStatusItem: created`，说明组件本身没问题。
- **其实是启动了，只是没数据**：标题显示 `⚡ —` 属于无数据状态，不是崩溃，见 5.2。
- **自启没生效**：`launchctl print` 报 `Could not find service`。确认 plist 存在于 `~/Library/LaunchAgents/`，然后按 3.3 重新 `bootstrap`。日志路径为空或不存在时，检查 plist 里的 `<安装目录>` 是否与实际一致。

### 5.2 显示 `⚡ —`，或数据源一栏不对

「数据源」一行只反映 **WS 通道**状态，不反映文件通道：

| 显示 | 含义 | 该做什么 |
| --- | --- | --- |
| `未连接` | 没找到可用的本地守护进程（缺 `server.token`、`instances/*.json` 里没有存活进程，或用了 `--no-ws`）。此时**文件源仍在工作**，只是每步更新、不逐字 | 想逐字实时就启动 Kimi Code 桌面端/守护进程，然后重启本工具 |
| `WS 流式` | 已连上守护进程，实时流可用（最佳状态） | 无需处理 |
| `wire.jsonl（WS 连接失败）` | 找到了端口与令牌，但连不上（守护进程刚退出、端口被占、令牌过期） | 重启 Kimi Code 桌面端；用 `--live 30` 复核 |
| `wire.jsonl（WS 断开）` | 连上后连接中断 | 通常会自动重连，持续出现就重启桌面端 |
| `wire.jsonl（WS 失败）` | WS 线程启动阶段就抛异常（常见原因：缺少 `websockets` 依赖） | 检查 `hud.err.log`；重装依赖 |
| `WS 错误` / `wire.jsonl（WS 报错回退）` | 服务端返回了 error 帧，后面附有摘要 | 通常是订阅的会话已失效，重启桌面端 |

排查命令：

```bash
# 1) 确认 WS 通道是否可用（会打印 server 行与带 out=/think= 的实时行）
kimicode-tps-mac --live 30

# 2) 确认文件通道是否可用（会打印步数与实际 wire.jsonl 路径）
kimicode-tps-mac --probe 10

# 3) 确认令牌与实例信息文件是否存在
ls -l ~/.kimi-code/server.token
ls -l ~/.kimi-code/server/instances/
cat ~/.kimi-code/server/instances/*.json

# 4) 如果数据目录不在默认位置
kimicode-tps-mac --kimi-home /path/to/kimi-code --live 30
```

判断依据：

- `--live 30` 打印 `server: 未找到（无 server.token 或守护进程未运行）`：本工具认为本地没有可用的守护进程。**Kimi Code 桌面端没有运行时就是这样**——只剩下文件源，行为是所有指标都按「步」更新，`等待首字` 阶段不会有实时速度。
- `--live 30` 有 `server: ('127.0.0.1', <port>)`，但随后没有实时行：通道通了但没在用（没有正在进行的会话），发一条消息复测即可。
- `--probe 10` 打印 `文件: None`：一个 `wire.jsonl` 都没找到。确认 `~/.kimi-code/sessions/<工作区>/session_*/agents/*/wire.jsonl` 存在；从未在此机器上跑过 Kimi Code 会话时，这里本来就是空的。

### 5.3 显示长度跳动

菜单栏标题会被后面的数字宽度变化顶动，这是刻意的取舍：

- 默认标题只有数字，但位数本身仍会变（`⚡ 204` ↔ `⚡ 99` ↔ `⚡ 1004`），宽度会小幅变化，这是这一版的设计取舍。
- 加了 `--title-units` 之后变成 `⚡ 204 t/s`，宽度明显更长、跳动更容易察觉。想要稳一点就别加这个参数。
- 把 `KIMICODE_TPS_MAC_REFRESH_MS` 调大只会让变化来得慢一些，**不能消除**位数变化。
- 完全不能接受跳动的话，只能不用它，或者改 `ui.py` 的标题逻辑、给标题留固定宽度。

### 5.4 卸载后菜单栏还有图标

`scripts/uninstall.sh` 会做三件事：`launchctl bootout`（或退化为 `launchctl unload -w`）停掉自启、删除 `~/Library/LaunchAgents/com.kimicode.tps-mac.plist`、`pkill -f "kimicode_tps_mac"` 清掉残留进程。如果手动装过 plist 或手动启动过进程，按下面收尾：

```bash
# 1) 停掉自启任务
launchctl bootout gui/$UID/com.kimicode.tps-mac 2>/dev/null || \
  launchctl unload -w ~/Library/LaunchAgents/com.kimicode.tps-mac.plist 2>/dev/null

# 2) 删掉 plist，避免下次登录又自己起来
rm -f ~/Library/LaunchAgents/com.kimicode.tps-mac.plist
ls ~/Library/LaunchAgents/ | grep kimi || echo "plist 已清理"

# 3) 杀掉可能残留的进程
pkill -f kimicode_tps_mac

# 4) 连带删除安装目录与日志
scripts/uninstall.sh --purge
```

如果自定义过安装目录，记得用同一个前缀，否则第 4 步会删错位置：

```bash
scripts/uninstall.sh --prefix "$HOME/Applications/kimicode-tps-mac" --purge
# 或
KIMICODE_TPS_MAC_PREFIX="$HOME/Applications/kimicode-tps-mac" scripts/uninstall.sh --purge
```

用 pipx / uv 安装的，用 `pipx uninstall kimicode-tps-mac` / `uv tool uninstall kimicode-tps-mac`。

### 5.5 非 macOS 系统会直接报错

`scripts/install.sh` 第一步就检查系统：

```text
$ scripts/install.sh
错误: 本项目依赖 macOS 菜单栏（rumps/AppKit），当前系统不是 Darwin。
```

这是预期行为，不是环境问题：项目依赖 AppKit 提供的菜单栏能力，Linux/Windows 上没有替代实现。同理，`--selftest` 在非 macOS 上会因为 `import AppKit` 失败而报错。

### 5.6 `pip install -e .` 之后过一会儿又导入失败（iCloud 同步隐藏了 `.pth`）

**症状**：`pip install -e .` 刚跑完能启动，过一段时间再跑（或换个终端、重新登录后）就报：

```text
ModuleNotFoundError: No module named 'kimicode_tps_mac'
```

包明明装过、`.venv` 也在，问题出在 editable 安装生成的 `.pth` 文件被 macOS 打上了 `hidden` 文件标志。**开启了 iCloud「桌面与文档」同步的机器上**，同步器会给它认为该隐藏的文件加标志；而从 **Python 3.12 起，`site` 模块会跳过带隐藏标志的 `.pth`**，于是这个包再也导入不了——典型表现就是「刚装完能用，过一会儿又不行」。

诊断与修复：

```bash
# 1) 看 flags 列里有没有 hidden（在权限位后面那一列）
ls -lO .venv/lib/python3.*/site-packages/_editable_impl_*.pth

# 2) 去掉隐藏标志后验证能否导入
chflags nohidden .venv/lib/python3.*/site-packages/_editable_impl_*.pth
.venv/bin/python -c "import kimicode_tps_mac; print(kimicode_tps_mac.__file__)"
```

几点说明：

- `scripts/install.sh` 用的是**非 editable 安装**（`pip install <仓库目录>`），落到 site-packages 的是普通拷贝，不受影响；只有方式 C（源码开发模式）会碰到。
- 想绕开 editable 机制，可以直接用源码路径跑：`PYTHONPATH=src .venv/bin/python -m kimicode_tps_mac`（`run.sh` 用的就是这个办法）。
- 把仓库挪出 iCloud 同步目录（例如放到 `~/Code` 下）也能根治。

### 5.7 其他

- **Python 版本过低**：安装脚本会打印 `错误: 需要 Python >= 3.10，当前为 Python 3.9.x`。用 `--python` 指定一个更新的解释器。
- **改完代码没变化**：LaunchAgent 启动的是安装目录里的副本，不是仓库。开发时请用 `./run.sh` 或 `.venv/bin/kimicode-tps-mac`，或者重跑 `scripts/install.sh`。
- **想强制只用文件源**（例如 WS 一直报错）：`--no-ws`，或 `KIMICODE_TPS_MAC_NO_WS=1`；用 LaunchAgent 的话写进 plist 的 `EnvironmentVariables`。

## 6. 验证安装是否成功

安装后依次跑这三条，全部符合预期即安装成功。

### 1）`--version`

```bash
~/.local/share/kimicode-tps-mac/venv/bin/kimicode-tps-mac --version
```

预期输出（版本号随版本变化）：

```text
kimicode-tps-mac 0.1.0
```

能打印出内容就说明包已正确安装、命令行入口可用。

### 2）`--selftest`

```bash
~/.local/share/kimicode-tps-mac/venv/bin/kimicode-tps-mac --selftest
```

预期输出（约 2.5 秒后自动退出；`source:` 那行取决于你此刻的通道状态）：

```text
[04:17:00] source: WS 流式
NSStatusItem: created
激活策略: 1（0=常规/Dock 可见, 1=accessory/无 Dock 图标）
菜单栏标题: '⚡ —'
  - 数据源：WS 流式
  - 在 Finder 中显示日志
  - 退出
```

关注两点：

- `NSStatusItem: created`：菜单栏项建出来了（不是 `MISSING`）。
- `激活策略: 1`：进程是 accessory，符合「不占 Dock」的设计。

自检末尾列出的菜单项是不完整的——rumps 在 Python 侧按标题给菜单项建索引，而界面上的这些行标题初始为空，所以只有一部分能被枚举出来；**实际展开菜单是完整的**（状态、模型、实时、最近一步、首字延迟、中位数、本会话、缓存命中、数据源、显示日志、退出）。要看真实菜单，直接点开菜单栏图标即可。

### 3）`--live 30`

```bash
~/.local/share/kimicode-tps-mac/venv/bin/kimicode-tps-mac --live 30
```

先在 Kimi Code 里发一条消息，再运行本命令。预期输出（端口、速度随机）：

```text
server: ('127.0.0.1', 49220)
[04:18:54] waiting  out=   0.0 think=   0.0 t/s tokens=0+0 src=WS 流式
[04:18:55] waiting  out=   0.0 think=   0.0 t/s tokens=0+0 src=WS 流式
[04:18:56] thinking out=   0.0 think= 156.0 t/s tokens=0+81 src=WS 流式
last exact step: 324 tok / 1705 ms = 190.0 t/s
```

判读方式：

- `server: ('127.0.0.1', <port>)`：找到了守护进程与端口。若是 `server: 未找到（…）`，说明桌面端没在跑或令牌缺失，此时只有文件源可用（用 `--probe` 验证）。
- `src=WS 流式`：实时流已订阅成功。
- 出现 `waiting` → `thinking` / `output` → 结束时的 `last exact step` 一行：从实时估算到精确值的完整链路都通了。

到这里，菜单栏里应该能看到 `⏳` / `🧠` / `⚡` 的标题变化，点开菜单能看到模型名、最近一步、首字延迟、本会话统计等明细。
