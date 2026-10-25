# -*- coding: utf-8 -*-
"""数字蚯蚓 · 驱动内核抽象(可插拔大脑)。

  - ollama   本地模型(默认; 现役 qwen3.8:27b, 观自在 192.168.1.2:11434)
  - deepseek DeepSeek API(需环境变量 DEEPSEEK_API_KEY)
  - none     无内核(仅纯规则快车道, 语义道全部禁食)

底线: 内核不可达时全局禁食 —— 智力密度不够就只观察不进食,
宁可少吃, 绝不把宝藏当垃圾消化(创始人 2026-10-25 令)。

网络安全边界: 内核端点只允许 环回/私网地址(本地模型) 与
api.deepseek.com 白名单域; 协议仅 http/https; 其余一律拒绝。
"""
from __future__ import annotations

import ipaddress
import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

VERDICTS = {"garbage", "treasure", "unknown"}

# 公网白名单域(且必须 https); 私网/环回允许 http(本地局域网模型端点)
PUBLIC_HOST_WHITELIST = {"api.deepseek.com"}

SYSTEM_PROMPT = """你是「数字蚯蚓」的消化判官。判断一个文件是垃圾还是宝藏, 拿不准必须给 unknown。
判据(反熵增纪律):
- 垃圾 = 可再生成的中间产物: 日志、缓存、临时文件、构建产物、崩溃转储、下载残留、同一文件的重复副本。删掉不损失任何独有信息。
- 宝藏 = 独有信息: 个人文档、笔记、数据集、配置、成果、纪要、规范。内容承载不可再生的信息。
- 文件名像垃圾但内容密度高的(例如旧日志里藏着独有分析结论), 按内容判为 treasure 或 unknown。
- 二进制文件你只能看到元数据看不到内容, 除非是极高确信的常见垃圾类型(崩溃转储/临时文件), 否则给 unknown。
- confidence 是你对判断的把握, 不是文件的重要性。
只输出一个 JSON 对象, 不要输出任何其他文字:
{"verdict":"garbage|treasure|unknown","confidence":0.0到1.0,"reason":"中文一句话","summary":"中文两句话概括内容与价值","topics":["关键词"],"key_points":["要点1","要点2","要点3"]}"""


class KernelDown(Exception):
    pass


def safe_url(url: str) -> str:
    """内核端点边界校验: 协议白名单 + 私网/环回或公网白名单域。"""
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise KernelDown(f"内核地址协议不允许: {url!r}")
    host = (u.hostname or "").lower()
    if not host:
        raise KernelDown(f"内核地址无主机: {url!r}")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if u.scheme == "https" and host in PUBLIC_HOST_WHITELIST:
            return url
        raise KernelDown(f"内核域名不在白名单: {host!r}")
    if ip.is_private or ip.is_loopback:
        return url
    raise KernelDown(f"内核地址必须为私网/环回: {host!r}")


def _parse_verdict(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no json object")
    obj = json.loads(t[start:end + 1])
    v = str(obj.get("verdict", "")).lower().strip()
    if v not in VERDICTS:
        raise ValueError(f"bad verdict: {v!r}")
    try:
        conf = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return {
        "verdict": v,
        "confidence": max(0.0, min(1.0, conf)),
        "reason": str(obj.get("reason", ""))[:300],
        "summary": str(obj.get("summary", ""))[:600],
        "topics": [str(x)[:40] for x in (obj.get("topics") or [])][:8],
        "key_points": [str(x)[:200] for x in (obj.get("key_points") or [])][:6],
    }


def build_user_message(meta: dict, excerpt: str) -> str:
    sig = ", ".join(meta.get("signals") or []) or "无"
    body = (
        "文件元数据:\n"
        f"- 路径: {meta['path']}\n"
        f"- 类型: {meta.get('ext') or '(无扩展名)'}, 大小: {meta.get('size', 0)} 字节, "
        f"修改距今约 {meta.get('age_days', 0):.0f} 天\n"
        f"- 规则引擎信号: {sig}\n"
    )
    if meta.get("precedents"):
        body += meta["precedents"] + "\n"
    if excerpt:
        body += f"内容摘录(截断):\n<<<\n{excerpt}\n>>>"
    else:
        body += "内容摘录: (二进制或未读取)"
    return body


class BaseKernel:
    name = "base"
    model = ""

    def judge(self, meta: dict, excerpt: str) -> dict:
        msg = build_user_message(meta, excerpt)
        last = None
        for attempt in range(3):
            try:
                raw = self._chat(SYSTEM_PROMPT, msg)
                return _parse_verdict(raw)
            except (ValueError, KeyError, urllib.error.URLError, OSError, TimeoutError) as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise KernelDown(f"{self.name} 裁决三次失败: {last}")

    def _chat(self, system: str, user: str) -> str:  # pragma: no cover
        raise NotImplementedError


class OllamaKernel(BaseKernel):
    name = "ollama"

    def __init__(self, url: str, model_pref: list, model: str = "", timeout: int = 240):
        self.url = safe_url(url).rstrip("/")
        self.timeout = timeout
        req = urllib.request.Request(self.url + "/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=10) as r:
            tags = json.loads(r.read().decode("utf-8"))
        names = [m.get("name", "") for m in tags.get("models", [])]
        if not names:
            raise KernelDown(f"ollama 在线但模型库为空: {self.url}")
        self.model = self._pick(names, model_pref, model)
        if not self.model:
            biggest = max(tags.get("models", []), key=lambda m: m.get("size", 0))
            self.model = biggest.get("name", names[0])

    @staticmethod
    def _pick(names: list, pref: list, model: str) -> str:
        if model:
            for n in names:
                if n == model or n.split(":")[0] == model.split(":")[0]:
                    return n
            return ""
        for p in pref:
            pl = p.lower()
            for n in names:
                if n.lower() == pl:
                    return n
            for n in names:
                if n.lower().split(":")[0] == pl.split(":")[0]:
                    return n
        return ""

    def _chat(self, system: str, user: str) -> str:
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_ctx": 8192},
        }).encode("utf-8")
        req = urllib.request.Request(
            self.url + "/api/chat", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["message"]["content"]


class DeepSeekKernel(BaseKernel):
    name = "deepseek"
    API = "https://api.deepseek.com/chat/completions"

    def __init__(self, model: str = "deepseek-chat", timeout: int = 120):
        self.api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise KernelDown("DEEPSEEK_API_KEY 未设置")
        self.model = model
        self.timeout = timeout
        safe_url(self.API)  # 白名单域常量, 校验不过直接拒绝启动

    def _chat(self, system: str, user: str) -> str:
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 800,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.API, data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


def make_kernel(provider: str, cfg) -> tuple:
    """返回 (kernel|None, 描述)。内核不可达 → (None, 原因), 调用方全局禁食。"""
    if provider == "none":
        return None, "无内核(仅规则快车道, 语义道禁食)"
    if provider == "deepseek":
        try:
            k = DeepSeekKernel(timeout=cfg.llm_timeout)
            return k, f"deepseek:{k.model}"
        except KernelDown as e:
            return None, f"deepseek 不可用: {e}"
    # ollama(默认)
    try:
        k = OllamaKernel(cfg.ollama_url, cfg.model_pref, cfg.model, cfg.llm_timeout)
        return k, f"ollama:{k.model}"
    except (KernelDown, urllib.error.URLError, OSError) as e:
        return None, f"ollama 不可达({cfg.ollama_url}): {e} → 全局禁食降级"
