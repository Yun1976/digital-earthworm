# -*- coding: utf-8 -*-
"""数字蚯蚓 · 沙盒夹具: 造假垃圾与假宝藏, 供断言 harness 使用。

垃圾(应被吃/冷置)与宝藏(绝不能被动)都有确定性内容与统一的旧 mtime。
"""
from __future__ import annotations

import os
import random
import time
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixture" / "workspace"

# 快车道必吃集合(纯规则强信号, 断言为硬断言)
FASTLANE = [
    r"tmp\session.tmp",
    r"cache\crash-2024-02-01.dmp",
    r"cache\__pycache__\util.cpython-311.pyc",
    r"tmp\~$会议纪要.docx",
    r"downloads\photo (1).jpg",      # photo.jpg 的重复副本
    r"downloads\setup-old (1).exe",  # setup-old.exe 的重复副本
    r"downloads\download.part",
    r"tmp\zero.txt",                 # 零字节
]
# 语义道(内核确认类, 断言为软断言)
SEMANTIC = [r"_logs\app-2024-03-01.log"]
# 宝藏(绝不能被动, 原地保留)
TREASURE = [
    r"treasures\四川北路社区营造试点纪要.md",
    r"treasures\肘关节标注规范v2.md",
    r"treasures\cases-summary.csv",
]

OLD = 300  # 全部夹具统一 300 天前(过陈化线)


def _write(p: Path, data: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def build() -> Path:
    rng = random.Random(42)
    if FIXTURE.exists():
        for p in sorted(FIXTURE.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
        FIXTURE.rmdir()
    log_lines = "\n".join(
        f"2024-03-01 10:{i % 60:02d}:{i % 60:02d} INFO worker tick i={i} data=0x{rng.getrandbits(16):04x} status=ok"
        for i in range(400))
    plan = [
        (r"tmp\session.tmp", b"\x00\x01TEMP" + rng.randbytes(1024)),
        (r"cache\crash-2024-02-01.dmp", rng.randbytes(4096)),
        (r"cache\__pycache__\util.cpython-311.pyc", b"\xcb\x0d\x0d\x0a" + rng.randbytes(2048)),
        (r"tmp\~$会议纪要.docx", b"\x00\x01~$" + rng.randbytes(64)),
        (r"tmp\zero.txt", b""),
        # 120KB: 超过 llm_read_max_kb, 保留件不该消耗内核裁决
        (r"downloads\photo.jpg", b"\xff\xd8\xff\xe0" + rng.randbytes(120 * 1024) + b"\xff\xd9"),
        (r"downloads\setup-old.exe", b"MZ" + rng.randbytes(120 * 1024)),
        (r"downloads\download.part", rng.randbytes(1536)),
        (r"_logs\app-2024-03-01.log", log_lines.encode("utf-8")),
        (r"treasures\四川北路社区营造试点纪要.md", TREASURE1.encode("utf-8")),
        (r"treasures\肘关节标注规范v2.md", TREASURE2.encode("utf-8")),
        (r"treasures\cases-summary.csv", CSV.encode("utf-8")),
    ]
    for rel, data in plan:
        _write(FIXTURE / rel, data)
    # 重复副本(与原件字节一致)
    _write(FIXTURE / r"downloads\photo (1).jpg", (FIXTURE / r"downloads\photo.jpg").read_bytes())
    _write(FIXTURE / r"downloads\setup-old (1).exe", (FIXTURE / r"downloads\setup-old.exe").read_bytes())
    # 统一旧 mtime
    old = time.time() - OLD * 86400
    for p in FIXTURE.rglob("*"):
        if p.is_file():
            os.utime(p, (old, old))
    return FIXTURE


TREASURE1 = """# 四川北路社区营造试点纪要(v0)

日期: 2026-10-11 ｜ 主持: 徐航 ｜ 记录: 项目组

## 一、试点定位

以多伦路历史风貌区为载体, 把「声音历史」做成社区营造的公共产品:
居民口述史采集 → 语料归档 → 声音地图 → 街区导览内容。

## 二、三站动线(推荐方案)

1. 公啡书社: 开场与背景展板, 咖啡馆形态降低参与门槛;
2. 内山书店旧址: 世纪之交的左翼文化现场, 承接"声音中的1927-1936"专题;
3. 多伦路街头终端: 二维码触发口述片段, 行人即听众。

## 三、语料与版权边界

- 口述人签署知情同意后入库, 原始录音保留 3 年;
- 街道侧素材(善治资源库)两份文档已归集, MD5 校验一致;
- 试点产出物走 CC BY-NC-SA 4.0。

## 四、下一步

- 2026-11 前: 完成三站内容脚本 v1;
- 2026-12 前: 20 位居民试点访谈, 建立 case ID 索引;
- 2027-01: 评估是否扩展到 8 个居民区。
"""

TREASURE2 = """# 肘关节标注规范 v2(节选)

## 1. 适配范围

本规范覆盖 CT 轴位序列的肘关节结构标注: 肱骨远端、尺骨鹰嘴、桡骨头、
冠突、关节间隙与游离体。RADAR 原方案仅覆盖腹部, 肘关节筛查不直接套用。

## 2. 标注规则

- 游离体直径 ≥3mm 才计入, <3mm 记为可疑;
- 鹰嘴窝与冠突窝的骨性增生按 R0-R3 分级;
- 每例由两名标注员独立完成, 分歧走仲裁流程(仲裁人为高年资)。

## 3. 质量锚点

- 人审锚点集 ≥50 例方可开跑机器预标;
- 预标注与锚点一致率 <80% 时, 冻结词表并回炉规则。
"""

CSV = """case_id,age,sex,laterality,loose_body_mm,olecranon_grade,reviewer,review_date
E001,34,M,left,4.2,R1,r1,2026-09-02
E002,51,F,right,0.0,R0,r2,2026-09-02
E003,27,M,right,6.8,R2,r1,2026-09-03
E004,63,M,left,2.1,R1,r2,2026-09-03
E005,45,F,left,5.5,R3,r1,2026-09-04
E006,38,M,bilateral,3.9,R2,r2,2026-09-05
E007,29,F,right,0.0,R0,r1,2026-09-05
E008,57,M,left,7.4,R2,r2,2026-09-06
E009,41,F,right,1.2,R1,r1,2026-09-06
E010,49,M,left,4.8,R2,r2,2026-09-07
E011,33,F,left,0.0,R0,r1,2026-09-07
E012,60,M,right,8.1,R3,r2,2026-09-08
"""


if __name__ == "__main__":
    print(build())
