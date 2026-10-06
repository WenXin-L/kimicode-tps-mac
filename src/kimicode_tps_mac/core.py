"""Kimi Code TPS HUD —— 在 macOS 菜单栏实时显示模型输出速度。

数据来源有两条路，流式优先、文件兜底：

1. Kimi Code 桌面端/守护进程的本地 WebSocket（``ws://127.0.0.1:<port>/api/v1/ws``，
   Bearer 令牌取自 ``<KIMI_CODE_HOME>/server.token``，端口取自
   ``<KIMI_CODE_HOME>/server/instances/*.json``）：

   - ``assistant.delta`` / ``thinking.delta`` / ``tool.call.delta``：逐块增量，
     用于滚动窗口实时速度
   - ``turn.step.completed``：带 ``usage.output``、``llmStreamDurationMs``、
     ``llmFirstTokenLatencyMs``，用于每步结束后的精确速度与首字延迟

2. 会话日志 ``<KIMI_CODE_HOME>/sessions/*/session_*/agents/*/wire.jsonl`` 的增量解析，
   从其中的 ``step.end`` 事件取同样的字段。WS 不可用时自动改走这条路（此时为每步更新）。
"""

from __future__ import annotations

import glob
import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

WIRE_GLOB = "*/session_*/agents/*/wire.jsonl"
SOURCE_WS = "WS 流式"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


@dataclass
class Config:
    """运行配置：环境变量可覆盖，命令行参数优先级最高。"""

    kimi_home: Path = field(default_factory=lambda: Path(os.environ.get("KIMI_CODE_HOME") or Path.home() / ".kimi-code"))
    state_file: str = field(default_factory=lambda: os.environ.get("KIMICODE_TPS_MAC_STATE_FILE", ""))
    enable_ws: bool = field(default_factory=lambda: not _env_bool("KIMICODE_TPS_MAC_NO_WS"))
    title_units: bool = field(default_factory=lambda: _env_bool("KIMICODE_TPS_MAC_TITLE_UNITS"))
    live_window_s: float = field(default_factory=lambda: _env_float("KIMICODE_TPS_MAC_LIVE_WINDOW_MS", 3000) / 1000.0)
    refresh_s: float = field(default_factory=lambda: _env_float("KIMICODE_TPS_MAC_REFRESH_MS", 500) / 1000.0)
    subscribe_refresh_s: float = 20.0
    rolling_window: int = 5
    fallback_grace_s: float = 5.0

    @property
    def sessions_dir(self) -> Path:
        return self.kimi_home / "sessions"


# --------------------------------------------------------------------------- #
# 路径与通道发现
# --------------------------------------------------------------------------- #
def wire_files(cfg: Config) -> list[Path]:
    return [Path(p) for p in glob.glob(str(cfg.sessions_dir / WIRE_GLOB))]


def newest_wire(cfg: Config) -> Path | None:
    files = wire_files(cfg)
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def recent_session_ids(cfg: Config, limit: int = 8) -> list[str]:
    dirs = glob.glob(str(cfg.sessions_dir / "*" / "session_*"))
    dirs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return [Path(p).name for p in dirs[:limit]]


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def live_server(cfg: Config) -> tuple[str, int, str] | None:
    """发现本地守护进程，返回 ``(host, port, token)``；不可用时返回 None。"""
    token_file = cfg.kimi_home / "server.token"
    if not token_file.exists():
        return None
    try:
        token = token_file.read_text().strip()
    except OSError:
        return None
    if not token:
        return None
    best = None
    for path in glob.glob(str(cfg.kimi_home / "server" / "instances" / "*.json")):
        if ".tmp." in path:
            continue
        try:
            info = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not _pid_alive(info.get("pid", 0)):
            continue
        if best is None or info.get("heartbeat_at", 0) > best.get("heartbeat_at", 0):
            best = info
    if not best:
        return None
    return best.get("host", "127.0.0.1"), int(best["port"]), token


def est_tokens(text: str) -> float:
    """按字符估算 token 数：CJK 约 1 字 1 token，其余约 4 字符 1 token。"""
    cjk = 0
    for ch in text:
        code = ord(ch)
        if 0x3000 <= code <= 0x9FFF or 0xFF00 <= code <= 0xFFEF or 0x20000 <= code <= 0x2FA1F:
            cjk += 1
    return cjk + (len(text) - cjk) / 4.0


# --------------------------------------------------------------------------- #
# 指标模型
# --------------------------------------------------------------------------- #
@dataclass
class StreamState:
    """单个 agent 的实时状态（按 agentId 维度）。"""

    phase: str = "idle"  # idle | waiting | thinking | output
    phase_since: float = 0.0
    first_token_at: float | None = None
    window: deque = field(default_factory=lambda: deque(maxlen=400))
    live_out_tps: float = 0.0
    live_think_tps: float = 0.0
    live_out_tokens: float = 0.0
    live_think_tokens: float = 0.0

    def add(self, kind: str, text: str, live_window_s: float) -> None:
        now = time.time()
        if self.phase == "waiting":
            self.phase = "thinking" if kind == "think" else "output"
            self.first_token_at = now
        tokens = est_tokens(text)
        self.window.append((now, kind, tokens))
        if kind == "think":
            self.phase = "thinking"
            self.live_think_tokens += tokens
        else:
            self.phase = "output"
            self.live_out_tokens += tokens
        self.recompute(live_window_s)

    def recompute(self, live_window_s: float) -> None:
        now = time.time()
        while self.window and now - self.window[0][0] > live_window_s:
            self.window.popleft()
        if not self.window:
            self.live_out_tps = self.live_think_tps = 0.0
            return
        span = max(now - self.window[0][0], 0.4)
        out = sum(t for _, k, t in self.window if k == "out")
        think = sum(t for _, k, t in self.window if k == "think")
        self.live_out_tps = out / span
        self.live_think_tps = think / span


@dataclass
class Step:
    """一次 LLM 请求完成后的精确数据。"""

    model: str
    output_tokens: int
    stream_ms: int
    ttft_ms: int
    turn: str
    step: int
    session: str = ""
    agent: str = ""

    @property
    def tps(self) -> float:
        return self.output_tokens / (self.stream_ms / 1000) if self.stream_ms > 0 else 0.0


@dataclass
class SessionStats:
    steps: int = 0
    output_tokens: int = 0
    stream_ms: int = 0
    ttft_ms: int = 0
    cache_read: int = 0
    input_other: int = 0

    @property
    def avg_tps(self) -> float:
        return self.output_tokens / (self.stream_ms / 1000) if self.stream_ms > 0 else 0.0

    @property
    def cache_hit(self) -> float:
        total = self.cache_read + self.input_other
        return 100.0 * self.cache_read / total if total else 0.0


class Metrics:
    """线程安全的指标容器：数据源线程写，界面线程读。"""

    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or Config()
        self.lock = threading.Lock()
        self.model = "—"
        self.session = ""
        self.agent = "main"
        self.last_step: Step | None = None
        self.recent: deque = deque(maxlen=self.cfg.rolling_window)
        self.stats = SessionStats()
        self.live: dict[str, StreamState] = {}
        self.active_agent: str | None = None
        self.source = "未连接"
        self.error: str | None = None
        self.ws_connected = False

    # --- 写 ---
    def on_llm_request(self, model: str | None = None) -> None:
        with self.lock:
            if model:
                self.model = model

    def on_phase_start(self, agent: str, session: str) -> None:
        with self.lock:
            state = self.live.setdefault(agent, StreamState())
            state.phase = "waiting"
            state.phase_since = time.time()
            state.first_token_at = None
            state.window.clear()
            state.live_out_tps = state.live_think_tps = 0.0
            state.live_out_tokens = state.live_think_tokens = 0.0
            self.active_agent = agent
            if session:
                self.session = session

    def on_delta(self, agent: str, kind: str, text: str) -> None:
        if not text:
            return
        with self.lock:
            state = self.live.setdefault(agent, StreamState())
            if state.phase == "idle":
                state.phase_since = time.time()
            state.add(kind, text, self.cfg.live_window_s)
            self.active_agent = agent

    def on_step_done(self, step: Step) -> None:
        with self.lock:
            self.last_step = step
            self.recent.append(step)
            self.stats.steps += 1
            self.stats.output_tokens += step.output_tokens
            self.stats.stream_ms += step.stream_ms
            self.stats.ttft_ms += step.ttft_ms
            state = self.live.get(step.agent)
            if state:
                state.phase = "idle"
                state.window.clear()
                state.live_out_tps = state.live_think_tps = 0.0

    def on_usage(self, cache_read: int, input_other: int) -> None:
        with self.lock:
            self.stats.cache_read += cache_read
            self.stats.input_other += input_other

    def set_source(self, source: str, error: str | None = None) -> None:
        with self.lock:
            self.source = source
            self.error = error

    def set_ws_connected(self, connected: bool) -> None:
        with self.lock:
            self.ws_connected = connected

    def note_file_source(self) -> None:
        """文件源开始供数时调用：WS 未连接时把数据源标注为 wire.jsonl。"""
        with self.lock:
            if not self.ws_connected:
                self.source = "wire.jsonl"
                self.error = None

    def switch(self, session: str, agent: str, model: str, reset: bool) -> None:
        with self.lock:
            self.session = session
            self.agent = agent
            if model:
                self.model = model
            if reset:
                self.stats = SessionStats()
                self.recent.clear()
                self.last_step = None
                self.live.clear()

    # --- 读 ---
    def snapshot(self) -> dict:
        with self.lock:
            state = self.live.get(self.active_agent) if self.active_agent else None
            if state:
                state.recompute(self.cfg.live_window_s)
            return {
                "model": self.model,
                "session": self.session,
                "agent": self.agent,
                "last_step": self.last_step,
                "recent": list(self.recent),
                "stats": self.stats,
                "phase": state.phase if state else "idle",
                "phase_since": state.phase_since if state else 0.0,
                "out_tps": state.live_out_tps if state else 0.0,
                "think_tps": state.live_think_tps if state else 0.0,
                "out_tokens": state.live_out_tokens if state else 0.0,
                "think_tokens": state.live_think_tokens if state else 0.0,
                "source": self.source,
                "error": self.error,
            }


# --------------------------------------------------------------------------- #
# 数据源 1：WebSocket 流式事件
# --------------------------------------------------------------------------- #
class WsClient(threading.Thread):
    """订阅本地守护进程的事件流。

    协议要点（实测得到，官方 asyncapi 未写清）：

    - 帧的 ``type`` 字段**就是事件名本身**（如 ``assistant.delta``），事件体在 ``payload``
    - 只发 ``client_hello`` 不会真正订阅到会话，必须再显式发一条 ``subscribe``
    - ``websockets`` 的 ``async for ws in connect(...)`` 重连写法会静默挂起，故用
      ``await connect()`` + 重连循环
    """

    def __init__(self, metrics: Metrics, target: tuple[str, int, str]):
        super().__init__(daemon=True)
        self.metrics = metrics
        self.cfg = metrics.cfg
        self.host, self.port, self.token = target
        self._stop = threading.Event()
        self._subs: list[str] = recent_session_ids(self.cfg)

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        import asyncio

        try:
            asyncio.run(self._main())
        except Exception as exc:  # 连接层失败 → 立刻回退文件源
            self.metrics.set_ws_connected(False)
            self.metrics.set_source("wire.jsonl（WS 失败）", f"{type(exc).__name__}: {exc}")

    async def _main(self) -> None:
        import asyncio
        import uuid

        import websockets

        url = f"ws://{self.host}:{self.port}/api/v1/ws"
        headers = {"Authorization": f"Bearer {self.token}"}
        while not self._stop.is_set():
            try:
                ws = await websockets.connect(url, additional_headers=headers, open_timeout=8)
            except Exception as exc:
                self.metrics.set_ws_connected(False)
                self.metrics.set_source("wire.jsonl（WS 连接失败）", f"{type(exc).__name__}: {exc}")
                await asyncio.sleep(3)
                continue
            self.metrics.set_ws_connected(True)
            self.metrics.set_source(SOURCE_WS)
            try:
                await self._session(ws, uuid)
            except Exception as exc:
                self.metrics.set_ws_connected(False)
                self.metrics.set_source("wire.jsonl（WS 断开）", f"{type(exc).__name__}: {exc}")
            finally:
                self.metrics.set_ws_connected(False)
                try:
                    await ws.close()
                except Exception:
                    pass
            if not self._stop.is_set():
                await asyncio.sleep(1)

    async def _session(self, ws, uuid) -> None:
        import asyncio

        await ws.send(
            json.dumps(
                {
                    "type": "client_hello",
                    "id": str(uuid.uuid4()),
                    "payload": {"client_id": str(uuid.uuid4()), "subscriptions": self._subs},
                }
            )
        )
        await ws.send(
            json.dumps(
                {"type": "subscribe", "id": str(uuid.uuid4()), "payload": {"session_ids": self._subs}}
            )
        )
        last_refresh = time.time()
        while not self._stop.is_set():
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                raw = None
            if raw is not None:
                await self._handle(json.loads(raw), ws, uuid)
            if time.time() - last_refresh > self.cfg.subscribe_refresh_s:
                last_refresh = time.time()
                current = recent_session_ids(self.cfg)
                if current != self._subs:
                    self._subs = current
                    await ws.send(
                        json.dumps(
                            {
                                "type": "subscribe",
                                "id": str(uuid.uuid4()),
                                "payload": {"session_ids": self._subs},
                            }
                        )
                    )

    async def _handle(self, msg: dict, ws, uuid) -> None:
        import uuid as _uuid

        mtype = msg.get("type")
        if mtype == "ping":
            await ws.send(
                json.dumps(
                    {
                        "type": "pong",
                        "id": str(_uuid.uuid4()),
                        "payload": {"nonce": (msg.get("payload") or {}).get("nonce", "")},
                    }
                )
            )
            return
        if mtype in ("server_hello", "ack", "pong", "subscribe_ack", "client_hello_ack"):
            return
        if mtype == "error":
            self.metrics.set_source("WS 错误", json.dumps(msg.get("payload"), ensure_ascii=False)[:200])
            return

        sid = msg.get("session_id", "")
        payload = msg.get("payload") or {}
        agent = str(payload.get("agentId", "main"))

        if mtype in ("turn.started", "turn.step.started"):
            self.metrics.switch(sid, agent, None, reset=False)
            self.metrics.on_phase_start(agent, sid)
        elif mtype == "assistant.delta":
            self.metrics.on_delta(agent, "out", payload.get("delta", ""))
        elif mtype == "thinking.delta":
            self.metrics.on_delta(agent, "think", payload.get("delta", ""))
        elif mtype == "tool.call.delta":
            self.metrics.on_delta(agent, "out", payload.get("argumentsPart", ""))
        elif mtype == "turn.step.completed":
            usage = payload.get("usage") or {}
            step = Step(
                model=self.metrics.model,
                output_tokens=int(usage.get("output") or 0),
                stream_ms=int(payload.get("llmStreamDurationMs") or 0),
                ttft_ms=int(payload.get("llmFirstTokenLatencyMs") or 0),
                turn=str(payload.get("turnId", "?")),
                step=int(payload.get("step") or 0),
                session=sid,
                agent=agent,
            )
            self.metrics.switch(sid, agent, None, reset=False)
            if step.output_tokens > 0 and step.stream_ms > 0:
                self.metrics.on_step_done(step)
            self.metrics.on_usage(
                int(usage.get("inputCacheRead") or 0), int(usage.get("inputOther") or 0)
            )
        elif mtype == "agent.status.updated":
            model = payload.get("model")
            if model:
                self.metrics.on_llm_request(str(model))


# --------------------------------------------------------------------------- #
# 数据源 2：wire.jsonl 兜底
# --------------------------------------------------------------------------- #
@dataclass
class Tailer:
    """增量跟随最新的 wire.jsonl，解析其中的 step.end 事件。"""

    metrics: Metrics
    path: Path | None = None
    offset: int = 0
    partial: str = ""
    pending_since: float | None = None
    _last_scan: float = 0.0
    agent: str = "main"
    model: str = "—"

    @property
    def cfg(self) -> Config:
        return self.metrics.cfg

    def _switch_to(self, path: Path, replay: bool) -> None:
        self.path = path
        self.offset = 0
        self.partial = ""
        self.agent = Path(path).parent.name
        self.pending_since = None
        session = Path(path).parent.parent.name
        if replay:
            self._read(Path(path).read_text(errors="replace"))
            self.offset = Path(path).stat().st_size
        else:
            with open(path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                self.offset = fh.tell()
        self.metrics.switch(session, self.agent, self.model, reset=True)
        self.metrics.note_file_source()

    def poll(self) -> None:
        now = time.time()
        if self.path is None or now - self._last_scan > 2.0:
            self._last_scan = now
            newest = newest_wire(self.cfg)
            if newest and newest != self.path:
                stale = now - newest.stat().st_mtime > 60
                if self.path is None:
                    self._switch_to(newest, replay=True)
                elif newest.stat().st_mtime > self.path.stat().st_mtime and not stale:
                    self._switch_to(newest, replay=False)
        if self.path is None:
            return
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                chunk = fh.read()
                self.offset = fh.tell()
        except FileNotFoundError:
            self.path = None
            return
        if chunk:
            self._read(self.partial + chunk.decode("utf-8", errors="replace"))
            self.metrics.note_file_source()

    def _read(self, text: str) -> None:
        lines = text.split("\n")
        self.partial = lines.pop()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                self._apply(json.loads(line))
            except json.JSONDecodeError:
                continue

    def _apply(self, record: dict) -> None:
        rtype = record.get("type")
        if rtype == "llm.request":
            self.model = record.get("modelAlias") or record.get("model") or self.model
            self.metrics.on_llm_request(self.model)
            self.pending_since = time.time()
            self.metrics.on_phase_start(self.agent, self.metrics.session)
            return
        if rtype == "usage.record":
            if record.get("model"):
                self.model = record["model"]
                self.metrics.on_llm_request(self.model)
            usage = record.get("usage") or {}
            self.metrics.on_usage(
                int(usage.get("inputCacheRead") or 0), int(usage.get("inputOther") or 0)
            )
            return
        if rtype != "context.append_loop_event":
            return
        event = record.get("event") or {}
        if event.get("type") != "step.end":
            return
        usage = event.get("usage") or {}
        step = Step(
            model=self.model,
            output_tokens=int(usage.get("output") or 0),
            stream_ms=int(event.get("llmStreamDurationMs") or 0),
            ttft_ms=int(event.get("llmFirstTokenLatencyMs") or 0),
            turn=str(event.get("turnId", "?")),
            step=int(event.get("step") or 0),
            session=self.metrics.session,
            agent=self.agent,
        )
        self.pending_since = None
        if step.output_tokens > 0 and step.stream_ms > 0:
            self.metrics.on_step_done(step)


# --------------------------------------------------------------------------- #
# 数据引擎：把两个数据源与指标容器组装起来，供菜单栏界面使用
# --------------------------------------------------------------------------- #
class Engine:
    """按“流式优先、文件兜底”的策略驱动数据源并产出快照。"""

    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or Config()
        self.metrics = Metrics(self.cfg)
        self.ws: WsClient | None = None
        if self.cfg.enable_ws:
            target = live_server(self.cfg)
            if target:
                self.ws = WsClient(self.metrics, target)
        self.tailer = Tailer(self.metrics)
        self.started_at = time.time()
        self._last_source = ""
        self.source_changed = False

    def start(self) -> None:
        if self.ws:
            self.ws.start()
        self.metrics.note_file_source()

    def stop(self) -> None:
        if self.ws:
            self.ws.stop()

    @property
    def tailer_path(self) -> Path | None:
        return self.tailer.path

    def tick(self) -> dict:
        """刷新数据源并返回最新快照（应在界面线程按刷新间隔调用）。"""
        self.source_changed = False
        snap = self.metrics.snapshot()
        # WS 健康时不跑文件兜底，避免两个数据源重复计数
        ws_ok = self.ws is not None and snap["source"] == SOURCE_WS
        if not ws_ok and time.time() - self.started_at > self.cfg.fallback_grace_s:
            self.tailer.poll()
            snap = self.metrics.snapshot()
        if self.ws is not None and snap["source"].startswith("WS 错误"):
            self.metrics.set_source("wire.jsonl（WS 报错回退）", snap["error"])
            snap = self.metrics.snapshot()
        if snap["source"] != self._last_source:
            self._last_source = snap["source"]
            self.source_changed = True
        return snap
