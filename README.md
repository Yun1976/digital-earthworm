# 数字蚯蚓 (Digital Earthworm)

> 一只住在磁盘里的蚯蚓：**收工时出洞 → 吃掉数据垃圾 → 消化成知识宝藏 → 回洞睡觉**。
> 产品方案（权威定稿）：`G:\obsidian-vault\kb\产品方案\2026-10-25-数字蚯蚓-产品方案.md`（SHA256 ebc2e725…）

本仓库是 **P0-P3 代谢内核 + CLI**（无桌宠壳，壳是 P1）。当前版本 v0.1.0，已完成沙盒验证。

## 快速开始

```bash
# 出洞看一圈(默认 dry-run, 不动任何文件)
python -m earthworm dig --roots "C:\Users\user\AppData\Local\Temp" --min-age-days 3

# 真吃(也只是移进冷区, 一键可回滚)
python -m earthworm dig --roots "C:\Users\user\AppData\Local\Temp" --min-age-days 3 --apply

# 冷区原路送回
python -m earthworm restore --cycle <循环ID>

# 洞口告示板
python -m earthworm status
```

驱动内核（可插拔）：

| provider | 说明 |
|---|---|
| `ollama`（默认） | 本地模型，端点 `192.168.1.2:11434`，自动挑库内最强（现役 qwen3.8:27b） |
| `deepseek` | DeepSeek API，需先 `$env:DEEPSEEK_API_KEY="..."` |
| `none` | 无内核：语义道全部禁食，只有纯规则快车道 |

## 安全铁律（写死在代码里，不是文档建议）

1. **保护名单 > 模型分数**（L-ENTROPY-004/005/006）：硬保护路径连扫描根都不许当；
   `D:\AI WORK` 默认整体软保护，仅 `logs / tmp / tmp-ref / ai-caches / zcode-caches` 开放。
2. **双钥门**：规则引擎判垃圾 **且** 内核判垃圾（conf ≥ 0.6）才进冷区；任何一方分歧 → 观察区，不动文件。内核单票不冷置。
3. **升级道**（防"把有用的当垃圾消化"的主防线）：名字像垃圾但文本密度高（text_score ≥ 0.6）的文件，快车道失效，强制内核按内容裁决；内容看不准一律 unknown → 观察。
4. **内核不可达 → 全局禁食**：智力密度不够就只观察不进食。
5. **永不久删**：`--apply` 也只是移入 append-only 冷区（`state/quarantine/<cycle>/` + MANIFEST 台账）。物理删除命令 v0 不提供。
6. **结构化证据**：每条判定落 `state/ledger.jsonl`，每轮全量快照落 `state/cycles/*.json`（DENSITY-002 诚信协议：JSON 台账是证据，Markdown 报告是转述）。
7. **junction 不穿透**（2026-10-06 事故教训）。

## 判定流水线

```
扫描(剪枝保护名单) → 规则信号(扩展名/重复副本/零字节/陈化…)
  ├─ 快车道: 纯规则强信号 且 非文本(零字节/.tmp/.pyc/崩溃转储/重复副本) → 冷区
  ├─ 语义道: 规则票 × 内核票 双钥一致 → 冷区; 分歧 → 观察
  ├─ 发现道: 内核判宝藏 → 消化出知识卡(treasure/), 原文件原地保留
  └─ 升级道: 垃圾外观 × 高文本密度 → 强制内核复核
```

密度度量复用主库 `anti-entropy-runtime/density_meter.py` 的口径
（lzma 熵率 / 8-gram 新颖度，DENSITY-001），为不触碰 RSI 运行时 state.db，
按同定义独立实现于 `earthworm/density.py`（P0 仪器接入时改为直连只读服务）。

## 目录

```
earthworm/        内核包(config/providers/scanner/judge/digest/quarantine/report/loop)
treasure/         宝藏库(知识卡 + INDEX.md, append-only)
state/            ledger.jsonl 台账 · cycles/ 快照 · quarantine/ 冷区 · treasure_index.json
reports/          每轮代谢报告(md)
sandbox/          沙盒夹具 + 断言 harness (python sandbox/run_test.py)
```

## 与产品方案的阶段对齐

- P0 仪器接入：密度口径已复用；直连 density_meter/bloat_meter 只读服务 = 待办
- P1 桌宠壳（悬浮窗/睡觉出洞动画）：待建（本仓库先跑通代谢内核）
- P2 三域扫描（C 盘 / D 盘 / 标注工作站）：C 盘 TEMP 与 D 盘已可扫；标注工作站
  `E:\elbow-expert` 当前在硬保护名单，需创始人拍板开放受控子路径
- P3 消化宝藏库：已完成（本地宝藏库；与主库同步只做指针，不强制写爆）
- P4 收工触发：v0 = 手动 `dig`（显式收工）；空闲/日历检测与计划任务待建
  （装计划任务前按启动器铁律对表 + 创始人批准）
- P5 开源发行（GitHub → itch.io → Steam）：本仓库即起点，License 待创始人裁定
- P6 VR（Meta Horizon）：远期可选，不阻塞
