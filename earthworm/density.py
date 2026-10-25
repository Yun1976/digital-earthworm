# -*- coding: utf-8 -*-
"""数字蚯蚓 · 信息密度基元(复用主库仪器口径)。

度量定义复用 D:\\AI WORK\\anti-entropy-runtime\\density_meter.py (DENSITY-001):
  entropy_rate = lzma(x)/|x|                     字节/字符, 绝对密度
  novelty      = 1 - |8gram(x) ∩ corpus|/|8gram(x)|  对语料新颖比例
为避免 import 触发 state_layer/state.db 副作用(反熵增运行时只读纪律),
此处按同一定义独立实现, 数值口径一致; P0 仪器接入阶段改为直连只读服务。

text_score 是产品层启发式(非主库理论值): 结构化标记密度 + 信息行占比 +
重复率惩罚, 只用于"名字像垃圾但内容像宝藏"的升级道, 不单独定生死。
"""
from __future__ import annotations

import lzma
import re
from collections import Counter
from pathlib import Path

NGRAM = 8  # 与 density_meter.py 一致


def _lzma_len(b: bytes) -> int:
    return len(lzma.compress(b, preset=6 | lzma.PRESET_EXTREME))


def entropy_rate(text: str) -> float:
    raw = text.encode("utf-8")
    return round(_lzma_len(raw) / max(1, len(raw)), 4)


def _ngrams(text: str, n: int = NGRAM) -> set:
    s = re.sub(r"\s+", "", text)
    return {s[i:i + n] for i in range(0, max(0, len(s) - n + 1))}


def novelty(text: str, corpus_texts) -> float:
    g = _ngrams(text)
    if not g:
        return 0.0
    seen: set = set()
    for c in corpus_texts:
        seen |= _ngrams(c)
    return round(1.0 - len(g & seen) / len(g), 4)


_STRUCT_RE = re.compile(
    r"^#{1,6} |```|^\|.*\|$|https?://|\[\[|\d{4}-\d{2}-\d{2}|^\s*[-*+] ", re.M
)


def text_score(text: str) -> float:
    """0..1 结构化密度启发; <200 字符视为无信息。"""
    if len(text) < 200:
        return 0.0
    kb = max(1.0, len(text) / 1024)
    struct = len(_STRUCT_RE.findall(text))
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return 0.0
    rep = Counter(lines).most_common(1)[0][1] / len(lines)
    struct_density = min(1.0, struct / kb / 8.0)
    info_ratio = min(1.0, len(set(lines)) / len(lines) * 1.2)
    return round(0.4 * info_ratio + 0.3 * struct_density + 0.3 * (1.0 - rep), 3)


def load_corpus(treasure_dir: Path, cap: int = 200) -> list:
    """新颖度语料 = 宝藏库已有卡片(压实后的自有知识)。"""
    texts = []
    if treasure_dir.exists():
        for p in sorted(treasure_dir.rglob("*.md"))[:cap]:
            try:
                texts.append(p.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
    return texts


def profile(text: str, corpus_texts) -> dict:
    return {
        "entropy_rate": entropy_rate(text),
        "novelty": novelty(text, corpus_texts),
        "text_score": text_score(text),
    }
