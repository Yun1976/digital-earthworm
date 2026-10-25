# -*- coding: utf-8 -*-
"""数字蚯蚓 · 扫描器: 出洞嗅探膨胀物。

输出候选清单(路径/大小/年龄/类型/规则信号), 不做裁决。
铁律: 保护名单剪枝在扫描期完成; junction 不穿透; 只读。
查重在"全量文件宇宙"上做: 保留件往往没有任何信号(不是候选),
但副本必须与它配对才能被安全吃掉。
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import time
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .config import Config, is_protected, is_reparse

# 纯规则强信号扩展名(可再生成的中间产物)
EXT_CATEGORY = {
    ".tmp": "tmp", ".temp": "tmp",
    ".pyc": "pyc", ".pyo": "pyc", ".class": "pyc", ".o": "pyc", ".obj": "pyc",
    ".dmp": "dmp", ".hdmp": "dmp", ".mdmp": "dmp",
    ".crdownload": "partial", ".part": "partial", ".partial": "partial",
    ".bak": "bak", ".old": "bak", ".orig": "bak", ".rej": "bak",
    ".swp": "swap", ".swo": "swap",
    ".etl": "etl", ".cache": "cache",
}
CATEGORY_WEIGHT = {
    "tmp": 5, "pyc": 4, "dmp": 5, "partial": 5, "swap": 4, "etl": 4,
    "bak": 3, "cache": 3, "zero": 5, "lock": 5, "dupe": 5, "copy": 4,
    "log": 3, "junk_dir": 2, "version": 3,
}
FASTLANE_CATS = {"zero", "lock", "tmp", "pyc", "dmp", "partial", "dupe"}
JUNK_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                  "crashdumps", "crash_reports"}
COPY_RE = re.compile(r"[（(]\d+[）)](\.\w+)?$")
COPY_HINTS = (" - 副本", " - copy", "(copy)", "_backup", ".backup")
LOG_DATE_RE = re.compile(r"\d{4}[-_]?\d{2}[-_]?\d{2}")
# 版本链后缀: v1/v12、终版、日历版、定稿、final、old、bak…
VERSION_SUFFIX_RE = re.compile(
    r"(?:[-_ \.]?(?:v\d+|终版|最终版|定稿|定版|final|日历版|修订版|新版|老版|旧版|旧|备份|bak\d*|old\d*|draft\d*|草稿\d*))+",
    re.IGNORECASE)
OFFICE_TEXT_EXTS = {".xlsx", ".xlsm", ".docx"}
HASH_CAP_MB = 64          # 查重单文件大小上限
HASH_BUDGET_MB = 512      # 单轮查重总字节预算


@dataclass
class Candidate:
    path: str
    size: int
    mtime: float
    age_days: float
    ext: str
    category: str = "other"
    signals: list = field(default_factory=list)
    rule_garbage: bool = False
    rule_weight: int = 0
    is_text: bool = False
    text_head: str = ""
    sha256: str = ""
    text_score: float = -1.0  # -1 = 未计算

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScanResult:
    candidates: list
    total_files: int = 0
    total_bytes: int = 0
    total_seen: int = 0
    skipped: int = 0
    dupes: int = 0
    version_chain: int = 0
    node_modules: list = field(default_factory=list)
    report_only: list = field(default_factory=list)   # _MEI* 等运行中程序目录: 只报不动
    truncated: bool = False


def _signals_for(fp: Path, size: int, rel_parts: tuple, age_days: float,
                 cfg: Config) -> tuple:
    """返回 (category, signals, weight)。禁止单特征定生死: 弱信号需组合。"""
    name = fp.name
    ext = fp.suffix.lower()
    signals: list = []
    weights: list = []
    cat_final = [""]

    def add(cat: str, sig: str) -> None:
        signals.append(sig)
        weights.append(CATEGORY_WEIGHT.get(cat, 1))
        if not cat_final[0] or CATEGORY_WEIGHT.get(cat, 1) > CATEGORY_WEIGHT.get(cat_final[0], 1):
            cat_final[0] = cat

    if size == 0:
        add("zero", "zero_byte")
    if name.startswith("~$"):
        add("lock", "office_lock_artifact(~$)")
    if ext in EXT_CATEGORY:
        add(EXT_CATEGORY[ext], f"ext:{ext}")
    if ext == ".log":
        stale = age_days >= cfg.log_age_days
        dated = bool(LOG_DATE_RE.search(name))
        if dated or stale:
            add("log", "rotated_log" if dated else f"stale_log({age_days:.0f}d)")
    if COPY_RE.search(name):
        add("copy", "copy_suffix(n)")
    elif any(h in name.lower() for h in COPY_HINTS):
        add("copy", "copy_name_hint")
    if any(p.lower() in JUNK_DIR_NAMES for p in rel_parts[:-1]):
        add("junk_dir", "junk_dir")
    if not cat_final[0]:
        cat_final[0] = "other"
    return cat_final[0], signals, sum(weights)


def _office_text(fp: Path, max_bytes: int) -> str:
    """xlsx/docx = zip+xml; 抽共享字符串/正文文本喂内核(读得到内容的office)。"""
    try:
        with zipfile.ZipFile(fp) as z:
            names = z.namelist()
            chunks = []
            for cand in ("xl/sharedStrings.xml", "word/document.xml"):
                if cand in names:
                    raw = z.read(cand)[:max_bytes]
                    chunks.append(re.sub(r"<[^>]+>", " ", raw.decode("utf-8", "ignore")))
            text = re.sub(r"\s+", " ", " ".join(chunks)).strip()
            return text[:max_bytes]
    except (OSError, zipfile.BadZipFile, KeyError):
        return ""


def _read_head(fp: Path, max_bytes: int) -> tuple:
    """返回 (is_text, head)。office 走文本抽取; NUL/乱码率高视为二进制。"""
    if fp.suffix.lower() in OFFICE_TEXT_EXTS:
        t = _office_text(fp, max_bytes)
        return (bool(t), t)
    try:
        raw = fp.read_bytes()[:max_bytes]
    except OSError:
        return False, ""
    if b"\x00" in raw[:2048]:
        return False, ""
    text = raw.decode("utf-8", errors="replace")
    if len(text) > 200 and text.count("\ufffd") / len(text) > 0.2:
        return False, ""
    return True, text


def _has_copy_marker(path: str) -> bool:
    name = Path(path).name.lower()
    return bool(COPY_RE.search(name) or any(h in name for h in COPY_HINTS))


def _sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def mark_dupes(universe: list) -> int:
    """全量宇宙上按尺寸分组 → 哈希确认重复。

    保留件优先序: 无副本标记 → 更老 → 更短路径; 副本打 dupe 信号
    (重量 5, rule_garbage)。只读, 不动文件。
    """
    by_size: dict = {}
    for c in universe:
        if c.size > 0 and c.size <= HASH_CAP_MB * 1024 * 1024:
            by_size.setdefault(c.size, []).append(c)
    budget = HASH_BUDGET_MB * 1024 * 1024
    dupes = 0
    for size, group in by_size.items():
        if len(group) < 2:
            continue
        hashes: dict = {}
        for c in sorted(group, key=lambda x: (_has_copy_marker(x.path), x.mtime,
                                              len(x.path), x.path)):
            if budget <= 0:
                break
            try:
                c.sha256 = _sha256_of(Path(c.path))
            except OSError:
                continue
            budget -= size
            if c.sha256 in hashes:
                keeper = hashes[c.sha256]
                c.signals.append(f"duplicate_of:{keeper.path}")
                # 哈希同一是零知识损失的物理事实, 类别强制归 dupe(名字信号保留在 signals)
                c.category = "dupe"
                c.rule_weight += CATEGORY_WEIGHT["dupe"]
                c.rule_garbage = True
                dupes += 1
            else:
                hashes[c.sha256] = c
    return dupes


def mark_version_chains(universe: list) -> int:
    """版本链: 同目录同名干 + 版本后缀(v2/终版/日历版/final…) ≥3 个成链。

    保留件优先: 终版/final > 最高版本号 > 最新 mtime; 其余标记
    superseded_by(类别 version, 重量 3, 走内核确认道)。只读。
    """
    groups: dict = {}
    for c in universe:
        stem = Path(c.path).stem
        m = VERSION_SUFFIX_RE.search(stem)
        if not m or m.end() < len(stem):
            continue  # 后缀必须贴尾
        base = VERSION_SUFFIX_RE.sub("", stem).strip("-_ .")
        if not base:
            continue
        key = (str(Path(c.path).parent).lower(), base.lower(), Path(c.path).suffix.lower())
        groups.setdefault(key, []).append(c)
    marked = 0
    for grp in groups.values():
        if len(grp) < 3:
            continue  # ≥3 才成链, 避免误伤"原件+一个重命名"

        def rank(c: Candidate) -> tuple:
            stem = Path(c.path).stem
            is_final = 1 if re.search(r"终版|最终|final", stem, re.I) else 0
            vn = re.search(r"v(\d+)", stem, re.I)
            return (is_final, int(vn.group(1)) if vn else -1, c.mtime)

        keeper = max(grp, key=rank)
        for c in grp:
            if c is keeper or c.category == "dupe":
                continue
            c.signals.append(f"superseded_by:{keeper.path}")
            if c.category in ("", "other"):
                c.category = "version"
            c.rule_weight += 3
            c.rule_garbage = True
            marked += 1
    return marked


def scan(roots: list, cfg: Config) -> ScanResult:
    now = time.time()
    res = ScanResult(candidates=[])
    universe: list = []
    stop = False
    for root in roots:
        rootp = Path(root)
        for cur, dirs, files in os.walk(rootp, followlinks=False):
            depth = len(Path(cur).relative_to(rootp).parts)
            keep = []
            for d in sorted(dirs):
                full = Path(cur) / d
                if is_reparse(full):
                    continue
                if is_protected(str(full), roots):
                    continue
                if d.lower() == "node_modules":
                    res.node_modules.append(str(full))
                    continue
                if d.upper().startswith("_MEI"):
                    # PyInstaller 运行时解包目录: 程序可能在用, 只报不动
                    res.report_only.append(str(full))
                    continue
                if depth + 1 > cfg.max_depth:
                    continue
                keep.append(d)
            dirs[:] = keep
            for f in sorted(files):
                res.total_seen += 1
                if res.total_seen > cfg.limit_files:
                    res.truncated = True
                    stop = True
                    dirs[:] = []
                    break
                fp = Path(cur) / f
                try:
                    stt = fp.stat()
                    if stat.S_ISDIR(stt.st_mode):
                        continue
                except OSError:
                    res.skipped += 1
                    continue
                if is_protected(str(fp), roots):
                    res.total_files += 1
                    res.total_bytes += stt.st_size
                    continue
                res.total_files += 1
                res.total_bytes += stt.st_size
                age = max(0.0, (now - stt.st_mtime) / 86400.0)
                rel = tuple(Path(cur).relative_to(rootp).parts) + (f,)
                cat, sigs, weight = _signals_for(fp, stt.st_size, rel, age, cfg)
                universe.append(Candidate(
                    path=str(fp), size=stt.st_size, mtime=stt.st_mtime,
                    age_days=round(age, 2), ext=fp.suffix.lower(),
                    category=cat, signals=sigs,
                    rule_garbage=(cat != "other" and weight >= 3),
                    rule_weight=weight,
                ))
            if stop:
                break
        if stop:
            break
    res.dupes = mark_dupes(universe)
    res.version_chain = mark_version_chains(universe)
    # 候选集: 有规则信号的 + 被查重标记的 + 小散件(交内核发现道)。
    # 陈化线只挡普通候选; 副本冗余与新旧无关, 豁免。
    for c in universe:
        if c.rule_weight >= 2 or c.category == "dupe":
            cands_ok = c.age_days >= cfg.min_age_days or c.category == "dupe"
        elif c.category != "other":
            cands_ok = c.age_days >= cfg.min_age_days
        elif c.size <= cfg.llm_read_max_kb * 1024:
            cands_ok = c.age_days >= cfg.min_age_days
        else:
            cands_ok = False
        if cands_ok:
            res.candidates.append(c)
    for c in res.candidates:
        if c.size <= cfg.llm_read_max_kb * 1024:
            c.is_text, c.text_head = _read_head(Path(c.path), cfg.llm_read_max_kb * 1024)
    return res
