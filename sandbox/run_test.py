# -*- coding: utf-8 -*-
"""数字蚯蚓 · 沙盒断言 harness。

跑法: python sandbox/run_test.py   (仓库根 cwd)
硬断言:
  A1 dry-run 不动任何文件;
  A2 apply 后快车道垃圾全部进冷区, MANIFEST 台账一致;
  A3 宝藏文件原地保留且字节不变(核心: 不吃宝藏);
  A4 restore 后全部原路送回, 与初始快照逐字节一致。
软断言(依赖内核智商, 只记录不判 FAIL):
  S1 日期名旧日志被双钥吃掉;
  S2 宝藏产出知识卡。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sandbox"))
import build_fixture as bf  # noqa: E402

PASS, FAIL, SOFT = [], [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def soft(name: str, ok: bool, detail: str = "") -> None:
    SOFT.append((name, ok))
    print(f"  [SOFT-{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def snapshot(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def latest_cycle() -> dict:
    cdir = REPO / "state" / "cycles"
    newest = max(cdir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(newest.read_text(encoding="utf-8"))


def dig(extra: list) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "earthworm", "dig",
         "--roots", str(bf.FIXTURE), "--min-age-days", "1",
         "--llm-limit", "12", *extra],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=1200,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def main() -> int:
    print("== 数字蚯蚓沙盒测试 ==")
    fixture = bf.build()
    snap0 = snapshot(fixture)
    print(f"夹具就绪: {fixture} ({len(snap0)} 文件)")

    print("-- 阶段1: DRY-RUN --")
    r1 = dig([])
    check("A1.1 dig 正常退出", r1.returncode == 0, (r1.stderr or "")[-200:])
    check("A1.2 dry-run 未动任何文件", snapshot(fixture) == snap0)
    s1 = latest_cycle()
    cold_planned = {d["path"] for d in s1["decisions"] if d["action"] == "cold"}
    for rel in bf.FASTLANE:
        check(f"A1.3 拟吃快车道: {rel}", str(fixture / rel) in cold_planned)
    tres = {str(fixture / rel) for rel in bf.TREASURE}
    check("A1.4 宝藏不在拟吃清单", not (tres & cold_planned))

    print("-- 阶段2: APPLY --")
    r2 = dig(["--apply"])
    check("A2.1 apply 正常退出", r2.returncode == 0, (r2.stderr or "")[-200:])
    s2 = latest_cycle()
    for rel in bf.FASTLANE:
        check(f"A2.2 已吃: {rel}", not (fixture / rel).exists())
    check("A2.3 快车道项 applied 标记", all(
        d.get("applied") for d in s2["decisions"]
        if d["action"] == "cold" and d["path"].endswith(tuple(bf.FASTLANE))))
    mf = REPO / "state" / "quarantine" / s2["cycle"] / "MANIFEST.json"
    check("A2.4 MANIFEST 台账存在且数目一致",
          mf.is_file() and len(json.loads(mf.read_text(encoding="utf-8"))["items"])
          == len([d for d in s2["decisions"] if d["action"] == "cold" and d.get("applied")]))
    snap2 = snapshot(fixture)
    check("A3.1 宝藏原地保留", all(rel in snap2 for rel in bf.TREASURE))
    check("A3.2 宝藏字节不变", all(snap2[rel] == snap0[rel] for rel in bf.TREASURE))
    log_rel = bf.SEMANTIC[0]
    if (fixture / log_rel).exists():
        dlog = [d for d in s2["decisions"] if d["path"] == str(fixture / log_rel)]
        soft("S1 旧日志处置", bool(dlog), dlog[0]["reason"] if dlog else "无判定")
    else:
        soft("S1 旧日志被双钥吃掉", True, "(cold)")
    idx_path = REPO / "state" / "treasure_index.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.is_file() else {}
    covered = [rel for rel in bf.TREASURE if snap0[rel] in idx]
    soft("S2 宝藏消化进宝藏库(出卡+索引)", len(covered) >= 1,
         f"{len(covered)}/{len(bf.TREASURE)} 已索引")

    print("-- 阶段3: RESTORE --")
    r3 = subprocess.run(
        [sys.executable, "-m", "earthworm", "restore", "--cycle", s2["cycle"]],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=300,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    check("A4.1 restore 正常退出", r3.returncode == 0, (r3.stderr or "")[-200:])
    check("A4.2 restore 后与初始快照逐字节一致", snapshot(fixture) == snap0)

    print(f"\n结果: PASS {len(PASS)} / FAIL {len(FAIL)} / SOFT {len(SOFT)}")
    if FAIL:
        print("失败项:", FAIL)
        return 1
    print("沙盒测试全部通过 ✅ (核心保证: dry-run 不动, 宝藏绝不被吃, 冷区可完整回滚)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
