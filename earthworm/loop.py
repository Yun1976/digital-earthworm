# -*- coding: utf-8 -*-
"""数字蚯蚓 · 循环编排: 出洞 → 吃 → 消化 → 回洞 → 报告。

每一轮 = scan → judge → (apply? 冷置) → digest → ledger → report。
结构化 JSON 台账是证据(DENSITY-002 诚信协议); Markdown 报告是给人看的转述。
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

from . import density, digest, evolution, judge, providers, quarantine, report, scanner
from .config import REPO, Config, filter_roots


def state_dir() -> Path:
    return REPO / "state"


def cycles_dir() -> Path:
    return state_dir() / "cycles"


def ledger_file() -> Path:
    return state_dir() / "ledger.jsonl"


def load_cold_hashes() -> set:
    hashes = set()
    lf = ledger_file()
    if lf.is_file():
        for line in lf.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("action") == "cold" and e.get("applied") and e.get("sha256"):
                hashes.add(e["sha256"])
    return hashes


def _append_ledger(entries: list) -> None:
    lf = ledger_file()
    lf.parent.mkdir(parents=True, exist_ok=True)
    with open(lf, "a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _heartbeat(cycle_id: str, phase: str, **extra) -> None:
    """心跳文件: 桌宠壳靠它感知一切进食(不管是谁触发的)。"""
    hb = {"ts": dt.datetime.now().isoformat(timespec="seconds"),
          "cycle": cycle_id, "phase": phase, **extra}
    state_dir().mkdir(parents=True, exist_ok=True)
    (state_dir() / "heartbeat.json").write_text(
        json.dumps(hb, ensure_ascii=False), encoding="utf-8")


def cycle(cfg: Config) -> dict:
    t0 = time.time()
    now = dt.datetime.now()
    cycle_id = now.strftime("%Y%m%d-%H%M%S")
    _heartbeat(cycle_id, "dig")

    roots, rejected = filter_roots(cfg.roots)
    print(f"[1/5] 出洞扫描: {roots}" + (f"(硬保护拒绝: {rejected})" if rejected else ""))
    scan = scanner.scan(roots, cfg)
    print(f"      见过 {scan.total_seen} 个文件, 候选 {len(scan.candidates)}, "
          f"重复副本 {scan.dupes}, node_modules(只记不动) {len(scan.node_modules)}"
          + (", 已达扫描上限截断" if scan.truncated else ""))

    print(f"[2/5] 召唤内核: provider={cfg.provider}")
    kernel, kdesc = providers.make_kernel(cfg.provider, cfg)
    print(f"      内核: {kdesc}")

    print("[3/5] 冗余判定(双钥门+升级道)…")
    treasure_hashes = set(digest.load_index().keys())
    corpus = density.load_corpus(digest.treasure_dir())
    decisions = judge.run(scan.candidates, kernel, cfg,
                          treasure_hashes, corpus)
    n_cold = sum(1 for d in decisions if d.action == "cold")
    n_dig = sum(1 for d in decisions if d.action == "digest")
    n_obs = sum(1 for d in decisions if d.action == "observe")
    print(f"      判定: 吃 {n_cold} / 消化 {n_dig} / 观察 {n_obs} / 跳过 "
          f"{len(decisions) - n_cold - n_dig - n_obs}")

    print("[4/5] 执行(吃进冷区 + 消化出卡)…")
    moved = quarantine.cold_move(decisions, cycle_id, cfg) if cfg.apply else []
    if cfg.apply:
        print(f"      冷置 {len(moved)} 项")
    else:
        print("      DRY-RUN: 未移动任何文件")

    cards = []
    idx = digest.load_index()
    for d in decisions:
        if d.action != "digest" or not d.cand.sha256 or d.cand.sha256 in idx:
            continue
        kinfo = dict(d.kernel)
        kinfo["model"] = kdesc
        try:
            card = digest.make_card(d.cand, kinfo, cycle_id, dry_run=not cfg.apply)
            idx[d.cand.sha256] = str(card)
            d.card = str(card)
            cards.append(str(card))
        except OSError as e:
            print(f"      出卡失败 {d.cand.path}: {e}")
    if idx:
        digest.save_index(idx)
    print(f"      宝藏卡 +{len(cards)}")

    elapsed = round(time.time() - t0, 1)
    entries = []
    for d in decisions:
        e = d.as_dict()
        e["cycle"] = cycle_id
        e["ts"] = now.isoformat(timespec="seconds")
        e["mode"] = "apply" if cfg.apply else "dry-run"
        if isinstance(e.get("kernel"), dict):
            e["kernel"]["engine"] = kdesc
        entries.append(e)
    _append_ledger(entries)

    summary = {
        "cycle": cycle_id, "ts": now.isoformat(timespec="seconds"),
        "mode": "apply" if cfg.apply else "dry-run",
        "kernel": kdesc, "roots": roots, "rejected_roots": rejected,
        "scan": {"total_seen": scan.total_seen, "total_files": scan.total_files,
                 "total_bytes": scan.total_bytes, "candidates": len(scan.candidates),
                 "dupes": scan.dupes, "skipped": scan.skipped,
                 "node_modules": len(scan.node_modules), "truncated": scan.truncated},
        "actions": {"cold": n_cold, "digest": n_dig, "observe": n_obs,
                    "ignore": len(decisions) - n_cold - n_dig - n_obs},
        "moved": moved, "cards": cards, "elapsed_s": elapsed,
        "decisions": [d.as_dict() for d in decisions],
    }
    cycles_dir().mkdir(parents=True, exist_ok=True)
    (cycles_dir() / f"{cycle_id}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[5/5] 代谢报告…")
    rpath = report.write_report(summary)
    print(f"完成: {rpath}")
    summary["report"] = str(rpath)

    # 晋升进化: 每轮吃法沉淀为模式统计与判例(越吃越聪明)
    lr = evolution.learn_from_decisions(summary["decisions"])
    summary["evolution"] = lr
    if lr["patterns"]:
        print(f"进化: 模式 {lr['patterns']} 个, 习得快车道 {len(lr['learned'])} 个"
              + (f", 新习得 {lr['newly_learned']}" if lr["newly_learned"] else ""))
    _heartbeat(cycle_id, "done", cold=summary["actions"]["cold"],
               digest=summary["actions"]["digest"],
               observe=summary["actions"]["observe"], report=str(rpath))
    return summary
