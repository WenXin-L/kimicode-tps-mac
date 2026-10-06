"""命令行入口：默认启动菜单栏应用，其余子模式用于自检与排错。"""

from __future__ import annotations

import argparse
import time

from . import __version__
from .core import Config, Metrics, Tailer, WsClient, live_server
from .ui import hide_dock_icon, selftest


def live_probe(cfg: Config, seconds: float) -> int:
    """打印实时流式指标（无界面），验证 WS 通道是否可用。"""
    metrics = Metrics(cfg)
    target = live_server(cfg) if cfg.enable_ws else None
    print("server:", target[:2] if target else "未找到（无 server.token 或守护进程未运行）")
    ws = WsClient(metrics, target) if target else None
    if ws:
        ws.start()
    deadline = time.time() + seconds
    while time.time() < deadline:
        snap = metrics.snapshot()
        if snap["phase"] != "idle" or snap["out_tps"] or snap["think_tps"]:
            print(
                f"[{time.strftime('%H:%M:%S')}] {snap['phase']:8} "
                f"out={snap['out_tps']:6.1f} think={snap['think_tps']:6.1f} t/s "
                f"tokens={snap['out_tokens']:.0f}+{snap['think_tokens']:.0f} "
                f"src={snap['source']}",
                flush=True,
            )
        time.sleep(1.0)
    if ws:
        ws.stop()
    last = metrics.snapshot()["last_step"]
    if last:
        print(f"last exact step: {last.output_tokens} tok / {last.stream_ms} ms = {last.tps:.1f} t/s")
    return 0


def wire_probe(cfg: Config, seconds: float) -> int:
    """只用 wire.jsonl 兜底源观察一段时间，验证文件通道。"""
    metrics = Metrics(cfg)
    tailer = Tailer(metrics)
    deadline = time.time() + seconds
    while time.time() < deadline:
        tailer.poll()
        time.sleep(0.5)
    snap = metrics.snapshot()
    print(
        f"session: {snap['stats'].steps} steps, {snap['stats'].output_tokens} tok, "
        f"avg {snap['stats'].avg_tps:.1f} t/s, cache {snap['stats'].cache_hit:.0f}%"
    )
    print(f"文件: {tailer.path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kimicode-tps-mac",
        description="Kimi Code 实时 token 速度菜单栏小组件（macOS）",
    )
    parser.add_argument("--version", action="version", version=f"kimicode-tps-mac {__version__}")
    parser.add_argument("--live", type=float, metavar="SECONDS", help="无界面打印实时流式指标，验证 WS 通道")
    parser.add_argument("--probe", type=float, metavar="SECONDS", help="只用 wire.jsonl 兜底源观察，验证文件通道")
    parser.add_argument("--selftest", action="store_true", help="启动菜单栏并打印自检信息后退出")
    parser.add_argument("--no-ws", action="store_true", help="强制只读 wire.jsonl（不连接本地守护进程）")
    parser.add_argument("--title-units", action="store_true", help="菜单栏标题带上 t/s 单位（默认只显示数字）")
    parser.add_argument("--state-file", metavar="PATH", help="把实时指标持续写入该 JSON 文件，便于排错")
    parser.add_argument("--kimi-home", metavar="PATH", help="覆盖 Kimi Code 数据目录（默认 ~/.kimi-code）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = Config()
    if args.kimi_home:
        from pathlib import Path

        cfg.kimi_home = Path(args.kimi_home).expanduser()
    if args.no_ws:
        cfg.enable_ws = False
    if args.title_units:
        cfg.title_units = True
    if args.state_file:
        cfg.state_file = args.state_file

    if args.probe:
        return wire_probe(cfg, args.probe)
    if args.live:
        return live_probe(cfg, args.live)
    if args.selftest:
        selftest(cfg)
        return 0

    hide_dock_icon()
    from .ui import Hud

    Hud(cfg).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
