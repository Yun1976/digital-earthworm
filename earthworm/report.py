# -*- coding: utf-8 -*-
"""数字蚯蚓 · 代谢报告(给人看的转述, 证据在 state/ 的 JSON 台账)。"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from .config import REPO

WORM = r"""
      ~°~  ~°~
   .--------.
  ( ~(~3~)~ )   数字蚯蚓 出洞·进食·消化·回洞
   '---\/---'   钻过土壤, 留下养分
      ~~~~
"""


def human(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.1f}{unit}" if unit != "B" else f"{int(f)}B"
        f /= 1024
    return f"{f:.1f}TB"


def write_report(summary: dict) -> Path:
    now = dt.datetime.now()
    rdir = REPO / "reports"
    rdir.mkdir(parents=True, exist_ok=True)
    path = rdir / f"{now:%Y-%m-%d}-{summary['cycle']}.md"

    sc = summary["scan"]
    act = summary["actions"]
    mode = summary["mode"]
    lines = [WORM, "",
             f"# 数字蚯蚓 · 代谢报告 {summary['cycle']}",
             "",
             f"- 时间: {summary['ts']} ｜ 模式: **{'已执行(冷区)' if mode == 'apply' else 'DRY-RUN(未动任何文件)'}**",
             f"- 内核: {summary['kernel']} ｜ 耗时: {summary['elapsed_s']}s",
             f"- 扫描根: {', '.join(summary['roots']) or '(无)'}",
             f"- 见过文件 {sc['total_seen']} / 计入 {sc['total_files']} ({human(sc['total_bytes'])}) / "
             f"候选 {sc['candidates']} / 重复副本 {sc['dupes']} / 占用跳过 {sc['skipped']}",
             f"- 判定: 吃 {act['cold']} ｜ 消化出卡 {act['digest']} ｜ 观察 {act['observe']} ｜ 跳过 {act['ignore']}",
             ""]

    cold = [d for d in summary["decisions"] if d["action"] == "cold"]
    if cold:
        title = "吃了什么(已移入冷区, 可一键恢复)" if mode == "apply" \
            else "拟吃清单(DRY-RUN, 未移动)"
        lines += [f"## {title}", "",
                  "| 文件 | 大小 | 依据 |", "|---|---|---|"]
        for d in cold:
            size = f"{human(d['size'])}" + (" ✅已冷置" if d.get("applied") else "")
            lines.append(f"| `{d['path']}` | {size} | {d['reason']} |")
        moved_bytes = sum(d["size"] for d in cold if d.get("applied"))
        if mode == "apply":
            lines += ["", f"**进冷区: {len([d for d in cold if d.get('applied')])} 项, "
                          f"{human(moved_bytes)}。恢复: `python -m earthworm restore --cycle {summary['cycle']}`**"]
        lines.append("")

    dig = [d for d in summary["decisions"] if d["action"] == "digest"]
    if dig:
        lines += ["## 消化出了什么宝藏(原文件原地保留)", "",
                  "| 知识卡 | 来源 | 内核摘要 |", "|---|---|---|"]
        for d in dig:
            s = (d.get("kernel") or {}).get("summary", "")
            card = d["card"] or "(dry-run 摘要卡已写入宝藏库)"
            lines.append(f"| `{card}` | `{d['path']}` | {s[:80]} |")
        lines.append("")

    obs = [d for d in summary["decisions"] if d["action"] == "observe"]
    if obs:
        lines += ["## 观察区(分歧/超限/禁食, 未动)", "",
                  "| 文件 | 原因 |", "|---|---|"]
        for d in obs[:40]:
            lines.append(f"| `{d['path']}` | {d['reason']} |")
        if len(obs) > 40:
            lines.append(f"| … | 其余 {len(obs) - 40} 项见 JSON 台账 |")
        lines.append("")

    if summary["rejected_roots"]:
        lines += ["## 被硬保护拒绝的扫描根", "",
                  f"`{', '.join(summary['rejected_roots'])}`", ""]

    lines += ["---",
              "*证据链: state/ledger.jsonl(逐条判定) + state/cycles/*.json(全量快照) + "
              "state/quarantine/<cycle>/MANIFEST.json(冷置台账)。本报告为转述, 与台账冲突时以台账为准。*"]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
