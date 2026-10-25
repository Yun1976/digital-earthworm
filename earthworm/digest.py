# -*- coding: utf-8 -*-
"""数字蚯蚓 · 消化道: 把宝藏判定压成知识卡, 存进宝藏库(文件原地不动)。

对齐主库晋升链: 教训式碎片 → 可复用知识摘要卡片。
宝藏库 = <repo>/treasure/YYYY-MM/<日期>-<hash8>.md + INDEX.md 索引。
冷区 append-only 纪律同样适用于宝藏库: 只增不删, 可追溯来源路径。
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import density
from .config import REPO


def treasure_dir() -> Path:
    return REPO / "treasure"


def index_file() -> Path:
    return REPO / "state" / "treasure_index.json"


def load_index() -> dict:
    if index_file().is_file():
        try:
            return json.loads(index_file().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_index(idx: dict) -> None:
    index_file().parent.mkdir(parents=True, exist_ok=True)
    index_file().write_text(json.dumps(idx, ensure_ascii=False, indent=2),
                            encoding="utf-8")


def _safe_slug(name: str) -> str:
    bad = '<>:"/\\|?*'
    base = name.rsplit(".", 1)[0] if "." in name else name
    return "".join(ch if ch not in bad else "_" for ch in base)[:60] or "untitled"


def make_card(cand, kernel_info: dict, cycle_id: str, dry_run: bool) -> Path:
    """为 treasure 判定生成知识卡, 返回卡片路径。"""
    now = dt.datetime.now()
    tdir = treasure_dir() / now.strftime("%Y-%m")
    tdir.mkdir(parents=True, exist_ok=True)
    card = tdir / f"{now:%Y-%m-%d}-{cand.sha256[:8]}.md"

    topics = "、".join(kernel_info.get("topics") or []) or "未标注"
    ent = density.entropy_rate(cand.text_head) if cand.is_text else "n/a"
    points = "\n".join(f"- {p}" for p in (kernel_info.get("key_points") or [])
                       if p.strip()) or "- (内核未给出要点)"
    excerpt = (cand.text_head or "").strip()[:800]
    excerpt_block = f"> {excerpt}".replace("\n", "\n> ") if excerpt else "(无文本摘录)"

    body = f"""---
title: "{_safe_slug(cand.path.rsplit(chr(92), 1)[-1].rsplit('/', 1)[-1])}"
source: "{cand.path}"
sha256: {cand.sha256}
size_bytes: {cand.size}
mtime: {dt.datetime.fromtimestamp(cand.mtime).isoformat(timespec='seconds')}
captured: {now.isoformat(timespec='seconds')}
cycle: {cycle_id}
kernel: {kernel_info.get('model', 'unknown')}
verdict: treasure (conf={kernel_info.get('confidence', 0):.2f})
density: entropy_rate={ent} text_score={cand.text_score}
tags: [数字蚯蚓宝藏, {topics[:60]}]
dry_run: {str(dry_run).lower()}
---

# 宝藏 · {_safe_slug(cand.path.rsplit(chr(92), 1)[-1].rsplit('/', 1)[-1])}

**来源**: `{cand.path}` ｜ **处置**: 原文件保留原地，本卡为消化摘要，未删除任何原文件。

## 内核摘要

{kernel_info.get('summary') or '(无摘要)'}

## 要点

{points}

## 原文摘录(前 800 字)

{excerpt_block}

*由数字蚯蚓循环 {cycle_id} 消化产出。*
"""
    card.write_text(body, encoding="utf-8")

    index_line = (f"- [{card.stem}]({card.relative_to(REPO).as_posix()}) ← "
                  f"`{cand.path}` ({now:%Y-%m-%d}, conf={kernel_info.get('confidence', 0):.2f})\n")
    with open(treasure_dir() / "INDEX.md", "a", encoding="utf-8") as f:
        f.write(index_line)
    return card
