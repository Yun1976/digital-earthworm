# -*- coding: utf-8 -*-
"""数字蚯蚓 · 冷区(影子剔除): 吃=移动到 append-only 冷区, 永不直接删除。

方案 §3.3/§3.5: 默认 dry-run/归档冷区; 物理删除是独立显式命令且本期不提供。
冷区结构:
  state/quarantine/<cycle_id>/NNN__<文件名>      被吃文件
  state/quarantine/<cycle_id>/MANIFEST.json      台账(原始路径/哈希/去向)
恢复: python -m earthworm restore --cycle <id>
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from .config import REPO


def cold_dir(cycle_id: str) -> Path:
    return REPO / "state" / "quarantine" / cycle_id


def _sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sanitize(name: str) -> str:
    bad = '<>:"/\\|?*'
    return "".join("_" if ch in bad else ch for ch in name)[:120] or "unnamed"


def _safe_move(src: Path, dst: Path) -> None:
    """同卷 rename 直达; 跨卷 copy→校验→替换→删源; 任何失败不落半截。"""
    try:
        os.rename(src, dst)
        return
    except OSError:
        pass
    tmp = dst.with_name(dst.name + ".parting")
    try:
        shutil.copy2(src, tmp)
        if tmp.stat().st_size != src.stat().st_size:
            raise OSError("copy size mismatch")
        os.replace(tmp, dst)
        src.unlink()
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def cold_move(decisions: list, cycle_id: str, cfg) -> list:
    """执行 cold 决策: 移入冷区并回写 applied/quarantine_path。返回移动清单。"""
    cdir = cold_dir(cycle_id)
    moved = []
    seq = 0
    for d in decisions:
        if d.action != "cold" or d.applied:
            continue
        src = Path(d.cand.path)
        if not src.is_file():
            d.action = "observe"
            d.reason += "; 移动时文件已不存在"
            continue
        # TOCTOU 守卫: 尺寸必须与扫描一致(内容哈希在 ≤32MB 时复核)
        try:
            if src.stat().st_size != d.cand.size:
                d.action = "observe"
                d.reason += "; 移动前复核发现文件已变化 → 观察"
                continue
            if d.cand.sha256 and d.cand.size <= 32 * 1024 * 1024 \
                    and _sha256_of(src) != d.cand.sha256:
                d.action = "observe"
                d.reason += "; 移动前哈希复核不一致 → 观察"
                continue
        except OSError as e:
            d.action = "observe"
            d.reason += f"; 移动前复核失败({e})"
            continue
        dst = cdir / f"{seq:03d}__{_sanitize(src.name)}"
        try:
            cdir.mkdir(parents=True, exist_ok=True)
            _safe_move(src, dst)
        except OSError as e:
            d.action = "observe"
            d.reason += f"; 移动失败(可能被占用): {e}"
            continue
        d.applied = True
        entry = {
            "from": str(src), "to": str(dst),
            "sha256": d.cand.sha256 or _sha256_of(dst), "size": d.cand.size,
        }
        moved.append(entry)
        seq += 1
    if moved:
        manifest = {
            "cycle": cycle_id, "note": "append-only 冷区; 恢复: earthworm restore",
            "items": moved,
        }
        (cdir / "MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return moved


def restore(cycle_id: str) -> list:
    """把冷区一个循环的文件原路送回; 目标已存在则并存为 .restored-*。"""
    cdir = cold_dir(cycle_id)
    mf = cdir / "MANIFEST.json"
    if not mf.is_file():
        raise SystemExit(f"冷区无此循环: {cycle_id} ({mf})")
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    results = []
    for item in manifest.get("items", []):
        src, dst = Path(item["to"]), Path(item["from"])
        if not src.is_file():
            results.append({"from": item["from"], "ok": False, "note": "冷区文件缺失"})
            continue
        try:
            if dst.exists():
                alt = dst.with_name(dst.name + ".restored-" + cycle_id)
                _safe_move(src, alt)
                results.append({"from": item["from"], "ok": True,
                                "note": f"目标已存在, 并存为 {alt.name}"})
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                _safe_move(src, dst)
                results.append({"from": item["from"], "ok": True, "note": "已原路送回"})
        except OSError as e:
            results.append({"from": item["from"], "ok": False, "note": str(e)})
    return results
