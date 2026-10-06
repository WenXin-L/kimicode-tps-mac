"""macOS 菜单栏界面。

菜单栏标题只放数字（不带单位），避免宽度反复变化导致图标左右跳动；
单位与明细都放在展开菜单里。想改文案只需修改下面的 ``L`` 字典。
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import time

from .core import Config, Engine

L = {
    "app_name": "kimicode-tps-mac",
    "idle_title": "⚡ —",
    "state_prefix": "状态",
    "state_idle": "空闲",
    "state_waiting": "等待首字",
    "state_thinking": "思考中",
    "state_output": "输出中",
    "model_prefix": "模型",
    "live_prefix": "实时",
    "last_prefix": "最近一步",
    "ttft_prefix": "首字延迟",
    "median_prefix": "中位数",
    "session_prefix": "本会话",
    "cache_prefix": "缓存命中",
    "source_prefix": "数据源",
    "open_log": "在 Finder 中显示日志",
    "quit": "退出",
    "steps_suffix": "步",
    "no_data": "—",
}


def fmt(value: float, unit: str = "") -> str:
    """单位后缀（t/s 等）只在展开菜单里使用。"""
    if not value:
        return L["no_data"]
    return f"{value:.0f}{unit}"


def title_for(snap: dict, title_units: bool = False) -> str:
    """根据指标快照计算菜单栏标题（纯函数，便于测试）。"""
    unit = " t/s" if title_units else ""
    phase = snap["phase"]
    if phase == "waiting":
        # 等待首字：只显示沙漏与秒数，不放闪电，减少视觉噪音
        elapsed = time.time() - snap["phase_since"] if snap["phase_since"] else 0.0
        return f"⏳{elapsed:.0f}s"
    if phase == "thinking" and snap["think_tps"]:
        return f"🧠 {snap['think_tps']:.0f}{unit}"
    if phase == "output" and snap["out_tps"]:
        return f"⚡ {snap['out_tps']:.0f}{unit}"
    last = snap["last_step"]
    if last and last.stream_ms:
        return f"⚡ {last.tps:.0f}{unit}"
    return L["idle_title"]


def hide_dock_icon() -> int:
    """把进程设为 accessory：保留菜单栏项，Dock 与 Cmd-Tab 中不再出现。"""
    import AppKit

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    return int(app.activationPolicy())


class Hud:
    """菜单栏应用主体。"""

    def __init__(self, cfg: Config | None = None, engine: Engine | None = None) -> None:
        import rumps

        self.rumps = rumps
        self.cfg = cfg or Config()
        self.engine = engine or Engine(self.cfg)
        self.engine.start()

        self.app = rumps.App(L["app_name"], title=L["idle_title"], quit_button=None)
        # 初始标题各不重复：rumps 用标题做菜单项索引键，空标题会被折叠成一项
        self.item_state = rumps.MenuItem(f"{L['state_prefix']}：…")
        self.item_model = rumps.MenuItem(f"{L['model_prefix']}：…")
        self.item_live = rumps.MenuItem(f"{L['live_prefix']}：…")
        self.item_last = rumps.MenuItem(f"{L['last_prefix']}：…")
        self.item_ttft = rumps.MenuItem(f"{L['ttft_prefix']}：…")
        self.item_med = rumps.MenuItem(f"{L['median_prefix']}：…")
        self.item_avg = rumps.MenuItem(f"{L['session_prefix']}：…")
        self.item_cache = rumps.MenuItem(f"{L['cache_prefix']}：…")
        self.item_src = rumps.MenuItem(f"{L['source_prefix']}：…")
        self.app.menu = [
            self.item_state,
            self.item_model,
            None,
            self.item_live,
            self.item_last,
            self.item_ttft,
            None,
            self.item_med,
            self.item_avg,
            self.item_cache,
            None,
            self.item_src,
            rumps.MenuItem(L["open_log"], callback=self.reveal),
            rumps.MenuItem(L["quit"], callback=self.quit),
        ]
        rumps.Timer(self.tick, self.cfg.refresh_s).start()

    # --- 菜单动作 ---
    def reveal(self, _sender):
        path = self.engine.tailer_path
        if path:
            subprocess.run(["open", "-R", str(path)], check=False)

    def quit(self, _sender):
        self.engine.stop()
        self.rumps.quit_application()

    # --- 周期刷新 ---
    def tick(self, _timer):
        self.apply(self.engine.tick())

    def apply(self, snap: dict) -> None:
        if self.engine.source_changed:
            print(f"[{time.strftime('%H:%M:%S')}] source: {snap['source']}", flush=True)

        self.app.title = title_for(snap, self.cfg.title_units)
        if self.cfg.state_file:
            self._dump_state(snap)

        state_text = {
            "idle": L["state_idle"],
            "waiting": L["state_waiting"],
            "thinking": L["state_thinking"],
            "output": L["state_output"],
        }[snap["phase"]]
        self.item_state.title = f"{L['state_prefix']}：{state_text}"
        self.item_model.title = f"{L['model_prefix']}：{snap['model']}"
        self.item_live.title = (
            f"{L['live_prefix']}：输出 {fmt(snap['out_tps'], ' t/s')} · "
            f"思考 {fmt(snap['think_tps'], ' t/s')}"
            f"（本步 {snap['out_tokens']:.0f}+{snap['think_tokens']:.0f} tok）"
        )

        last = snap["last_step"]
        if last:
            self.item_last.title = (
                f"{L['last_prefix']}：{fmt(last.tps, ' t/s')}（{last.output_tokens} tok / "
                f"{last.stream_ms / 1000:.1f}s，{last.agent} 轮 {last.turn} 步 {last.step}）"
            )
            self.item_ttft.title = f"{L['ttft_prefix']}：{last.ttft_ms / 1000:.2f}s"
        else:
            self.item_last.title = f"{L['last_prefix']}：{L['no_data']}"
            self.item_ttft.title = f"{L['ttft_prefix']}：{L['no_data']}"

        recent_tps = [s.tps for s in snap["recent"] if s.tps > 0]
        median = statistics.median(recent_tps) if recent_tps else 0.0
        self.item_med.title = (
            f"近 {self.cfg.rolling_window} {L['steps_suffix']}{L['median_prefix']}：{fmt(median, ' t/s')}"
        )
        stats = snap["stats"]
        self.item_avg.title = (
            f"{L['session_prefix']}：{fmt(stats.avg_tps, ' t/s')} · {stats.steps} "
            f"{L['steps_suffix']} · {stats.output_tokens} tok"
        )
        self.item_cache.title = (
            f"{L['cache_prefix']}：{stats.cache_hit:.0f}%（读取 {stats.cache_read} tok）"
        )
        src = snap["source"]
        if snap["error"]:
            src = f"{src} · {snap['error'][:60]}"
        self.item_src.title = f"{L['source_prefix']}：{src}"

    def _dump_state(self, snap: dict) -> None:
        """把当前指标写入文件（KIMICODE_TPS_MAC_STATE_FILE），便于外部观察与排错。"""
        last = snap["last_step"]
        payload = {
            "title": self.app.title,
            "phase": snap["phase"],
            "model": snap["model"],
            "session": snap["session"],
            "agent": snap["agent"],
            "out_tps": round(snap["out_tps"], 1),
            "think_tps": round(snap["think_tps"], 1),
            "out_tokens": round(snap["out_tokens"], 1),
            "think_tokens": round(snap["think_tokens"], 1),
            "last_step_tps": round(last.tps, 1) if last else None,
            "last_step_tokens": last.output_tokens if last else None,
            "last_step_ttft_ms": last.ttft_ms if last else None,
            "session_steps": snap["stats"].steps,
            "session_tokens": snap["stats"].output_tokens,
            "session_avg_tps": round(snap["stats"].avg_tps, 1),
            "cache_hit_pct": round(snap["stats"].cache_hit),
            "source": snap["source"],
            "error": snap["error"],
            "updated_at": time.time(),
        }
        tmp = f"{self.cfg.state_file}.tmp"
        try:
            with open(tmp, "w") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            os.replace(tmp, self.cfg.state_file)
        except OSError:
            pass

    def run(self) -> None:
        self.app.run()


def selftest(cfg: Config | None = None) -> None:
    """真实启动应用，2.5 秒后打印菜单栏状态并退出（验证 UI 层可用）。"""
    import rumps

    policy = hide_dock_icon()
    hud = Hud(cfg)

    def report(_timer):
        status_item = getattr(hud.app._nsapp, "nsstatusitem", None)
        print(f"NSStatusItem: {'created' if status_item is not None else 'MISSING'}", flush=True)
        print(f"激活策略: {policy}（0=常规/Dock 可见, 1=accessory/无 Dock 图标）", flush=True)
        if status_item is not None:
            print(f"菜单栏标题: {status_item.button().title()!r}", flush=True)
        for item in hud.app.menu.values():
            if hasattr(item, "title"):
                print(f"  - {item.title}", flush=True)
        rumps.quit_application()

    rumps.Timer(report, 2.5).start()
    hud.app.run()
