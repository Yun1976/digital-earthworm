# -*- coding: utf-8 -*-
"""数字蚯蚓 · 配置与保护名单。

铁律(L-ENTROPY-004/005/006): 保护名单 > 模型分数。
命中硬保护的路径即使显式指定为扫描根也会被拒绝;
命中软保护的路径在扫描期直接剪枝, 根本不进候选, 内核无权覆盖。
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AI_WORK = Path(r"D:\AI WORK")
D_ROOT = Path("D:\\")

# D:\ 整体默认保护(D盘是主战场, 生产/资产目录密集), 仅白名单开放扫描。
# 2026-10-25 创始人令"真实环境从D盘开跑"前实测顶层49项后划定。
D_SCANNABLE = {"tmp", "tmp_lo_temp", "tmp_render", "es-tmp",
               "baidunetdiskdownload", "gs", "gsv"}

# 系统级文件按名硬保护(锁定/系统自建, 吃了无意义且危险)
PROTECTED_FILE_NAMES = {"pagefile.sys", "hiberfil.sys", "swapfile.sys",
                        "dumpstack.log.tmp"}

# D:\AI WORK 整体软保护, 仅下列"天然垃圾向"子目录开放扫描
AI_WORK_SCANNABLE = {"logs", "tmp", "tmp-ref", "ai-caches", "zcode-caches"}

# 硬保护: 永不扫描、永不移动, 显式 --roots 也拒绝(防手滑)
HARD_PROTECT = [
    r"C:\Windows",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\ProgramData",
    r"C:\Users\user\.ssh",
    r"C:\Users\user\.zcode",
    r"C:\Users\user\.ollama",
    r"E:\elbow-expert",   # 标注工作站生产数据(P2 再开受控子路径)
    r"D:\livetalking",
    # C4 器官 / 反熵增仪器 / 秘密 / 模型库 / 备份(只读, 绝不吃)
    r"D:\AI WORK\anti-entropy-runtime",
    r"D:\AI WORK\entropy-transfer",
    r"D:\AI WORK\secrets",
    r"D:\AI WORK\backups",
    r"D:\AI WORK\blobs",
    r"D:\AI WORK\manifests",
    r"D:\AI WORK\manifests-v2",
    r"D:\AI WORK\.pnpm-store",
    r"D:\AI WORK\mihomo",
    r"D:\AI WORK\scripts",
    r"D:\AI WORK\tools",
]

# 软保护: 默认剪枝; 以仓库内部为扫描根(沙盒)时放行
SOFT_PROTECT = [str(REPO), str(AI_WORK)]


def _norm(p: str | Path) -> str:
    return str(p).lower().rstrip(os.sep)


def is_protected(p: str | Path, roots=()) -> bool:
    """判定路径是否受保护。roots=本次显式授权的扫描根。"""
    sl = _norm(p)
    if Path(str(p)).name.lower() in PROTECTED_FILE_NAMES:
        return True
    for h in HARD_PROTECT:
        hl = _norm(h)
        if sl == hl or sl.startswith(hl + os.sep):
            return True
    repo_l = _norm(REPO)
    if sl == repo_l or sl.startswith(repo_l + os.sep):
        for r in roots:
            rl = _norm(Path(r).resolve())
            if rl == repo_l or rl.startswith(repo_l + os.sep):
                return False  # 沙盒: 显式以仓库内部为根
        return True
    aw_l = _norm(AI_WORK)
    if sl == aw_l or sl.startswith(aw_l + os.sep):
        try:
            rel = Path(str(p)).relative_to(AI_WORK)
        except ValueError:
            return True
        return not (rel.parts and rel.parts[0].lower() in AI_WORK_SCANNABLE)
    d_l = _norm(D_ROOT)
    if sl == d_l or sl.startswith(d_l + os.sep):
        try:
            rel = Path(str(p)).relative_to(D_ROOT)
        except ValueError:
            return True
        if not rel.parts:
            return False  # D:\ 本身(逐个子项再判)
        if len(rel.parts) == 1:
            return False  # 盘根散文件(如 tmp-eco-master.md)交规则/内核判
        return rel.parts[0].lower() not in D_SCANNABLE
    return False


def is_reparse(p: Path) -> bool:
    """junction/符号链接不穿透(教训 2026-10-06: junction 穿透事故)。"""
    try:
        st = p.stat(follow_symlinks=False)
    except OSError:
        return True
    fa = getattr(st, "st_file_attributes", 0)
    return bool(fa & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)) or os.path.islink(p)


@dataclass
class Config:
    roots: list = field(default_factory=list)
    apply: bool = False                 # False=dry-run(默认), 只看不动
    provider: str = "ollama"            # ollama | deepseek | none
    model: str = ""                     # 空=按偏好序自动挑
    ollama_url: str = "http://192.168.1.2:11434"
    model_pref: list = field(default_factory=lambda: [
        "qwen3.8:27b", "qwen3.6:latest", "gemma4:26b", "gemma4:12b",
        "qwen3.8:27b-mtp-q4_K_M",
    ])
    llm_timeout: int = 240
    llm_judge_limit: int = 40           # 单轮内核裁决次数上限(控时控费)
    llm_read_max_kb: int = 96           # 送内核/密度分析的文本读取上限
    min_age_days: float = 7.0           # 候选最低陈化(太新的不碰)
    log_age_days: float = 90.0          # 无日期名 .log 的垃圾判定陈化线
    max_move_mb: float = 200.0          # 单文件冷置上限
    limit_files: int = 50000            # 单轮扫描文件数上限
    max_depth: int = 8
    escalate_score: float = 0.60        # 文本密度≥此值 → 强制内核复核(升级道)
    kernel_conf_floor: float = 0.60     # 内核垃圾票生效最低置信度


def filter_roots(roots: list) -> tuple[list, list]:
    """拆分扫描根: (可扫描, 被硬保护拒绝)。"""
    ok, rejected = [], []
    for r in roots:
        rp = Path(r).resolve()
        sl = _norm(rp)
        hard = any(sl == _norm(h) or sl.startswith(_norm(h) + os.sep) for h in HARD_PROTECT)
        (rejected if hard else ok).append(str(rp))
    return ok, rejected
