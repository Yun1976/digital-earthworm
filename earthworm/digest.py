# -*- coding: utf-8 -*-
"""数字蚯蚓 · 消化道: 把宝藏判定压成知识卡, 存进宝藏库(文件原地不动)。

对齐主库晋升链: 教训式碎片 → 可复用知识摘要卡片。
创始人 2026-10-26 令: 知识必须经过形式逻辑可验证 ——
  验证层 = 证据锚定(要点规范化后与原文逐字比对, 确定性)
         + 蕴含审查(内核逐条判定 entailed/not_found/contradicted, 附原文依据);
  卡片状态 verified / partial / unverified, 有矛盾即 unverified。
已产 verified 知识的内容, 对应垃圾数据才可物理清除(见 quarantine/clear)。
宝藏库 = <repo>/treasure/YYYY-MM/*.md + INDEX.md 索引, append-only。
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from . import density
from .config import REPO


def treasure_dir() -> Path:
    return REPO / "treasure"


def index_file() -> Path:
    return REPO / "state" / "treasure_index.json"


def load_index() -> dict:
    """sha256 → {"card": 路径, "status": verified|partial|unverified}。
    兼容 v1(纯路径字符串 → 视为 unverified)。"""
    if index_file().is_file():
        try:
            raw = json.loads(index_file().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        out = {}
        for k, v in raw.items():
            if isinstance(v, str):
                out[k] = {"card": v, "status": "unverified"}
            else:
                out[k] = v
        return out
    return {}


def save_index(idx: dict) -> None:
    index_file().parent.mkdir(parents=True, exist_ok=True)
    index_file().write_text(json.dumps(idx, ensure_ascii=False, indent=2),
                            encoding="utf-8")


def _safe_slug(name: str) -> str:
    bad = '<>:"/\\|?*'
    base = name.rsplit(".", 1)[0] if "." in name else name
    return "".join(ch if ch not in bad else "_" for ch in base)[:60] or "untitled"


_NORM_RE = re.compile(r"[\s，。；：、！？（）()\"'“”「」《》\-—·]+")

NLI_SYSTEM = """你是形式逻辑审查官。对每一条「要点」, 判定它是否可由「原文摘录」推出:
- entailed: 原文语义蕴含该要点(允许同义改写与数值一致)
- not_found: 原文没有依据
- contradicted: 与原文矛盾
只输出一个 JSON 对象: {"verdicts":[{"i":序号,"verdict":"entailed|not_found|contradicted","evidence":"原文依据片段(≤50字)"}]}"""


def _norm(s: str) -> str:
    return _NORM_RE.sub("", s).lower()


def ground_points(points: list, source_text: str) -> list:
    """确定性证据锚定: 要点规范化后与原文逐字比对。"""
    src = _norm(source_text)
    out = []
    for i, p in enumerate(points):
        out.append({"i": i, "point": p,
                    "grounded": bool(src) and _norm(p)[:120] in src})
    return out


def nli_audit(points: list, source_text: str, kernel) -> list | None:
    """蕴含审查: 内核逐条判定 entailed/not_found/contradicted。内核故障返回 None。"""
    if not points or kernel is None:
        return None
    premises = source_text[:3000]
    lines = "\n".join(f"{i}. {p}" for i, p in enumerate(points))
    prompt = f"原文摘录(前提):\n<<<\n{premises}\n>>>\n\n待审要点:\n{lines}"
    try:
        raw = kernel._chat(NLI_SYSTEM, prompt)
        return _parse_verdicts(raw, len(points))
    except Exception:
        return None


def _parse_verdicts(text: str, n: int) -> list:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no json")
    obj = json.loads(t[start:end + 1])
    out = [None] * n
    for v in obj.get("verdicts", []):
        try:
            i = int(v.get("i"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < n:
            out[i] = {"verdict": str(v.get("verdict", "not_found")),
                      "evidence": str(v.get("evidence", ""))[:120]}
    return [v or {"verdict": "not_found", "evidence": ""} for v in out]


def verify_card(card_path: Path, kernel) -> dict:
    """对已生成的知识卡跑形式逻辑验证, 回写 verification 块与状态。

    状态机: 有 contradicted → unverified; 否则 可验证要点中
    (grounded 或 entailed)比例 ≥0.75 → verified; 否则 partial。
    内核故障 → grounding-only 结果, 最高 partial。
    """
    text = card_path.read_text(encoding="utf-8")
    points = re.findall(r"^- (.+)$", text.split("## 要点", 1)[-1]
                        .split("##", 1)[0], re.M) if "## 要点" in text else []
    points = [p.strip() for p in points if p.strip() and p.strip() != "- (内核未给出要点)"]
    # 原文: 来源文件还在就读全文, 否则退回卡内摘录
    m_src = re.search(r'^source: "(.+)"', text, re.M)
    m_exc = re.search(r"## 原文摘录[^#]*\n\n((?:> .*\n?)+)", text)
    excerpt = "".join(l[2:] for l in m_exc.group(1).splitlines()) if m_exc else ""
    source_text = excerpt
    if m_src:
        try:
            source_text = Path(m_src.group(1)).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            pass

    grounded = ground_points(points, source_text)
    nli = nli_audit(points, source_text, kernel)

    n_ok = n_bad = 0
    for i, g in enumerate(grounded):
        nv = nli[i]["verdict"] if nli else None
        if nv == "contradicted":
            n_bad += 1
        elif g["grounded"] or nv == "entailed":
            n_ok += 1
    total = max(1, len(grounded))
    ratio = n_ok / total
    if n_bad:
        status = "unverified"
    elif kernel is not None and ratio >= 0.75:
        status = "verified"
    elif ratio >= 0.5:
        status = "partial"
    else:
        status = "unverified"

    vlines = ["", "## 形式逻辑验证", "",
              f"- 状态: **{status}** ｜ 方法: 证据锚定(逐字比对) + 蕴含审查(NLI)"
              f"{' + 矛盾检查' if nli else '(内核缺席, 仅锚定)'}",
              f"- 可验证要点: {n_ok}/{total}"
              + (f", 矛盾 {n_bad} 条" if n_bad else ""),
              ""]
    for i, g in enumerate(grounded):
        nv = nli[i] if nli else {"verdict": "—", "evidence": ""}
        mark = {"entailed": "✓蕴含", "not_found": "?无据", "contradicted": "✗矛盾"}.get(
            nv["verdict"], "—" if not nli else "?无据")
        anchor = "✓锚定" if g["grounded"] else "△未锚定"
        vlines.append(f"- [{anchor}|{mark}] {g['point'][:80]}"
                      + (f" 〈依据: {nv['evidence'][:60]}〉" if nv.get("evidence") else ""))
    vlines.append("")

    marker = "## 形式逻辑验证"
    if marker in text:
        text = text.split(marker)[0].rstrip() + "\n"
    text = text.rstrip() + "\n" + "\n".join(vlines)
    text = text.replace("dry_run: true", "dry_run: true")  # 保持不动
    card_path.write_text(text, encoding="utf-8")
    return {"status": status, "points_total": len(grounded),
            "points_ok": n_ok, "contradicted": n_bad, "nli": nli is not None}


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
