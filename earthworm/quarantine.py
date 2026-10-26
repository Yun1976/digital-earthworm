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

from .config import COLD_ROOT


def cold_dir(cycle_id: str) -> Path:
    return COLD_ROOT / cycle_id


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
            "category": d.cand.category, "signals": d.cand.signals,
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


def clearance_ledger() -> Path:
    return COLD_ROOT / "clearance.jsonl"


def plan_clearance(idx: dict) -> tuple:
    """清除资格审计(dry-run 数据)。三条依据, 全部是"信息零损失"可证明类:
      a) verified_card  内容已被形式逻辑验证的知识卡覆盖(创始人 2026-10-26 令);
      b) keeper_intact  版本链保留件/哈希重复原件完好无损地留在原位。
    返回 (合格清单, 可回收字节)。"""
    eligible: list = []
    if not COLD_ROOT.is_dir():
        return eligible, 0
    for cdir in sorted(COLD_ROOT.iterdir()):
        mf = cdir / "MANIFEST.json"
        if not mf.is_file():
            continue
        try:
            manifest = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in manifest.get("items", []):
            if item.get("cleared"):
                continue
            basis = None
            ent = idx.get(item.get("sha256", ""))
            if isinstance(ent, dict) and ent.get("status") == "verified":
                basis = f"verified_card:{ent.get('card', '')}"
            else:
                for s in item.get("signals") or []:
                    if s.startswith(("superseded_by:", "duplicate_of:")):
                        keeper = s.split(":", 1)[1]
                        if Path(keeper).is_file():
                            basis = f"keeper_intact:{keeper}"
                        break
            if basis:
                eligible.append({"cycle": cdir.name, "item": item, "basis": basis})
    return eligible, sum(e["item"].get("size", 0) for e in eligible)


def clear_apply(eligible: list) -> list:
    """物理清除 + append-only 清除台账(结构化证据)。"""
    import datetime as dt
    led = clearance_ledger()
    done = []
    for e in eligible:
        item = e["item"]
        src = Path(item["to"])
        if not src.is_file():
            alt = COLD_ROOT / e["cycle"] / src.name
            src = alt if alt.is_file() else None
        if src is None:
            continue
        try:
            src.unlink()
        except OSError:
            continue
        rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"),
               "cycle": e["cycle"], "from": item["from"],
               "sha256": item.get("sha256", ""), "size": item.get("size", 0),
               "basis": e["basis"]}
        done.append(rec)
        with open(led, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    # 回写受影响循环的 MANIFEST cleared 标记(历史保留, 只加标记)
    cleared_keys = {(r["cycle"], r["from"]) for r in done}
    for cyc in sorted({c for c, _ in cleared_keys}):
        mf = COLD_ROOT / cyc / "MANIFEST.json"
        try:
            manifest = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        changed = False
        for i in manifest.get("items", []):
            if (cyc, i.get("from")) in cleared_keys and not i.get("cleared"):
                i["cleared"] = True
                changed = True
        if changed:
            mf.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    return done


def restore(cycle_id: str) -> list:
    """把冷区一个循环的文件原路送回; 目标已存在则并存为 .restored-*。"""
    cdir = cold_dir(cycle_id)
    mf = cdir / "MANIFEST.json"
    if not mf.is_file():
        raise SystemExit(f"冷区无此循环: {cycle_id} ({mf})")
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    results = []
    for item in manifest.get("items", []):
        src = Path(item["to"])
        if not src.is_file():
            # 冷区整体搬迁后的回退解析: 清单同目录同名(NNN__name 扁平命名保证唯一)
            alt = mf.parent / src.name
            if alt.is_file():
                src = alt
        if not src.is_file():
            results.append({"from": item["from"], "ok": False, "note": "冷区文件缺失"})
            continue
        dst = Path(item["from"])
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
