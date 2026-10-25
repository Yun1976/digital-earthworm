# -*- coding: utf-8 -*-
"""数字蚯蚓 · 命令行入口。

  python -m earthworm dig --roots <目录>... [--apply]   出洞进食(默认 dry-run)
  python -m earthworm restore --cycle <id>              冷区原路送回
  python -m earthworm status                            洞里最近怎样了
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import digest, loop, quarantine
from .config import REPO, Config


def _build_cfg(a) -> Config:
    roots = list(a.roots or [])
    if getattr(a, "roots_file", None):
        rf = Path(a.roots_file)
        if rf.is_file():
            roots += [l.strip() for l in rf.read_text(encoding="utf-8").splitlines()
                      if l.strip() and not l.strip().startswith("#")]
        else:
            print(f"roots 文件不存在: {rf}")
            sys.exit(2)
    return Config(
        roots=roots, apply=a.apply, provider=a.provider, model=a.model,
        ollama_url=a.ollama_url, llm_judge_limit=a.llm_limit,
        min_age_days=a.min_age_days, max_move_mb=a.max_mb,
        limit_files=a.limit_files, max_depth=a.max_depth,
    )


def cmd_dig(a) -> int:
    cfg = _build_cfg(a)
    if not cfg.roots:
        print("拒绝: 未指定 --roots(安全默认: 不给范围就不扫)")
        return 2
    print(f"数字蚯蚓 v0.1 ｜ 模式: {'APPLY(移入冷区)' if cfg.apply else 'DRY-RUN(只看不动)'}"
          f" ｜ 陈化线 ≥{cfg.min_age_days} 天")
    s = loop.cycle(cfg)
    if s["kernel"].startswith(("ollama 不可达", "deepseek 不可用")):
        print("注意: 内核不可达, 本轮只有纯规则快车道可吃, 语义道全部观察。")
    return 0


def cmd_restore(a) -> int:
    results = quarantine.restore(a.cycle)
    ok = sum(1 for r in results if r["ok"])
    print(f"恢复循环 {a.cycle}: {ok}/{len(results)} 成功")
    for r in results:
        mark = "✓" if r["ok"] else "✗"
        print(f" {mark} {r['from']}  ({r['note']})")
    return 0 if ok == len(results) else 1


def cmd_status(_a) -> int:
    cdir = loop.cycles_dir()
    cycles = sorted(cdir.glob("*.json")) if cdir.is_dir() else []
    print("=== 数字蚯蚓 · 洞口告示板 ===")
    print(f"仓库: {REPO}")
    if cycles:
        last = json.loads(cycles[-1].read_text(encoding="utf-8"))
        print(f"最近循环: {last['cycle']} ({last['mode']}, 内核 {last['kernel']}, "
              f"{last['elapsed_s']}s)")
        print(f"  判定: 吃 {last['actions']['cold']} / 消化 {last['actions']['digest']}"
              f" / 观察 {last['actions']['observe']}")
    else:
        print("最近循环: (还没有出过洞, 试试 python -m earthworm dig --roots <目录>)")
    cards = sorted(digest.treasure_dir().rglob("*.md")) if digest.treasure_dir().is_dir() else []
    cards = [c for c in cards if c.name != "INDEX.md"]
    print(f"宝藏库: {len(cards)} 张知识卡  ({digest.treasure_dir()})")
    q = REPO / "state" / "quarantine"
    qc = sorted(p.name for p in q.iterdir() if p.is_dir()) if q.is_dir() else []
    print(f"冷区循环: {len(qc)} 个  ({q})")
    return 0


def cmd_learn(_a) -> int:
    from . import evolution
    if evolution.STATS.exists():
        evolution.STATS.unlink()  # 台账是唯一事实源, 全量重建保证幂等
    entries = []
    lf = loop.ledger_file()
    if lf.is_file():
        for line in lf.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    r = evolution.learn_from_decisions(entries)
    print(f"模式统计 {r['patterns']} 个, 习得快车道 {len(r['learned'])} 个")
    for k in r["learned"]:
        print(f"  + {k}")
    return 0


def cmd_promote(a) -> int:
    from . import digest, evolution, providers
    kernel, kdesc = providers.make_kernel(a.provider, Config(provider=a.provider,
                                                             ollama_url=a.ollama_url))
    if kernel is None:
        print(f"内核不可达, 无法压实: {kdesc}")
        return 2
    made = evolution.promote(kernel, digest.treasure_dir())
    if made:
        print(f"聚合晋升 +{len(made)} 张:")
        for m in made:
            print(f"  {m}")
    else:
        print("没有达到晋升门槛的主题簇(同主题宝藏卡 ≥4 张才压实)。")
    return 0


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="earthworm", description="数字蚯蚓: 吃垃圾, 吐知识")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dig", help="出洞进食(默认 dry-run)")
    d.add_argument("--roots", nargs="+", default=None, help="扫描根目录(可多个)")
    d.add_argument("--roots-file", default=None,
                   help="从文件读扫描根(每行一个, # 注释), 常驻任务用")
    d.add_argument("--apply", action="store_true", help="真吃(移入冷区); 缺省 dry-run")
    d.add_argument("--provider", default="ollama",
                   choices=["ollama", "deepseek", "none"], help="驱动内核")
    d.add_argument("--model", default="", help="内核模型名(默认按偏好序自动挑)")
    d.add_argument("--ollama-url", default="http://192.168.1.2:11434")
    d.add_argument("--llm-limit", type=int, default=40, help="单轮内核裁决上限")
    d.add_argument("--min-age-days", type=float, default=7.0)
    d.add_argument("--max-mb", type=float, default=200.0, help="单文件冷置上限")
    d.add_argument("--limit-files", type=int, default=50000)
    d.add_argument("--max-depth", type=int, default=8)
    d.set_defaults(func=cmd_dig)

    r = sub.add_parser("restore", help="冷区原路送回")
    r.add_argument("--cycle", required=True)
    r.set_defaults(func=cmd_restore)

    s = sub.add_parser("status", help="洞口告示板")
    s.set_defaults(func=cmd_status)

    ln = sub.add_parser("learn", help="从台账重建模式统计/判例/习得快车道")
    ln.set_defaults(func=cmd_learn)

    pr = sub.add_parser("promote", help="同主题宝藏卡聚合晋升(压实成聚合卡)")
    pr.add_argument("--provider", default="ollama", choices=["ollama", "deepseek"])
    pr.add_argument("--ollama-url", default="http://192.168.1.2:11434")
    pr.set_defaults(func=cmd_promote)

    args = p.parse_args(argv)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
