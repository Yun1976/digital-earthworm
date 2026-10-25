# -*- coding: utf-8 -*-
"""数字蚯蚓 · 晋升进化机制: 越吃越聪明。

三件事(对齐主库晋升链与 DENSITY-002 诚信协议):
  learn   从台账重算模式统计 → 产出 判例(precedents, 注入内核提示) 与
          习得快车道(learned_fastlane: 仅非文本类, 内核确认率≥95%且样本≥15);
  precedents 每轮判定时把高频判例注入内核提示, 内核裁决有案可援;
  promote 同主题宝藏卡 ≥4 张 → 内核压实成一张聚合卡(碎片→摘要→高密度条目)。
所有进化动作落 state/evolution.jsonl(结构化证据)。
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from .config import REPO

STATS = REPO / "state" / "pattern_stats.json"
LEARNED = REPO / "state" / "learned_fastlane.json"
EVOLUTION = REPO / "state" / "evolution.jsonl"

LEARN_MIN_SAMPLES = 15      # 习得快车道最低样本
LEARN_AGREE_RATE = 0.95     # 习得快车道最低内核确认率
PRECEDENT_TOP_N = 8
PROMOTE_MIN_CARDS = 4       # 聚合晋升最低卡片数


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _log(kind: str, detail: dict) -> None:
    EVOLUTION.parent.mkdir(parents=True, exist_ok=True)
    with open(EVOLUTION, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": _now(), "kind": kind, **detail},
                           ensure_ascii=False) + "\n")


def pattern_key(category: str, signals: list) -> str:
    sig0 = (signals[0].split(":")[0] if signals else "none")
    return f"{category}|{sig0}"


def load_stats() -> dict:
    if STATS.is_file():
        try:
            return json.loads(STATS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def load_learned() -> set:
    if LEARNED.is_file():
        try:
            return set(json.loads(LEARNED.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return set()
    return set()


def learn_from_decisions(decisions_dicts: list) -> dict:
    """把一轮判定增量并入模式统计并重算习得快车道。"""
    stats = load_stats()
    pats = stats.setdefault("patterns", {})
    for d in decisions_dicts:
        if d.get("action") not in ("cold", "observe") or not d.get("signals"):
            continue
        k = pattern_key(d.get("category", "other"), d.get("signals") or [])
        slot = pats.setdefault(k, {"confirm": 0, "disagree": 0})
        if d.get("action") == "cold" and (d.get("kernel") or {}).get("verdict") == "garbage":
            slot["confirm"] += 1
        elif d.get("action") == "cold":
            slot["confirm"] += 1          # 快车道(无内核)也视为确认信号质量
        else:
            slot["disagree"] += 1
    stats["updated"] = _now()
    STATS.parent.mkdir(parents=True, exist_ok=True)
    STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")

    learned = set()
    for k, v in pats.items():
        n = v["confirm"] + v["disagree"]
        if v["confirm"] >= LEARN_MIN_SAMPLES and n > 0 \
                and v["confirm"] / n >= LEARN_AGREE_RATE:
            learned.add(k)
    old = load_learned()
    LEARNED.write_text(json.dumps(sorted(learned), ensure_ascii=False), encoding="utf-8")
    newly = sorted(learned - old)
    _log("learn", {"patterns": len(pats), "learned": sorted(learned),
                   "newly_learned": newly})
    return {"patterns": len(pats), "learned": sorted(learned),
            "newly_learned": newly}


def precedents_text() -> str:
    """高频高确认判例, 注入内核提示(判例法: 越吃越有案可援)。"""
    stats = load_stats()
    pats = stats.get("patterns", {})
    rows = []
    for k, v in pats.items():
        n = v["confirm"] + v["disagree"]
        if v["confirm"] >= 5 and n and v["confirm"] / n >= 0.9:
            rows.append((v["confirm"], f"{k} → 垃圾(确认{v['confirm']}/{n})"))
    if not rows:
        return ""
    rows.sort(reverse=True)
    lines = [t for _, t in rows[:PRECEDENT_TOP_N]]
    return "历史判例(规则信号模式 → 历史结论, 供参考):\n- " + "\n- ".join(lines)


# ---------- promote: 宝藏卡聚合晋升 ----------

_FM_TAG_RE = re.compile(r"^tags:\s*\[(.+)\]", re.M)


def _card_tags(text: str) -> list:
    m = _FM_TAG_RE.search(text)
    if not m:
        return []
    return [t.strip() for t in m.group(1).split(",") if t.strip()]


def cluster_cards(treasure_dir: Path) -> dict:
    """按主题词把宝藏卡聚类(标题不算, 取知识域词)。"""
    clusters: dict = {}
    for card in sorted(treasure_dir.rglob("*.md")):
        if card.name.startswith(("INDEX", "DISTILLED")):
            continue
        try:
            tags = _card_tags(card.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        for t in tags:
            if t in ("数字蚯蚓宝藏",):
                continue
            clusters.setdefault(t, []).append(card)
    return {t: cards for t, cards in clusters.items() if len(cards) >= PROMOTE_MIN_CARDS}


def promote(kernel, treasure_dir: Path) -> list:
    """对每个 ≥4 卡的主题簇, 内核压实为一张聚合卡。返回聚合卡路径列表。"""
    made = []
    for topic, cards in cluster_cards(treasure_dir).items():
        briefs = []
        for c in cards[:12]:
            try:
                head = c.read_text(encoding="utf-8", errors="ignore")[:900]
            except OSError:
                continue
            briefs.append(f"### 卡片: {c.stem}\n{head}")
        if len(briefs) < PROMOTE_MIN_CARDS:
            continue
        prompt = (
            f"以下是数字蚯蚓宝藏库中主题为「{topic}」的 {len(briefs)} 张知识卡片段。\n"
            "请把它们压实成一张更高密度的聚合卡(晋升链: 碎片→摘要→高密度条目):\n"
            "保留跨卡片重复的要点只写一次; 冲突之处明确指出; 保留来源卡索引。\n"
            "直接输出 Markdown 正文(不要代码围栏), 以 '# 宝藏聚合 · " + topic + "' 开头。"
        )
        try:
            raw = kernel._chat(
                "你是数字蚯蚓的知识压实器。只输出 Markdown 正文。",
                prompt + "\n\n" + "\n\n".join(briefs))
        except Exception as e:  # KernelDown/网络
            _log("promote", {"topic": topic, "ok": False, "error": str(e)[:200]})
            continue
        out = treasure_dir / dt.datetime.now().strftime("%Y-%m") \
            / f"DISTILLED-{topic[:30]}.md".replace("/", "_").replace("\\", "_")
        out.parent.mkdir(parents=True, exist_ok=True)
        body = raw.strip().strip("`") + "\n\n---\n### 来源卡\n" + \
            "\n".join(f"- {c.name}" for c in cards[:12])
        out.write_text(
            f"---\ntitle: 宝藏聚合 · {topic}\ncaptured: {_now()}\n"
            f"kind: distilled\ncards: {len(cards)}\n"
            f"tags: [数字蚯蚓宝藏, 数字蚯蚓聚合, {topic[:40]}]\n---\n\n" + body,
            encoding="utf-8")
        with open(treasure_dir / "INDEX.md", "a", encoding="utf-8") as f:
            f.write(f"- [聚合:{topic}]({out.relative_to(REPO).as_posix()}) "
                    f"← 压实 {len(cards)} 张卡 ({_now()})\n")
        _log("promote", {"topic": topic, "ok": True, "cards": len(cards),
                         "out": str(out)})
        made.append(str(out))
    return made
