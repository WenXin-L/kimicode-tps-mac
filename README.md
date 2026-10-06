# kimicode-tps-mac

> macOS 小组件：用菜单栏图标实时显示 [Kimi Code](https://kimi.com/code) 模型输出的 token 速度（TPS）与首字延迟（TTFT），不占用 Dock。

Kimi Code 本身不显示 token 速度（官方 issue #35 仍开放），社区现有方案都是给终端 TUI 状态栏做的插件，桌面端没有对应工具。本项目直接读本机 Kimi Code 的数据，把速度和延迟放进菜单栏，写代码时抬眼就能看到。

## 特色

- **实时 TPS**：输出通道与思考通道分开统计，滚动窗口平滑，逐字更新。
- **首字延迟（TTFT）**：每一步的精确毫秒数，直接来自 Kimi Code 的用量数据。
- **每步精确速度**：步骤结束后用真实 `usage.output` 与流式耗时算出精确 TPS，不受字符估算误差影响。
- **会话统计**：近 5 步中位数、本会话平均 TPS / 步数 / 总 token、输入缓存命中率。
- **双数据源**：优先订阅本地 WebSocket 事件流，连不上时自动回退到会话日志 `wire.jsonl`。
- **不占 Dock**：进程激活策略为 accessory，菜单栏图标不会出现在 Dock 和 Cmd-Tab 里。
- **纯本地**：只读本地文件与 `127.0.0.1` 上的本地接口，不向任何远端发送数据，不需要屏幕录制等系统权限。
- **轻量**：依赖仅 `rumps` / `pyobjc-framework-Cocoa` / `websockets`，无后台服务。

## 它长什么样

### 菜单栏标题

`--title-units` 可让标题带上单位（默认不带，理由见下）。

| 当前状态 | 标题显示 | 说明 |
| --- | --- | --- |
| 已发出请求，还没吐出第一个字 | `⏳7s` | 沙漏 + 已等待秒数，**刻意不放闪电** |
| 思考中（`thinking.delta` 流入） | `🧠 52` | 思考通道的实时速度估算 |
| 输出中（`assistant.delta` 流入） | `⚡ 204` | 回答通道的实时速度估算 |
| 空闲 | `⚡ 247` | 最近一步的精确 TPS |
| 还没有任何数据 | `⚡ —` | 无数据 |

加 `--title-units` 后变成 `⏳9s` / `🧠 52 t/s` / `⚡ 204 t/s` / `⚡ 247 t/s`。

### 展开菜单

点开菜单栏图标后是这样（下例为示意，数值随机）：

```text
状态：输出中
模型：kimi-k2-turbo-preview
──────────────────────────────────────────────
实时：输出 204 t/s · 思考 0 t/s（本步 812+0 tok）
最近一步：247 t/s（1204 tok / 4.9s，main 轮 t_8f3c 步 3）
首字延迟：0.42s
──────────────────────────────────────────────
近 5 步中位数：231 t/s
本会话：238 t/s · 12 步 · 14822 tok
缓存命中：93%（读取 138240 tok）
──────────────────────────────────────────────
数据源：WS 流式
在 Finder 中显示日志
退出
```

- **状态**：空闲 / 等待首字 / 思考中 / 输出中。
- **实时**：当前滚动窗口内的估算速度，以及本步已累计的 token。
- **最近一步**：上一次 LLM 请求结束后的精确 TPS、token 数、流式耗时、轮次与步号。
- **本会话**：本次会话累计的精确平均 TPS、步数、输出 token 总数。
- **缓存命中**：输入侧缓存读取量占输入总量的比例。
- **数据源**：见下文「工作原理」，出现回退时会附带错误摘要。
- **在 Finder 中显示日志**：在访达里定位当前正在跟随的 `wire.jsonl`。

<!-- 截图占位：补图后把本节替换为 ![kimicode-tps-mac 菜单栏与展开菜单](docs/screenshot.png) -->
<!-- 建议补图：docs/screenshot.png（菜单栏标题 + 展开菜单各一张即可，可用系统截图命令 shift-cmd-4 截取菜单栏区域） -->

## 工作原理

两条数据源，**流式优先、文件兜底**。

```text
                  ┌──────────────────────────────────────┐
  Kimi Code       │ 1) 本地 WebSocket（逐字实时）        │
  桌面端/守护进程 ├─▶ ws://127.0.0.1:<port>/api/v1/ws     │──▶ 实时 TPS
                  │    端口: server/instances/*.json      │
                  │    令牌: server.token（Bearer）       │──▶ 精确 TPS / TTFT
                  └──────────────────────────────────────┘
                  ┌──────────────────────────────────────┐
  Kimi Code       │ 2) 会话日志（每步兜底）              │
  会话目录        ├─▶ sessions/*/session_*/agents/*/      │──▶ 精确 TPS / TTFT
                  │      wire.jsonl 中的 step.end 事件    │    （每步更新）
                  └──────────────────────────────────────┘
```

### 数据源 1：本地 WebSocket 事件流

Kimi Code 桌面端/守护进程在本机监听 HTTP/WS，端口记录在 `<KIMI_CODE_HOME>/server/instances/*.json`（含 `pid`、`port`、`heartbeat_at`，取存活进程中心跳最新的一个），Bearer 令牌在 `<KIMI_CODE_HOME>/server.token`。本工具用 `Authorization: Bearer <token>` 握手并订阅最近若干会话。

用到的三类事件：

- `assistant.delta` / `thinking.delta` / `tool.call.delta`：逐块文本增量，用于**实时速度**。流里没有 token 计数，只能按字符估算（CJK 约 1 字 1 token，其余约 4 字符 1 token），再按 `KIMICODE_TPS_MAC_LIVE_WINDOW_MS` 的滚动窗口平滑。
- `turn.step.completed`：带 `usage.output`、`llmStreamDurationMs`、`llmFirstTokenLatencyMs`，每步结束给出**精确的 TPS 与首字延迟**。
- `agent.status.updated`：用于显示当前模型名。

实现上踩到的几个协议细节（官方 asyncapi 未写清，已在源码注释中记录）：帧的 `type` 字段就是事件名本身，事件体在 `payload`；只发 `client_hello` 并不会真正订阅到会话，必须再显式发一条 `subscribe`；服务端会发应用层 `ping`，需要回 `pong`。

### 数据源 2：`wire.jsonl` 兜底

会话日志位于 `<KIMI_CODE_HOME>/sessions/<工作区>/session_*/agents/<agent>/wire.jsonl`。其中 `context.append_loop_event` 记录里嵌套的 `event.type == "step.end"` 带有与 WS 相同的用量与耗时字段，解析出来即可得到每一步的 TPS 与 TTFT。

WS 不可用、断开或报错时会自动改走这条路。代价是**每步更新而非逐字实时**，首字延迟也只有步骤结束后才能拿到。为避免重复计数，WS 正常时不会同时跑文件源；程序启动后有 5 秒宽限期，不急于回退。

## 安装

要求：macOS + Python >= 3.10。

### 快速开始

```bash
git clone https://github.com/WenXin-L/kimicode-tps-mac.git
cd kimicode-tps-mac
scripts/install.sh
```

<!-- 发布前替换：把上面的 WenXin-L 换成实际 GitHub 账号（pyproject.toml 的 Homepage/Issues 同理） -->

脚本会在 `~/.local/share/kimicode-tps-mac/` 下建独立虚拟环境并安装本项目，完成后启动：

```bash
~/.local/share/kimicode-tps-mac/venv/bin/kimicode-tps-mac
```

菜单栏出现 `⚡ —` 即启动成功（有数据后会变成 `⚡ 204` 之类）。

### 登录自启（可选）

```bash
scripts/install.sh --with-launch-agent
```

会额外安装 LaunchAgent `~/Library/LaunchAgents/com.kimicode.tps-mac.plist`：登录自动启动，崩溃自动拉起（从菜单点「退出」属于正常退出，不会被重启）。日志写到安装目录的 `hud.out.log` / `hud.err.log`。

安装脚本其他选项：

```bash
scripts/install.sh --prefix ~/Applications/kimicode-tps-mac   # 自定义安装目录
scripts/install.sh --python /opt/homebrew/bin/python3.12  # 指定解释器
scripts/install.sh --help
```

卸载：

```bash
scripts/uninstall.sh          # 停自启、删 plist，保留安装目录
scripts/uninstall.sh --purge  # 连安装目录一起删
```

### 用 pipx / uv 安装

```bash
pipx install .     # 或：uv tool install .
kimicode-tps-mac
```

这两种方式不包含 LaunchAgent，需要自启请参考 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) 中的说明手写 plist。

### 从源码开发运行

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/kimicode-tps-mac
```

仓库内还带一个开发启动脚本，直接用仓库里的 `.venv` 运行、单实例、日志落在 `hud.log`，参数会原样透传给程序：

```bash
./run.sh
./run.sh --title-units    # 参数直接透传，这条等于 python -m kimicode_tps_mac --title-units
```

**开了 iCloud「桌面与文档」同步的话注意一下**：`pip install -e .` 生成的 `.pth` 文件（`.venv/lib/python3.*/site-packages/_editable_impl_*.pth`）可能被 macOS 打上隐藏标志，而 Python 3.12 起 `site` 模块会跳过带隐藏标志的 `.pth`，于是出现「刚装完还能跑、过一会儿又 `ModuleNotFoundError: No module named 'kimicode_tps_mac'`」：

```bash
ls -lO .venv/lib/python3.*/site-packages/_editable_impl_*.pth   # flags 列出现 hidden 就是它
chflags nohidden .venv/lib/python3.*/site-packages/_editable_impl_*.pth
```

不想和这个问题打交道，可以换成非 editable 安装（代码会拷进 site-packages，不依赖 `.pth`，代价是改完源码要重装一次）：

```bash
.venv/bin/pip install .
```

安装脚本本身用的就是非 editable 安装，不受影响；开发时也可以直接用 `PYTHONPATH=src .venv/bin/python -m kimicode_tps_mac` 绕开。

部署方式对比、LaunchAgent 细节与排错请看 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

## 使用

### 命令行选项

| 参数 | 说明 |
| --- | --- |
| `kimicode-tps-mac` | 启动菜单栏应用（默认行为） |
| `--version` | 打印版本号后退出 |
| `--live SECONDS` | 无界面打印实时流式指标若干秒，用于验证 WS 通道 |
| `--probe SECONDS` | 无界面，只用 `wire.jsonl` 兜底源观察若干秒，用于验证文件通道 |
| `--selftest` | 启动菜单栏、打印自检信息后退出（验证 UI 层） |
| `--no-ws` | 强制只读 `wire.jsonl`，不连接本地守护进程 |
| `--title-units` | 菜单栏标题带上 `t/s` 单位（默认只显示数字） |
| `--state-file PATH` | 持续把实时指标写入该 JSON 文件，便于排错 |
| `--kimi-home PATH` | 覆盖 Kimi Code 数据目录（默认 `~/.kimi-code`） |
| `-h`, `--help` | 显示帮助 |

`--live` 与 `--probe` 是最常用的两个自检入口：

```bash
kimicode-tps-mac --live 30    # 应能看到 server: ('127.0.0.1', <port>) 与带 out=/think= 的实时行
kimicode-tps-mac --probe 10   # 应能看到 session: N steps, ... 与实际 wire.jsonl 路径
```

### 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `KIMI_CODE_HOME` | `~/.kimi-code` | Kimi Code 数据目录 |
| `KIMICODE_TPS_MAC_STATE_FILE` | 空（不写） | 等价于 `--state-file` |
| `KIMICODE_TPS_MAC_NO_WS` | 未设置 | 设为 `1` / `true` / `yes` / `on` 等价于 `--no-ws` |
| `KIMICODE_TPS_MAC_TITLE_UNITS` | 未设置 | 设为真值等价于 `--title-units` |
| `KIMICODE_TPS_MAC_LIVE_WINDOW_MS` | `3000` | 实时速度的滚动窗口（毫秒），越大越平滑 |
| `KIMICODE_TPS_MAC_REFRESH_MS` | `500` | 菜单栏的刷新间隔（毫秒） |

命令行参数的优先级高于环境变量。

## 常见问题

**为什么 Dock 和 Cmd-Tab 里没有它？**
进程的激活策略被设为 accessory（`NSApplicationActivationPolicyAccessory`），所以它只有菜单栏图标，不占 Dock 位。这是刻意的：HUD 是常驻的小工具，不应该占一个 Dock 位、也不该混在 Cmd-Tab 的窗口切换列表里。

**为什么「等待首字」时显示 `⏳7s` 而不是闪电？**
等待阶段没有任何速度可显示，而秒数每秒都会变。如果这时也放闪电，图标会一会儿有、一会儿没有地跳；换成沙漏既表意准确，也减少了菜单栏的视觉噪音。

**实时值是准确的吗？**
实时值是**估算**。流式增量里只有文本，没有 token 计数，只能按字符折算（CJK 约 1 字 1 token，其余约 4 字符 1 token），所以对代码、英文、混排文本都会有偏差。**精确值来自每步结束**：菜单里的「最近一步」「本会话」「首字延迟」都是用真实 `usage.output` 与 `llmStreamDurationMs` 算的，不受估算影响。

**WS 连不上会怎样？**
自动回退到 `wire.jsonl` 文件源，一切照常显示，只是从逐字实时变成每步更新，菜单里「数据源」一栏会标注回退原因（例如 `wire.jsonl（WS 连接失败）`）。注意：如果根本没有检测到可用的守护进程（或使用了 `--no-ws`），「数据源」会一直显示 `未连接`，此时文件源仍在工作但不逐字更新。想强制只用文件源，用 `--no-ws`。

**需要屏幕录制权限吗？**
不需要。它不截屏、不监听键鼠、不申请任何辅助功能权限，只读 `~/.kimi-code` 下的本地文件，并在本机 `127.0.0.1` 上连本地的 Kimi Code 守护进程。

**为什么标题默认不带 `t/s`？**
带上单位后标题宽度变化更大（`204 t/s` 比 `204` 宽），数字位数一变就会顶动旁边的菜单栏图标。默认只放数字，单位和明细都放在展开菜单里；想要单位就用 `--title-units`。

**数据准不准，会不会漏？**
菜单栏刷新间隔默认 500ms，实时速度按 3 秒滚动窗口平滑，所以快速突发的速度峰值可能被抹平；需要看真实值请以「最近一步」为准。

## 开发与贡献

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'    # 额外装 ruff 与 pytest
./run.sh                             # 单实例启动，日志见 hud.log
```

- 代码结构：`src/kimicode_tps_mac/__main__.py`（命令行入口）、`core.py`（配置、路径发现、指标模型、两个数据源与共用的数据引擎 `Engine`）、`ui.py`（菜单栏与标题逻辑）。
- 菜单文案集中在 `ui.py` 的 `L` 字典里，标题逻辑是纯函数 `title_for()`。改动都容易验证。
- 提交前建议跑一遍 `.venv/bin/ruff check src`。欢迎提交 issue 与 PR；涉及数据源字段的改动请附上你观察到的原始事件样例。

## 致谢与相关项目

- **官方 issue**：[Kimi Code issue #35](https://github.com/MoonshotAI/kimi-code/issues/35)——希望官方提供 token 速度显示，目前仍开放。本项目是绕开该缺口的社区方案。
- 社区面向终端 TUI 状态栏的插件（如 `kimi-code-hud`、`kimi-quota-statusline`）启发了本项目；它们覆盖终端，本项目覆盖桌面菜单栏。
- 依赖 [rumps](https://github.com/jaredks/rumps)（菜单栏）与 [pyobjc](https://pyobjc.readthedocs.io/)（用 AppKit 把进程设为 accessory，不占 Dock）。

## 许可

[MIT](LICENSE)。Copyright (c) 2026 Wen Xin。
