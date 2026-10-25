# -*- coding: utf-8 -*-
"""数字蚯蚓 · 桌宠壳(Pet Shell, 方案 §3.3 模块1)。

独立运行的桌面悬浮小蚯蚓:
  平时  洞里睡觉(Zzz), 几乎不打扰;
  收工  每日 20:30(可配)自动出洞吃一轮; 点它也能手动出洞;
  进食  调 python -m earthworm dig(代谢内核独立进程), 动画+进度;
  报告  吃完冒泡报数, 点「报告」打开最新代谢报告 md。
启动: pythonw pet.py(无黑窗) ｜ 安装: pythonw pet.py --install(开机自启)
退出: 右键蚯蚓 → 退出。卸载: pythonw pet.py --uninstall
"""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent
ROOTS_FILE = REPO / "state" / "daily-roots.txt"
DIG_TIME = "20:30"          # 收工触发窗口(v0 固定, P4 做空闲检测)
MIN_AGE_DAYS = "30"         # 常驻自动进食的保守陈化线
LLM_LIMIT = "10"

DEFAULT_ROOTS = "\n".join([
    r"C:\Users\user\AppData\Local\Temp",
    r"D:\tmp",
    r"D:\AI WORK\logs",
    r"D:\AI WORK\tmp",
    r"D:\AI WORK\tmp-ref",
    r"D:\AI WORK\ai-caches",
    r"D:\AI WORK\zcode-caches",
]) + "\n"


def ensure_roots_file() -> None:
    ROOTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not ROOTS_FILE.is_file():
        ROOTS_FILE.write_text(DEFAULT_ROOTS, encoding="utf-8")


def latest_report() -> Path | None:
    rdir = REPO / "reports"
    if not rdir.is_dir():
        return None
    files = sorted(rdir.glob("*.md"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


class Pet:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("数字蚯蚓")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"170x150+{sw - 220}+{sh - 260}")
        self.cv = tk.Canvas(self.root, width=170, height=150,
                            bg="white", highlightthickness=0)
        self.cv.pack()
        self.cv.create_rectangle(15, 118, 155, 138, fill="#6b4f2a", outline="")  # 土壤
        self.cv.create_oval(55, 108, 115, 132, fill="#2b1d0e", outline="")       # 洞口
        self.segs = [self.cv.create_oval(0, 0, 0, 0, fill="#e58aa0", outline="#b0566e")
                     for _ in range(5)]
        self.eyes = [self.cv.create_oval(0, 0, 0, 0, fill="white", outline=""),
                     self.cv.create_oval(0, 0, 0, 0, fill="black", outline="")]
        self.bubble = self.cv.create_text(85, 26, text="Zzz", font=("宋体", 11),
                                          fill="#444", width=150)
        self.state = "sleep"          # sleep|dig|done
        self.tick = 0
        self.q: queue = queue.Queue()
        self.proc = None
        self.last_run_day = ""
        self.cv.tag_bind("all", "<Button-1>", self._on_click)
        self.cv.tag_bind("all", "<Button-3>", self._on_menu)
        self.cv.bind("<Button-3>", self._on_menu)
        self._menu = tk.Menu(self.root, tearoff=0)
        self._menu.add_command(label="立即出洞·吃(进冷区, 可回滚)", command=self.dig)
        self._menu.add_command(label="巡逻·只看不吃(dry-run)",
                               command=lambda: self.dig(apply=False))
        self._menu.add_command(label="打开最新代谢报告", command=self.open_report)
        self._menu.add_separator()
        self._menu.add_command(label="退出", command=self.root.destroy)
        self._drag = None
        self._hb_ts = ""
        self.cv.bind("<ButtonPress-1>", self._drag_start, add="+")
        self.cv.bind("<B1-Motion>", self._drag_move, add="+")
        self.root.after(400, self._animate)
        self.root.after(3000, self._poll_hb)
        self.root.after(2000, self._check_schedule)

    def _poll_hb(self) -> None:
        """心跳监听: 任何人触发的代谢都让蚯蚓醒来表态。"""
        try:
            hb = json.loads((REPO / "state" / "heartbeat.json").read_text(encoding="utf-8"))
            ts = hb.get("ts", "")
            if ts and ts != self._hb_ts:
                self._hb_ts = ts
                if hb.get("phase") == "dig":
                    self.state = "dig"
                    self._say("有人喂我了, 出洞进食中…")
                elif hb.get("phase") == "done":
                    self.state = "done"
                    self._say(f"吃饱回洞✅ 吃{hb.get('cold', '?')}·消化{hb.get('digest', '?')}"
                              f"·观察{hb.get('observe', '?')}\n(点击看报告)")
                    self.root.after(60000, self._back_to_sleep)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        self.root.after(3000, self._poll_hb)

    # ---------- 外观 ----------
    def _draw(self) -> None:
        t = self.tick
        out = t % 14 < 7 if self.state == "dig" else (t % 40 < 20)
        base_y = 96 if (self.state != "sleep" and out) else 116   # 出洞/缩洞
        wig = [0, 2, -2, 3, -3] if self.state == "dig" else [0, 0, 0, 0, 0]
        if self.state == "dig":
            wig = [(w * (1 if (t // 3) % 2 == 0 else -1)) for w in wig]
        xs = [92, 78, 64, 52, 42]
        rs = [13, 12, 11, 10, 9]
        for i, (s, x, r, w) in enumerate(zip(self.segs, xs, rs, wig)):
            y = base_y + i * 3 + w
            self.cv.coords(s, x - r, y - r, x + r, y + r)
        self.cv.coords(self.eyes[0], 94, base_y - 6, 100, base_y)
        self.cv.coords(self.eyes[1], 96, base_y - 4, 99, base_y - 1)

    def _say(self, text: str) -> None:
        self.cv.itemconfigure(self.bubble, text=text)

    def _animate(self) -> None:
        self.tick += 1
        self._draw()
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "say":
                    self._say(payload)
                elif kind == "state":
                    self.state = payload
        except queue.Empty:
            pass
        self.root.after(120, self._animate)

    # ---------- 代谢 ----------
    def dig(self, apply: bool = True) -> None:
        if self.state == "dig":
            return
        ensure_roots_file()
        self.last_run_day = datetime.now().strftime("%Y%m%d")
        self.q.put(("state", "dig"))
        self._say("出洞觅食…")
        cmd = [sys.executable, "-m", "earthworm", "dig",
               "--roots-file", str(ROOTS_FILE),
               "--min-age-days", MIN_AGE_DAYS, "--llm-limit", LLM_LIMIT]
        if apply:
            cmd.append("--apply")

        def work() -> None:
            try:
                p = subprocess.run(cmd, cwd=str(REPO), capture_output=True,
                                   text=True, encoding="utf-8", errors="replace",
                                   timeout=7200,
                                   env=None)
                out = p.stdout or ""
                cold = digest_n = obs = "?"
                for line in out.splitlines():
                    if line.startswith("      判定:"):
                        try:
                            parts = line.split("判定:")[1].split("/")
                            cold, digest_n, obs = (x.strip().split(" ")[0] for x in parts[:3])
                        except Exception:
                            pass
                if p.returncode == 0:
                    self.q.put(("state", "done"))
                    self.q.put(("say", f"吃饱回洞✅ 吃{cold}·消化{digest_n}·观察{obs}\n(点击看报告, 60秒后睡觉)"))
                    self.root.after(60000, self._back_to_sleep)
                else:
                    self.q.put(("state", "done"))
                    self.q.put(("say", "出洞失败⚠\n看控制台/报告"))
                    self.root.after(60000, self._back_to_sleep)
            except Exception as e:  # subprocess 层故障
                self.q.put(("state", "done"))
                self.q.put(("say", f"出洞异常: {str(e)[:60]}"))
                self.root.after(60000, self._back_to_sleep)

        threading.Thread(target=work, daemon=True).start()

    def _back_to_sleep(self) -> None:
        if self.state != "dig":
            self.state = "sleep"
            self._say("Zzz")

    def _check_schedule(self) -> None:
        now = datetime.now()
        if (self.state != "dig"
                and now.strftime("%H:%M") >= DIG_TIME
                and self.last_run_day != now.strftime("%Y%m%d")):
            self.dig(apply=True)
        self.root.after(30000, self._check_schedule)

    # ---------- 交互 ----------
    def open_report(self) -> None:
        rp = latest_report()
        if rp:
            import os
            os.startfile(str(rp))  # noqa: S606

    def _on_click(self, _e) -> None:
        if self.state == "done":
            self.open_report()

    def _on_menu(self, e) -> None:
        try:
            self._menu.tk_popup(e.x_root, e.y_root)
        finally:
            self._menu.grab_release()

    def _drag_start(self, e) -> None:
        self._drag = (e.x, e.y)

    def _drag_move(self, e) -> None:
        if self._drag:
            x = self.root.winfo_x() + e.x - self._drag[0]
            y = self.root.winfo_y() + e.y - self._drag[1]
            self.root.geometry(f"+{x}+{y}")

    def run(self) -> None:
        self._say("Zzz")
        self.root.mainloop()


def install() -> None:
    import winreg
    cmd = f'pyw.exe -3 "{REPO / "pet.py"}"'
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                         winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, "DigitalEarthworm", 0, winreg.REG_SZ, cmd)
    winreg.CloseKey(key)
    print(f"已注册开机自启(HKCU Run): {cmd}")


def uninstall() -> None:
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                             winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, "DigitalEarthworm")
        winreg.CloseKey(key)
        print("已移除开机自启")
    except FileNotFoundError:
        print("本来就没有自启项")


if __name__ == "__main__":
    if "--install" in sys.argv:
        install()
    elif "--uninstall" in sys.argv:
        uninstall()
    else:
        Pet().run()
