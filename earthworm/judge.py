# -*- coding: utf-8 -*-
"""数字蚯蚓 · 冗余判定(双钥门 + 升级道)。

组合信号, 禁止单特征定生死(方案 §3.3):
  冷置(吃) = 纯规则快车道(强信号类且无密度反常)
             或 规则垃圾票 × 内核垃圾票 双钥一致;
  消化(吐卡) = 内核判 treasure(文件原地不动, 只产出知识卡);
  观察     = 一切分歧/超限/内核不可达/预算耗尽 —— 宁可少吃。
升级道(创始人误伤担忧的主防线): 名字像垃圾但 text_score 高的,
强制内核复核, 密度反常时快车道失效。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from . import density
from .config import Config
from .evolution import pattern_key, precedents_text, load_learned
from .providers import KernelDown
from .scanner import FASTLANE_CATS, Candidate, _sha256_of

HASH_CAP_MB = 64

# 动作: cold=吃进冷区 / digest=消化出卡(文件不动) / observe=观察 / ignore=跳过
ACTIONS = {"cold", "digest", "observe", "ignore"}


@dataclass
class Decision:
    cand: Candidate
    action: str
    reason: str
    kernel: dict = field(default_factory=dict)
    card: str = ""
    applied: bool = False

    def as_dict(self) -> dict:
        return {
            "path": self.cand.path, "sha256": self.cand.sha256,
            "size": self.cand.size, "age_days": self.cand.age_days,
            "category": self.cand.category, "signals": self.cand.signals,
            "rule_weight": self.cand.rule_weight, "text_score": self.cand.text_score,
            "action": self.action, "applied": self.applied,
            "reason": self.reason, "kernel": self.kernel, "card": self.card,
        }


def run(candidates: list, kernel, cfg: Config, treasure_hashes: set,
        corpus_texts: list) -> list:
    decisions: list = []
    budget = cfg.llm_judge_limit
    prec = precedents_text()
    learned = load_learned()

    for c in sorted(candidates, key=lambda x: (-x.rule_weight, x.path)):
        # 台账去重: 同一内容已消化过 → 不重复出卡(消融: 零知识损失)。
        # 冷区不设永久哈希跳过: restore 送回的文件应重新受审。
        if c.sha256 and c.sha256 in treasure_hashes:
            decisions.append(Decision(c, "ignore", "sha256 已在宝藏库(已消化)"))
            continue

        if c.is_text and c.text_score < 0:
            corpus = corpus_texts if len(corpus_texts) < 50 else corpus_texts[:50]
            c.text_score = density.text_score(c.text_head)

        escalate = c.is_text and c.text_score >= cfg.escalate_score
        has_text = c.is_text and bool(c.text_head.strip())
        learned_fast = (pattern_key(c.category, c.signals) in learned
                        and not has_text)  # 习得快车道只对非文本生效
        fast = ((c.category in FASTLANE_CATS or learned_fast) and c.rule_garbage
                and not escalate and not has_text)  # 有字的必须过内核

        if fast:
            if c.size > cfg.max_move_mb * 1024 * 1024:
                decisions.append(Decision(c, "observe",
                                          f"快车道命中但超单文件上限 {cfg.max_move_mb}MB"))
                continue
            decisions.append(Decision(c, "cold",
                                      f"快车道: {c.category} (纯规则强信号, 非文本)"))
            continue

        # ---- 语义道: 需要内核 ----
        if kernel is None:
            decisions.append(Decision(c, "observe", "内核不可达/未启用 → 全局禁食"))
            continue
        if budget <= 0:
            decisions.append(Decision(c, "observe", "本轮内核预算耗尽 → 观察"))
            continue

        meta = {"path": c.path, "ext": c.ext, "size": c.size,
                "age_days": c.age_days, "signals": c.signals}
        if prec:
            meta["precedents"] = prec
        excerpt = c.text_head[:3000] if c.is_text else ""
        try:
            k = kernel.judge(meta, excerpt)
        except KernelDown as e:
            decisions.append(Decision(c, "observe", f"内核故障禁食: {e}"))
            continue
        budget -= 1

        if c.rule_garbage and k["verdict"] == "garbage" \
                and k["confidence"] >= cfg.kernel_conf_floor:
            act = "cold"
            reason = f"双钥一致: 规则({c.category}) × 内核垃圾(conf={k['confidence']:.2f})"
        elif c.rule_garbage:
            act = "observe"
            reason = f"双钥分歧: 规则垃圾但内核={k['verdict']}(conf={k['confidence']:.2f}) → 观察"
        elif k["verdict"] == "treasure":
            act = "digest"
            # 宝藏卡与去重台账都依赖 sha256; 查重没算过的这里补算(≤64MB)
            if not c.sha256 and c.size <= HASH_CAP_MB * 1024 * 1024:
                try:
                    c.sha256 = _sha256_of(Path(c.path))
                except OSError:
                    pass
            reason = f"内核判宝藏(conf={k['confidence']:.2f}) → 消化出卡, 原文件保留"
        elif k["verdict"] == "garbage":
            act = "observe"
            reason = f"内核单票垃圾(conf={k['confidence']:.2f}), 无规则票 → 观察(单票不冷置)"
        else:
            act = "observe"
            reason = f"内核 unknown(conf={k['confidence']:.2f}) → 观察"

        if act == "cold" and c.size > cfg.max_move_mb * 1024 * 1024:
            act = "observe"
            reason += f"; 超单文件上限 {cfg.max_move_mb}MB"
        decisions.append(Decision(c, act, reason, kernel=k))

    return decisions
