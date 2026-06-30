"""
社交媒体监控 GUI 启动器
一键运行所有采集脚本，并发送到飞书
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, font as tkfont

# ── 高 DPI 支持 ──────────────────────────────────────────
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(2)  # PerMonitorV2
except Exception:
    try:
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

# ── 路径 ──────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _find_python():
    if not getattr(sys, 'frozen', False):
        return sys.executable
    try:
        r = subprocess.run(["where", "python"], capture_output=True, text=True, timeout=5)
        if r.stdout:
            for c in [p.strip() for p in r.stdout.strip().split("\n") if p.strip()]:
                if "python" in c.lower() and c.lower().endswith(".exe"):
                    return c
    except Exception:
        pass
    for fb in [
        r"C:\Users\YQSL\AppData\Local\Programs\Python\Python312\python.exe",
        "python",
    ]:
        try:
            r = subprocess.run([fb, "--version"], capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and "Python" in r.stdout:
                return fb
        except Exception:
            pass
    return "python"


PYTHON = _find_python()

# ── 样式常量 ──────────────────────────────────────────────
BG = "#f0f2f5"
CARD_BG = "#ffffff"
PRIMARY = "#1a73e8"
PRIMARY_HOVER = "#1557b0"
SUCCESS = "#34a853"
DANGER = "#ea4335"
TEXT = "#202124"
TEXT_SECONDARY = "#5f6368"
BORDER = "#dadce0"
FONT = ("Microsoft YaHei UI", 10)
FONT_SM = ("Microsoft YaHei UI", 9)
FONT_MONO = ("Cascadia Code", 10, "normal") if os.name == "nt" else ("Menlo", 10)


class HoverButton(ttk.Button):
    """带 hover 颜色的按钮（通过 style 实现）。"""

    def __init__(self, master=None, **kw):
        super().__init__(master, style="Accent.TButton", **kw)


class SocialMonitorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("社交媒体监控工具")
        self.root.geometry("860x720")
        self.root.minsize(680, 560)
        self.root.configure(bg=BG)

        self.script_dir = BASE_DIR
        self.urls_file = os.path.join(self.script_dir, "urls.txt")
        self.process = None

        self._setup_styles()
        self._build_ui()
        self._center_window()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", font=FONT, background=BG, foreground=TEXT)

        # LabelFrame
        style.configure("Card.TLabelframe", background=CARD_BG, relief="solid", borderwidth=1,
                        bordercolor=BORDER)
        style.configure("Card.TLabelframe.Label", background=CARD_BG, foreground=TEXT,
                        font=("Microsoft YaHei UI", 11, "bold"))

        # 按钮
        style.configure("Accent.TButton", background=PRIMARY, foreground="white",
                        borderwidth=0, focusthickness=0, focuscolor="none",
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Accent.TButton",
                  background=[("active", PRIMARY_HOVER), ("disabled", "#ccc")])

        style.configure("Danger.TButton", background=DANGER, foreground="white",
                        borderwidth=0, focusthickness=0, focuscolor="none",
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Danger.TButton",
                  background=[("active", "#c62828"), ("disabled", "#ccc")])

        style.configure("Outline.TButton", background=CARD_BG, foreground=TEXT,
                        borderwidth=1, focusthickness=0, focuscolor="none",
                        font=("Microsoft YaHei UI", 9))
        style.map("Outline.TButton",
                  background=[("active", "#e8f0fe")])

        # Combobox
        style.configure("TCombobox", fieldbackground=CARD_BG, foreground=TEXT,
                        arrowcolor=PRIMARY, bordercolor=BORDER, borderwidth=1)
        style.map("TCombobox", fieldbackground=[("readonly", CARD_BG)])

        # Spinbox
        style.configure("TSpinbox", fieldbackground=CARD_BG, foreground=TEXT,
                        bordercolor=BORDER, borderwidth=1)

        # Checkbutton
        style.configure("TCheckbutton", background=CARD_BG, foreground=TEXT)

        # Entry
        style.configure("TEntry", fieldbackground=CARD_BG, foreground=TEXT,
                        bordercolor=BORDER, borderwidth=1)

        # Label
        style.configure("TLabel", background=CARD_BG, foreground=TEXT)
        style.configure("Hint.TLabel", background=CARD_BG, foreground=TEXT_SECONDARY,
                        font=FONT_SM)

        # StatusBar
        style.configure("StatusBar.TLabel", background="#e8eaed", foreground=TEXT,
                        font=FONT_SM, relief="sunken", padding=(8, 3))

        # Separator
        style.configure("TSeparator", background=BORDER)

    def _center_window(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def _card(self, parent, text, **kw):
        """创建卡片容器。"""
        f = ttk.LabelFrame(parent, text=text, style="Card.TLabelframe", **kw)
        f.pack(fill="x", padx=16, pady=(8, 0))
        # 内部 padding
        inner = ttk.Frame(f, style="Card.TLabelframe")
        inner.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        return inner

    def _row(self, parent, col_ct=4):
        """创建等宽列容器。"""
        for c in range(col_ct):
            parent.columnconfigure(c, weight=1)
        return parent

    def _build_ui(self):
        outer = ttk.Frame(self.root, style="TFrame")
        outer.pack(fill="both", expand=True, padx=0, pady=0)

        # ── 标题栏 ──
        header = tk.Frame(outer, bg=PRIMARY, height=56)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="📊 社交媒体监控", bg=PRIMARY, fg="white",
                 font=("Microsoft YaHei UI", 16, "bold")).pack(side="left", padx=20, pady=12)
        tk.Label(header, text="一键采集 · 自动推送飞书", bg=PRIMARY, fg="#c5d9f7",
                 font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(4, 0), pady=12)

        body = ttk.Frame(outer, style="TFrame")
        body.pack(fill="both", expand=True, padx=0, pady=0)

        # ── 配置卡片 ──
        cfg = self._card(body, "⚙️ 任务配置")

        # 第1行：脚本 + 数量
        r1 = ttk.Frame(cfg, style="Card.TLabelframe")
        r1.pack(fill="x", pady=(6, 0))
        ttk.Label(r1, text="采集脚本").pack(side="left", padx=(0, 8))
        self.script_var = tk.StringVar(value="competitor_monitor  (竞品监控)")
        self.script_combo = ttk.Combobox(r1, textvariable=self.script_var,
                                          state="readonly", width=36, values=[
                    "competitor_monitor  (竞品监控)",
                    "weibo_scraper  (微博账号内容)",
                    "xiaohongshu_scraper  (小红书账号内容)",
                    "weibo_hot_search  (微博热搜)",
                ])
        self.script_combo.pack(side="left", padx=(0, 24))
        self.script_combo.bind("<<ComboboxSelected>>", self._on_script_change)

        ttk.Label(r1, text="采集数量").pack(side="left", padx=(0, 6))
        self.limit_var = tk.StringVar(value="5")
        ttk.Spinbox(r1, from_=1, to=50, textvariable=self.limit_var,
                     width=6).pack(side="left")

        # 第2行：URL
        r2 = ttk.Frame(cfg, style="Card.TLabelframe")
        r2.pack(fill="x", pady=(6, 0))
        ttk.Label(r2, text="URL/文件源").pack(side="left", padx=(0, 8))
        self.url_entry = ttk.Entry(r2)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(r2, text="📂 浏览", style="Outline.TButton",
                   command=self._pick_urls_file, width=8).pack(side="left")

        # 提示
        self.url_hint = ttk.Label(cfg, text="", style="Hint.TLabel")
        self.url_hint.pack(fill="x", pady=(2, 0))
        self._on_script_change()

        # 第3行：选项（用 Frame 包成一行）
        r3 = ttk.Frame(cfg, style="Card.TLabelframe")
        r3.pack(fill="x", pady=(8, 0))

        self.no_content_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(r3, text="不获取正文", variable=self.no_content_var,
                         style="TCheckbutton").pack(side="left", padx=(0, 16))

        self.no_comment_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(r3, text="不获取评论", variable=self.no_comment_var,
                         style="TCheckbutton").pack(side="left", padx=(0, 16))

        self.visible_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(r3, text="显示浏览器", variable=self.visible_var,
                         style="TCheckbutton").pack(side="left", padx=(0, 16))

        self.feishu_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="发送到飞书", variable=self.feishu_var,
                         style="TCheckbutton").pack(side="left", padx=(0, 16))

        self.agent_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="发送到 AI Agent", variable=self.agent_var,
                         style="TCheckbutton").pack(side="left", padx=(0, 16))

        # ── 按钮行 ──
        btn_frame = ttk.Frame(body, style="TFrame")
        btn_frame.pack(fill="x", padx=16, pady=(12, 4))

        self.run_btn = ttk.Button(btn_frame, text="▶  开始采集",
                                   style="Accent.TButton",
                                   command=self._run_script, width=14)
        self.run_btn.pack(side="left", padx=(0, 8))

        self.stop_btn = ttk.Button(btn_frame, text="■  停止",
                                    style="Danger.TButton",
                                    command=self._stop_script, state="disabled", width=10)
        self.stop_btn.pack(side="left", padx=(0, 8))

        self.clear_btn = ttk.Button(btn_frame, text="清空输出",
                                     style="Outline.TButton",
                                     command=self._clear_output, width=10)
        self.clear_btn.pack(side="left")

        # ── 输出卡片 ──
        out_card = self._card(body, "📋 运行日志")
        out_card.pack(fill="both", expand=True, pady=(8, 16))

        text_frame = ttk.Frame(out_card, style="Card.TLabelframe")
        text_frame.pack(fill="both", expand=True)

        self.output = tk.Text(
            text_frame, wrap=tk.WORD,
            font=("Cascadia Code", 10) if os.name == "nt" else ("Menlo", 10),
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white",
            state="disabled", relief="flat", borderwidth=0,
            padx=12, pady=8,
        )
        self.output.pack(fill="both", expand=True)

        # 滚动条
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.output.yview)
        scroll.pack(side="right", fill="y")
        self.output.configure(yscrollcommand=scroll.set)

        # ── 状态栏 ──
        self.status_var = tk.StringVar(value="就绪 — 选择脚本后点击「开始采集」")
        status_bar = ttk.Label(outer, textvariable=self.status_var,
                                style="StatusBar.TLabel")
        status_bar.pack(fill="x", side="bottom")

    # ── 方法 ──

    def _on_script_change(self, event=None):
        s = self._get_key()
        hints = {
            "competitor_monitor": "💡 从 urls.txt 读取竞品 URL，也可点击「浏览」选择其他文件",
            "weibo_scraper": "💡 默认为元气森林微博，可在上方输入其他账号主页 URL",
            "xiaohongshu_scraper": "💡 默认为元气森林小红书，可在上方输入其他账号主页 URL",
            "weibo_hot_search": "💡 热搜采集无需填写 URL",
        }
        self.url_hint.config(text=hints.get(s, ""))
        self.url_entry.config(state="disabled" if s == "weibo_hot_search" else "normal")

    def _get_key(self):
        raw = self.script_var.get()
        return raw.split("  ")[0] if "  " in raw else raw

    def _pick_urls_file(self):
        from tkinter import filedialog
        p = filedialog.askopenfilename(title="选择 URL 文件",
                                        filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
                                        initialdir=self.script_dir)
        if p:
            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, p)

    def _log(self, text, color=None):
        self.output.config(state="normal")
        if color:
            self.output.tag_configure(color, foreground=color,
                                       font=("Cascadia Code", 10))
            self.output.insert(tk.END, text + "\n", color)
        else:
            self.output.insert(tk.END, text + "\n")
        self.output.see(tk.END)
        self.output.config(state="disabled")
        self.root.update_idletasks()

    def _clear_output(self):
        self.output.config(state="normal")
        self.output.delete("1.0", tk.END)
        self.output.config(state="disabled")

    def _run_script(self):
        s = self._get_key()
        limit = self.limit_var.get()
        visible = self.visible_var.get()
        nc = self.no_content_var.get()
        ncmt = self.no_comment_var.get()
        to_fs = self.feishu_var.get()
        to_agent = self.agent_var.get()
        url = self.url_entry.get().strip()

        self._clear_output()
        self.run_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set("⏳ 运行中...")

        def work():
            try:
                self._log(f"▶ 开始执行: {s}", "cyan")
                self._log(f"   采集数量: {limit}  |  评论: {'关' if ncmt else '开'}  |  正文: {'关' if nc else '开'}", "cyan")
                self._log("")

                cmd = [PYTHON, os.path.join(self.script_dir, "scripts", f"{s}.py")]

                if s == "competitor_monitor":
                    cmd += ["-f", url if url else self.urls_file]
                elif s == "weibo_scraper":
                    if url:
                        cmd += ["--url", url]
                    cmd += ["--max-comments", "10"]
                    if not ncmt:
                        cmd.append("--comments")
                elif s == "xiaohongshu_scraper":
                    if url:
                        cmd += ["--url", url]
                    if nc:
                        cmd.append("--no-content")
                    if ncmt:
                        cmd.append("--no-comments")
                    cmd += ["--max-comments", "10"]
                elif s == "weibo_hot_search":
                    cmd += ["--top-posts", "3",
                            "--top-comments", "5" if not ncmt else "0"]

                cmd += ["--limit", limit]

                if visible:
                    cmd.append("--visible")

                tmp = tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", suffix=".json",
                    delete=False, dir=self.script_dir, prefix="_gui_")
                tmp_path = tmp.name
                tmp.close()
                cmd += ["-o", tmp_path]

                self._log("$ " + " ".join(cmd), "green")

                # 强制子进程 Python 使用 UTF-8 输出
                env = os.environ.copy()
                env["PYTHONUTF8"] = "1"

                self.process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd=self.script_dir, env=env,
                )

                for raw_line in iter(self.process.stderr.readline, b""):
                    if not raw_line:
                        break
                    self._log(raw_line.decode("utf-8", errors="replace").rstrip())
                self.process.wait()

                if self.process.returncode != 0:
                    self._log(f"\n✗ 脚本异常退出 ({self.process.returncode})", "red")
                    self.status_var.set("❌ 执行失败")
                    return

                self._log("\n✓ 采集完成", "green")

                if to_fs:
                    self._log("  正在发送到飞书...", "yellow")
                    ncmd = [PYTHON,
                            os.path.join(self.script_dir, "notify", "notify_feishu.py"),
                            "-i", tmp_path]
                    np = subprocess.Popen(
                        ncmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        cwd=self.script_dir, env=env,
                    )
                    no, ne = np.communicate()
                    for ln in (ne.decode("utf-8", errors="replace") or "").split("\n"):
                        if ln.strip():
                            self._log("  " + ln.strip())
                    if np.returncode == 0:
                        self._log("✅ 已发送到飞书群", "green")
                    else:
                        self._log("❌ 飞书发送失败", "red")

                if to_agent:
                    self._log("  正在发送到 AI Agent...", "yellow")
                    acmd = [PYTHON,
                            os.path.join(self.script_dir, "notify", "notify_agent.py"),
                            "-i", tmp_path]
                    ap = subprocess.Popen(
                        acmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        cwd=self.script_dir, env=env,
                    )
                    _, ae = ap.communicate()
                    for ln in (ae.decode("utf-8", errors="replace") or "").split("\n"):
                        if ln.strip():
                            self._log("  " + ln.strip())
                    if ap.returncode == 0:
                        self._log("✅ 已发送到 AI Agent", "green")
                    else:
                        self._log("❌ Agent 发送失败", "red")

                self.status_var.set("✅ 完成")

            except Exception as e:
                self._log(f"\n✗ 异常: {e}", "red")
                self.status_var.set("❌ 出错")
            finally:
                self.root.after(0, self._enable)

        threading.Thread(target=work, daemon=True).start()

    def _enable(self):
        self.run_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def _stop_script(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self._log("■ 已终止", "red")
            self.status_var.set("■ 已终止")
        self._enable()


if __name__ == "__main__":
    root = tk.Tk()
    app = SocialMonitorGUI(root)
    root.mainloop()
