"""
社交媒体监控 GUI 启动器 — Tab 布局版
支持热搜、关键词搜索、账号监控三大功能
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ── 内置品牌账号映射 ────────────────────────────────────
BRAND_ACCOUNTS = {
    "weibo": {
        "元气森林": "genkiforest",
    },
    "xiaohongshu": {
        "元气森林": "27247124186",
        "麦当劳": "5bed337c3619b00001f56cdd",
    },
}
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

# ── 路径 ──────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))  # 用户数据目录（.env, urls.txt）
    BUNDLE_DIR = sys._MEIPASS  # 打包数据目录（scripts/, notify/, keywords.json）
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = BASE_DIR


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
FONT_MONO = ("Cascadia Code", 10)


class SocialMonitorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("社交媒体监控工具")
        self.root.geometry("900x780")
        self.root.minsize(720, 620)
        self.root.configure(bg=BG)

        self.script_dir = BUNDLE_DIR  # 脚本文件目录（scripts/, notify/）
        self.urls_file = os.path.join(BASE_DIR, "urls.txt")
        self.keywords_file = os.path.join(BUNDLE_DIR, "keywords.json")

        self.tab_processes = {}
        self.tab_logs = {}

        self._setup_styles()
        self._build_ui()
        self._center_window()
        self._load_notify_config()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", font=FONT, background=BG, foreground=TEXT)
        style.configure("Card.TLabelframe", background=CARD_BG, relief="solid", borderwidth=1, bordercolor=BORDER)
        style.configure("Card.TLabelframe.Label", background=CARD_BG, foreground=TEXT, font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Accent.TButton", background=PRIMARY, foreground="white", borderwidth=0, focusthickness=0, focuscolor="none", font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", PRIMARY_HOVER), ("disabled", "#ccc")])
        style.configure("Danger.TButton", background=DANGER, foreground="white", borderwidth=0, focusthickness=0, focuscolor="none", font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Danger.TButton", background=[("active", "#c62828"), ("disabled", "#ccc")])
        style.configure("Outline.TButton", background=CARD_BG, foreground=TEXT, borderwidth=1, focusthickness=0, focuscolor="none", font=FONT_SM)
        style.map("Outline.TButton", background=[("active", "#e8f0fe")])
        style.configure("TCombobox", fieldbackground=CARD_BG, foreground=TEXT, arrowcolor=PRIMARY, bordercolor=BORDER, borderwidth=1)
        style.map("TCombobox", fieldbackground=[("readonly", CARD_BG)])
        style.configure("TSpinbox", fieldbackground=CARD_BG, foreground=TEXT, bordercolor=BORDER, borderwidth=1)
        style.configure("TCheckbutton", background=CARD_BG, foreground=TEXT)
        style.configure("TEntry", fieldbackground=CARD_BG, foreground=TEXT, bordercolor=BORDER, borderwidth=1)
        style.configure("TLabel", background=CARD_BG, foreground=TEXT)
        style.configure("Hint.TLabel", background=CARD_BG, foreground=TEXT_SECONDARY, font=FONT_SM)
        style.configure("StatusBar.TLabel", background="#e8eaed", foreground=TEXT, font=FONT_SM, relief="sunken", padding=(8, 3))
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background="#e8eaed", foreground=TEXT, padding=(16, 4), font=("Microsoft YaHei UI", 10))
        style.map("TNotebook.Tab", background=[("selected", CARD_BG)], foreground=[("selected", PRIMARY)])

    def _center_window(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def _card_frame(self, parent, text, **kw):
        f = ttk.LabelFrame(parent, text=text, style="Card.TLabelframe", **kw)
        f.pack(fill="x", padx=8, pady=(6, 0))
        inner = ttk.Frame(f, style="Card.TLabelframe")
        inner.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        return inner

    def _tab_frame(self, notebook, tab_name):
        f = ttk.Frame(notebook, style="TFrame")
        notebook.add(f, text=tab_name)
        return f

    def _make_log_area(self, parent, tab_name):
        text_frame = ttk.Frame(parent, style="TFrame")
        text_frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        text = tk.Text(
            text_frame, wrap=tk.WORD,
            font=FONT_MONO if os.name == "nt" else ("Menlo", 10),
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white",
            state="disabled", relief="flat", borderwidth=0,
            padx=12, pady=8,
        )
        text.pack(fill="both", expand=True, side="left")

        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=text.yview)
        scroll.pack(side="right", fill="y")
        text.configure(yscrollcommand=scroll.set)

        self.tab_logs[tab_name] = text
        return text

    def _log(self, tab_name, text, color=None):
        w = self.tab_logs.get(tab_name)
        if not w:
            return
        ts = time.strftime("%H:%M:%S")
        w.config(state="normal")
        if color:
            w.tag_configure(color, foreground=color, font=FONT_MONO)
            w.insert(tk.END, f"[{ts}] {text}\n", color)
        else:
            w.insert(tk.END, f"[{ts}] {text}\n")
        w.see(tk.END)
        w.config(state="disabled")
        self.root.update_idletasks()

    def _clear_log(self, tab_name):
        w = self.tab_logs.get(tab_name)
        if w:
            w.config(state="normal")
            w.delete("1.0", tk.END)
            w.config(state="disabled")

    # ── UI 构建 ───────────────────────────────────────────

    def _build_ui(self):
        outer = ttk.Frame(self.root, style="TFrame")
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=PRIMARY, height=56)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="📊 社交媒体监控", bg=PRIMARY, fg="white",
                 font=("Microsoft YaHei UI", 16, "bold")).pack(side="left", padx=20, pady=12)
        tk.Label(header, text="一键采集 · 自动推送飞书", bg=PRIMARY, fg="#c5d9f7",
                 font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(4, 0), pady=12)

        nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        self._build_tab_hot(nb)
        self._build_tab_keyword(nb)
        self._build_tab_account(nb)
        self._build_tab_schedule(nb)
        self._build_tab_notify(nb)

        nb.bind("<<NotebookTabChanged>>", self._on_tab_change)
        self.notebook = nb

        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(outer, textvariable=self.status_var, style="StatusBar.TLabel")
        status_bar.pack(fill="x", side="bottom")

    # ── 通知配置 ──────────────────────────────────────────

    def _notify_env_path(self):
        return os.path.join(BASE_DIR, ".env")

    def _load_notify_config(self):
        path = self._notify_env_path()
        if not os.path.isfile(path):
            return
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip()
                if k.strip() == "FEISHU_WEBHOOK":
                    self.fs_webhook_var.set(v)
                elif k.strip() == "AGENT_URL":
                    self.ag_url_var.set(v)
                elif k.strip() == "AGENT_SENDER":
                    self.ag_sender_var.set(v)
                elif k.strip() == "AGENT_CHAT":
                    self.ag_chat_var.set(v)

    def _save_notify_config(self):
        path = self._notify_env_path()
        kv = {
            "FEISHU_WEBHOOK": self.fs_webhook_var.get(),
            "AGENT_URL": self.ag_url_var.get(),
            "AGENT_SENDER": self.ag_sender_var.get(),
            "AGENT_CHAT": self.ag_chat_var.get(),
        }
        lines = [
            "# 飞书通知",
            f"FEISHU_WEBHOOK={kv['FEISHU_WEBHOOK']}",
            "",
            "# AI Agent",
            f"AGENT_URL={kv['AGENT_URL']}",
            f"AGENT_SENDER={kv['AGENT_SENDER']}",
            f"AGENT_CHAT={kv['AGENT_CHAT']}",
        ]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self.status_var.set("✅ 配置已保存")
        messagebox.showinfo("保存成功", "配置已保存到 .env 文件\n下次打开会自动加载")

    # ── Tab: 🔥 热搜 ──────────────────────────────────────

    def _build_tab_hot(self, nb):
        f = self._tab_frame(nb, "🔥 热搜")
        cfg = self._card_frame(f, "采集配置")

        r1 = ttk.Frame(cfg, style="Card.TLabelframe")
        r1.pack(fill="x", pady=(4, 0))
        ttk.Label(r1, text="采集平台:").pack(side="left", padx=(0, 8))
        self.hot_platform = tk.StringVar(value="merged")
        for val, txt in [("weibo_hot", "微博热搜"), ("weibo_ent", "微博文娱"),
                          ("douyin", "抖音热榜"), ("merged", "合并模式")]:
            ttk.Radiobutton(r1, text=txt, variable=self.hot_platform,
                            value=val).pack(side="left", padx=(0, 12))

        r2 = ttk.Frame(cfg, style="Card.TLabelframe")
        r2.pack(fill="x", pady=(6, 0))
        ttk.Label(r2, text="采集数量:").pack(side="left", padx=(0, 8))
        self.hot_limit = tk.StringVar(value="15")
        ttk.Spinbox(r2, from_=1, to=50, textvariable=self.hot_limit, width=6).pack(side="left", padx=(0, 24))
        self.hot_visible = tk.BooleanVar(value=False)
        ttk.Checkbutton(r2, text="显示浏览器", variable=self.hot_visible).pack(side="left", padx=(0, 16))

        r3 = ttk.Frame(cfg, style="Card.TLabelframe")
        r3.pack(fill="x", pady=(6, 8))
        self.hot_fs = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="发送到飞书", variable=self.hot_fs).pack(side="left", padx=(0, 12))
        self.hot_agent = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="发送到 AI Agent", variable=self.hot_agent).pack(side="left")

        btnf = ttk.Frame(f, style="TFrame")
        btnf.pack(fill="x", padx=8, pady=(4, 0))
        self.hot_run_btn = ttk.Button(btnf, text="▶  开始采集", style="Accent.TButton",
                                      command=lambda: self._run_hot(), width=14)
        self.hot_run_btn.pack(side="left", padx=(0, 8))
        self.hot_stop_btn = ttk.Button(btnf, text="■  停止", style="Danger.TButton",
                                       command=lambda: self._stop_tab("hot"), state="disabled", width=10)
        self.hot_stop_btn.pack(side="left")

        self._make_log_area(f, "hot")

    # ── Tab: 🔍 关键词搜索 ────────────────────────────────

    def _build_tab_keyword(self, nb):
        f = self._tab_frame(nb, "🔍 关键词搜索")
        cfg = self._card_frame(f, "搜索配置")

        self.kw_product = tk.StringVar(value="")
        self.kw_checkboxes = {}

        r1 = ttk.Frame(cfg, style="Card.TLabelframe")
        r1.pack(fill="x", pady=(4, 0))
        ttk.Label(r1, text="产品线:").pack(side="left", padx=(0, 8))
        self.kw_product_combo = ttk.Combobox(r1, textvariable=self.kw_product,
                                              state="readonly", width=14)
        self.kw_product_combo.pack(side="left", padx=(0, 8))
        self.kw_product_combo.bind("<<ComboboxSelected>>", self._on_product_change)
        self.kw_select_all_btn = ttk.Button(r1, text="取消全选", style="Outline.TButton",
                                            command=self._toggle_all_kw, width=12)
        self.kw_select_all_btn.pack(side="right", padx=(4, 0))

        self.kw_frame = ttk.Frame(cfg, style="Card.TLabelframe")
        self.kw_frame.pack(fill="x", pady=(6, 0))

        r_add = ttk.Frame(cfg, style="Card.TLabelframe")
        r_add.pack(fill="x", pady=(4, 0))
        ttk.Label(r_add, text="自定义关键词:").pack(side="left", padx=(0, 6))
        self.kw_custom_entry = ttk.Entry(r_add, width=20)
        self.kw_custom_entry.pack(side="left", padx=(0, 6))
        ttk.Button(r_add, text="+ 添加", style="Outline.TButton",
                   command=self._add_custom_keyword, width=8).pack(side="left")

        r2 = ttk.Frame(cfg, style="Card.TLabelframe")
        r2.pack(fill="x", pady=(6, 0))
        self.kw_weibo = tk.BooleanVar(value=True)
        ttk.Checkbutton(r2, text="微博", variable=self.kw_weibo).pack(side="left", padx=(0, 12))
        self.kw_xhs = tk.BooleanVar(value=True)
        ttk.Checkbutton(r2, text="小红书", variable=self.kw_xhs).pack(side="left", padx=(0, 24))
        self.kw_visible = tk.BooleanVar(value=False)
        ttk.Checkbutton(r2, text="显示浏览器", variable=self.kw_visible).pack(side="left", padx=(0, 16))
        ttk.Label(r2, text="每个关键词:").pack(side="left", padx=(0, 4))
        self.kw_per = tk.StringVar(value="5")
        ttk.Spinbox(r2, from_=1, to=20, textvariable=self.kw_per, width=5).pack(side="left", padx=(0, 4))
        ttk.Label(r2, text="条  ").pack(side="left")

        r3 = ttk.Frame(cfg, style="Card.TLabelframe")
        r3.pack(fill="x", pady=(6, 8))
        self.kw_fs = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="发送到飞书", variable=self.kw_fs).pack(side="left", padx=(0, 12))
        self.kw_agent = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="发送到 AI Agent", variable=self.kw_agent).pack(side="left")

        btnf = ttk.Frame(f, style="TFrame")
        btnf.pack(fill="x", padx=8, pady=(4, 0))
        self.kw_run_btn = ttk.Button(btnf, text="▶  开始搜索", style="Accent.TButton",
                                     command=lambda: self._run_keyword(), width=14)
        self.kw_run_btn.pack(side="left", padx=(0, 8))
        self.kw_stop_btn = ttk.Button(btnf, text="■  停止", style="Danger.TButton",
                                      command=lambda: self._stop_tab("keyword"), state="disabled", width=10)
        self.kw_stop_btn.pack(side="left")

        self._make_log_area(f, "keyword")
        self._load_keywords()

    def _load_keywords(self):
        try:
            with open(self.keywords_file, encoding="utf-8") as f:
                data = json.load(f)
            self._keywords_data = data.get("product_lines", [])
            names = [p["name"] for p in self._keywords_data]
            self.kw_product_combo["values"] = names
            if names:
                self.kw_product_combo.current(0)
                self._on_product_change()
        except Exception:
            self._keywords_data = []

    def _on_product_change(self, event=None):
        for w in self.kw_frame.winfo_children():
            w.destroy()
        self.kw_checkboxes.clear()

        name = self.kw_product.get()
        pl = next((p for p in self._keywords_data if p["name"] == name), None)
        if not pl:
            return

        keywords = pl.get("keywords", [])
        for col, kw in enumerate(keywords):
            var = tk.BooleanVar(value=True)
            cb = ttk.Checkbutton(self.kw_frame, text=kw, variable=var)
            cb.grid(row=col // 4, column=col % 4, sticky="w", padx=(4, 8), pady=2)
            self.kw_checkboxes[kw] = var

    def _add_custom_keyword(self):
        kw = self.kw_custom_entry.get().strip()
        if not kw or kw in self.kw_checkboxes:
            return
        var = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(self.kw_frame, text=kw, variable=var)
        col = len(self.kw_checkboxes)
        cb.grid(row=col // 4, column=col % 4, sticky="w", padx=(4, 8), pady=2)
        self.kw_checkboxes[kw] = var
        self.kw_custom_entry.delete(0, tk.END)

    # ── Tab: 📊 账号监控 ────────────────────────────────

    def _build_tab_account(self, nb):
        f = self._tab_frame(nb, "📊 账号监控")
        cfg = self._card_frame(f, "监控配置")

        r0 = ttk.Frame(cfg, style="Card.TLabelframe")
        r0.pack(fill="x", pady=(4, 0))
        ttk.Label(r0, text="从 URL 文件读取账号：", font=FONT).pack(side="left")

        self.acc_url_vars = []  # (brand, identifier, var) for checkboxes

        self.acc_file_frame = ttk.Frame(cfg, style="Card.TLabelframe")
        ttk.Label(self.acc_file_frame, text="URL 文件:").pack(side="left", padx=(0, 6))
        self.acc_file_var = tk.StringVar(value=self.urls_file)
        ttk.Entry(self.acc_file_frame, textvariable=self.acc_file_var, width=40).pack(side="left", padx=(0, 6))
        ttk.Button(self.acc_file_frame, text="📂 浏览", style="Outline.TButton",
                   command=lambda: self._pick_file("acc_file_var")).pack(side="left")
        ttk.Button(self.acc_file_frame, text="📋 读取列表", style="Outline.TButton",
                   command=self._load_file_urls, width=10).pack(side="left", padx=(6, 0))

        self.acc_file_list_frame = ttk.Frame(cfg, style="Card.TLabelframe")

        # 可滚动列表容器
        self.acc_file_canvas_frame = ttk.Frame(cfg, style="Card.TLabelframe")
        self.acc_file_canvas = tk.Canvas(self.acc_file_canvas_frame, bg=CARD_BG, highlightthickness=0, height=150)
        self.acc_file_scrollbar = ttk.Scrollbar(self.acc_file_canvas_frame, orient="vertical", command=self.acc_file_canvas.yview)
        self.acc_file_scroll_inner = ttk.Frame(self.acc_file_canvas, style="Card.TLabelframe")
        self.acc_file_scroll_inner.bind("<Configure>", lambda e: self.acc_file_canvas.configure(scrollregion=self.acc_file_canvas.bbox("all")))
        self.acc_file_canvas.create_window((0, 0), window=self.acc_file_scroll_inner, anchor="nw")
        self.acc_file_canvas.configure(yscrollcommand=self.acc_file_scrollbar.set)
        # 鼠标滚轮绑定
        def _on_mousewheel(event):
            self.acc_file_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.acc_file_canvas.bind("<MouseWheel>", _on_mousewheel)
        self.acc_file_scroll_inner.bind("<MouseWheel>", _on_mousewheel)

        

        r3 = ttk.Frame(cfg, style="Card.TLabelframe")
        r3.pack(fill="x", pady=(6, 0))
        self.acc_limit = tk.StringVar(value="10")
        ttk.Label(r3, text="采集数量:").pack(side="left", padx=(0, 8))
        ttk.Spinbox(r3, from_=1, to=50, textvariable=self.acc_limit, width=6).pack(side="left", padx=(0, 24))
        self.acc_content = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="获取正文", variable=self.acc_content).pack(side="left", padx=(0, 12))
        self.acc_comment = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="获取评论", variable=self.acc_comment).pack(side="left", padx=(0, 12))
        self.acc_visible = tk.BooleanVar(value=False)
        ttk.Checkbutton(r3, text="显示浏览器", variable=self.acc_visible).pack(side="left")

        r4 = ttk.Frame(cfg, style="Card.TLabelframe")
        r4.pack(fill="x", pady=(6, 8))
        self.acc_fs = tk.BooleanVar(value=True)
        ttk.Checkbutton(r4, text="发送到飞书", variable=self.acc_fs).pack(side="left", padx=(0, 12))
        self.acc_agent = tk.BooleanVar(value=True)
        ttk.Checkbutton(r4, text="发送到 AI Agent", variable=self.acc_agent).pack(side="left")

        btnf = ttk.Frame(f, style="TFrame")
        btnf.pack(fill="x", padx=8, pady=(4, 0))
        self.acc_run_btn = ttk.Button(btnf, text="▶  开始采集", style="Accent.TButton",
                                      command=lambda: self._run_account(), width=14)
        self.acc_run_btn.pack(side="left", padx=(0, 8))
        self.acc_stop_btn = ttk.Button(btnf, text="■  停止", style="Danger.TButton",
                                       command=lambda: self._stop_tab("account"), state="disabled", width=10)
        self.acc_stop_btn.pack(side="left")

        self._make_log_area(f, "account")

        # 读取 url 文件（自动加载）
        self._load_file_urls()

    def _load_file_urls(self):
        filepath = self.acc_file_var.get()
        if not os.path.isfile(filepath):
            messagebox.showwarning("提示", f"文件不存在: {filepath}")
            return
        for w in self.acc_file_scroll_inner.winfo_children():
            w.destroy()
        self.acc_url_vars.clear()

        # 解析 urls.txt: # === 品牌名 === 后跟 weibo URL 或小红书号
        entries = []  # (brand, identifier, platform)
        current_brand = None
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                m = __import__("re").match(r'#\s*===\s*(.+?)\s*===\s*$', line)
                if m:
                    current_brand = m.group(1).strip()
                    continue
                if line.startswith("#") or not current_brand:
                    continue
                if "weibo.com" in line:
                    entries.append((current_brand, line, "weibo"))
                elif __import__("re").match(r'^\d+$', line):
                    entries.append((current_brand, line, "xiaohongshu"))

        if not entries:
            messagebox.showinfo("提示", "文件中没有解析到有效 URL\n格式: # === 品牌名 === 后跟 URL")
            return

        # 元气森林置顶
        entries.sort(key=lambda e: (0 if e[0] == "元气森林" else 1))

        header = ttk.Frame(self.acc_file_scroll_inner, style="Card.TLabelframe")
        header.pack(fill="x", pady=(2, 0))
        ttk.Label(header, text=f"共 {len(entries)} 个条目，勾选需要采集的：",
                  font=FONT_SM).pack(side="left", padx=4)

        select_all_btn = ttk.Button(header, text="全选/取消", style="Outline.TButton",
                                    command=self._toggle_all_file_urls, width=10)
        select_all_btn.pack(side="right", padx=4)

        for brand, identifier, platform in entries:
            var = tk.BooleanVar(value=True)
            icon = "📱" if platform == "weibo" else "📕"
            label = f"{brand} ({'微博' if platform == 'weibo' else '小红书'})"
            rf = ttk.Frame(self.acc_file_scroll_inner, style="Card.TLabelframe")
            rf.pack(fill="x", pady=1)
            cb = ttk.Checkbutton(rf, text=f"{icon} {label}", variable=var)
            cb.pack(side="left", padx=(4, 8))
            self.acc_url_vars.append((brand, identifier, var))

        # 显示滚动区域
        self.acc_file_list_frame.pack_forget()
        self.acc_file_canvas_frame.pack(fill="x", pady=(4, 0))
        self.acc_file_canvas.pack(side="left", fill="both", expand=True)
        self.acc_file_scrollbar.pack(side="right", fill="y")

    def _toggle_all_file_urls(self):
        if not self.acc_url_vars:
            return
        any_checked = any(var.get() for _, _, var in self.acc_url_vars)
        new_val = not any_checked
        for _, _, var in self.acc_url_vars:
            var.set(new_val)

    def _pick_file(self, var_name):
        p = filedialog.askopenfilename(title="选择 URL 文件",
                                       filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
                                       initialdir=self.script_dir)
        if p:
            getattr(self, var_name).set(p)

    # ── Tab: ⏰ 定时任务（预留） ────────────────────────────

    def _build_tab_schedule(self, nb):
        f = self._tab_frame(nb, "⏰ 定时任务")
        ttk.Label(f, text="⏰ 定时任务功能即将推出", font=("Microsoft YaHei UI", 14),
                 foreground=TEXT_SECONDARY).pack(expand=True, pady=60)
        ttk.Label(f, text="在这里你可以设置每天定时执行采集任务并自动推送飞书",
                 font=FONT_SM, foreground=TEXT_SECONDARY).pack()

    # ── Tab: ⚙️ Agent 配置 ────────────────────────────────────

    def _build_tab_notify(self, nb):
        f = self._tab_frame(nb, "⚙️ Agent 配置")

        nf = self._card_frame(f, "飞书 Webhook")
        ttk.Label(nf, text="Webhook URL").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        self.fs_webhook_var = tk.StringVar(value="")
        ttk.Entry(nf, textvariable=self.fs_webhook_var, width=55).grid(row=0, column=1, pady=4, sticky="ew")
        nf.columnconfigure(1, weight=1)

        nf2 = self._card_frame(f, "AI Agent")
        ttk.Label(nf2, text="RPC URL").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        self.ag_url_var = tk.StringVar(value="")
        ttk.Entry(nf2, textvariable=self.ag_url_var, width=55).grid(row=0, column=1, pady=4, sticky="ew")
        ttk.Label(nf2, text="Sender ID").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=4)
        self.ag_sender_var = tk.StringVar(value="")
        ttk.Entry(nf2, textvariable=self.ag_sender_var, width=28).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(nf2, text="Chat ID").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=4)
        self.ag_chat_var = tk.StringVar(value="")
        ttk.Entry(nf2, textvariable=self.ag_chat_var, width=28).grid(row=2, column=1, sticky="w", pady=4)
        nf2.columnconfigure(1, weight=1)

        nf3 = ttk.Frame(f, style="TFrame")
        nf3.pack(fill="x", padx=8, pady=(12, 0))
        ttk.Button(nf3, text="💾 保存为默认配置", style="Accent.TButton",
                   command=self._save_notify_config, width=20).pack()
        ttk.Label(nf3, text="保存到 .env 文件", style="Hint.TLabel").pack(pady=(2, 0))

    # ── Tab 切换 ──────────────────────────────────────────

    def _current_tab(self):
        sel = self.notebook.index(self.notebook.select())
        return ["hot", "keyword", "account", "schedule", "notify"][sel]

    def _on_tab_change(self, event=None):
        self.status_var.set(f"当前: {self.notebook.tab(self.notebook.select(), 'text')}")

    # ── 运行逻辑 ──────────────────────────────────────────

    def _stop_tab(self, tab_name):
        proc = self.tab_processes.get(tab_name)
        if proc and proc.poll() is None:
            proc.terminate()
            self._log(tab_name, "■ 已终止", "red")
        self._set_tab_buttons(tab_name, running=False)
        self.status_var.set("■ 已终止")

    def _set_tab_buttons(self, tab_name, running=True):
        btn_map = {
            "hot": (self.hot_run_btn, self.hot_stop_btn),
            "keyword": (self.kw_run_btn, self.kw_stop_btn),
            "account": (self.acc_run_btn, self.acc_stop_btn),
        }
        run_btn, stop_btn = btn_map.get(tab_name, (None, None))
        if run_btn:
            run_btn.config(state="disabled" if running else "normal")
        if stop_btn:
            stop_btn.config(state="normal" if running else "disabled")

    def _run_script_common(self, tab_name, cmd, send_feishu, send_agent):
        self._clear_log(tab_name)
        self._set_tab_buttons(tab_name, running=True)
        self.status_var.set("⏳ 运行中...")
        self._log(tab_name, f"▶ 开始执行: {os.path.basename(cmd[1])}", "cyan")

        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"

        tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json",
            delete=False, dir=self.script_dir, prefix="_gui_")
        tmp_path = tmp.name
        tmp.close()

        def work():
            try:
                full_cmd = cmd + ["-o", tmp_path]
                proc = subprocess.Popen(
                    full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd=self.script_dir, env=env,
                )
                self.tab_processes[tab_name] = proc

                for raw_line in iter(proc.stderr.readline, b""):
                    if not raw_line:
                        break
                    self._log(tab_name, raw_line.decode("utf-8", errors="replace").rstrip())
                proc.wait()

                if proc.returncode != 0:
                    self._log(tab_name, f"\n✗ 脚本异常退出 ({proc.returncode})", "red")
                    self.status_var.set("❌ 执行失败")
                    self.root.after(0, lambda: self._set_tab_buttons(tab_name, running=False))
                    return

                self._log(tab_name, "\n✓ 采集完成", "green")

                if send_feishu:
                    self._log(tab_name, "  正在发送到飞书...", "yellow")
                    ncmd = [PYTHON, os.path.join(self.script_dir, "notify", "notify_feishu.py"),
                            "-i", tmp_path]
                    fs_webhook = self.fs_webhook_var.get().strip()
                    if fs_webhook:
                        ncmd += ["--webhook", fs_webhook]
                    np = subprocess.Popen(ncmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          cwd=self.script_dir, env=env)
                    _, ne = np.communicate()
                    for ln in (ne.decode("utf-8", errors="replace") or "").split("\n"):
                        if ln.strip():
                            self._log(tab_name, "  " + ln.strip())
                    self._log(tab_name, "✅ 已发送到飞书群" if np.returncode == 0 else "❌ 飞书发送失败",
                              "green" if np.returncode == 0 else "red")

                if send_agent:
                    self._log(tab_name, "  正在发送到 AI Agent...", "yellow")
                    acmd = [PYTHON, os.path.join(self.script_dir, "notify", "notify_agent.py"),
                            "-i", tmp_path]
                    ag_url = self.ag_url_var.get().strip()
                    ag_sender = self.ag_sender_var.get().strip()
                    ag_chat = self.ag_chat_var.get().strip()
                    if ag_url:
                        acmd += ["--url", ag_url]
                    if ag_sender:
                        acmd += ["--sender", ag_sender]
                    if ag_chat:
                        acmd += ["--chat", ag_chat]
                    ap = subprocess.Popen(acmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          cwd=self.script_dir, env=env)
                    _, ae = ap.communicate()
                    for ln in (ae.decode("utf-8", errors="replace") or "").split("\n"):
                        if ln.strip():
                            self._log(tab_name, "  " + ln.strip())
                    self._log(tab_name, "✅ 已发送到 AI Agent" if ap.returncode == 0 else "❌ Agent 发送失败",
                              "green" if ap.returncode == 0 else "red")

                self.status_var.set("✅ 完成")
            except Exception as e:
                self._log(tab_name, f"\n✗ 异常: {e}", "red")
                self.status_var.set("❌ 出错")
            finally:
                self.root.after(0, lambda: self._set_tab_buttons(tab_name, running=False))

        threading.Thread(target=work, daemon=True).start()

    def _run_hot(self):
        platform = self.hot_platform.get()
        limit = self.hot_limit.get()
        visible = self.hot_visible.get()

        script_map = {
            "weibo_hot": "weibo_hot_search",
            "weibo_ent": "weibo_hot_search",
            "douyin": "douyin_hot_search",
            "merged": "hot_search",
        }
        script = script_map.get(platform, "hot_search")
        cmd = [PYTHON, os.path.join(self.script_dir, "scripts", f"{script}.py")]

        if platform == "weibo_hot":
            cmd += ["--board", "hot", "--limit", limit]
        elif platform == "weibo_ent":
            cmd += ["--board", "entertainment", "--limit", limit]
        elif platform == "douyin":
            cmd += ["--limit", limit]
        elif platform == "merged":
            cmd += ["--weibo-limit", limit, "--douyin-limit", limit]

        if visible:
            cmd.append("--visible")

        self._run_script_common("hot", cmd, self.hot_fs.get(), self.hot_agent.get())

    def _toggle_all_kw(self):
        if not self.kw_checkboxes:
            return
        any_checked = any(var.get() for var in self.kw_checkboxes.values())
        new_val = not any_checked
        for var in self.kw_checkboxes.values():
            var.set(new_val)
        self.kw_select_all_btn.config(text="取消全选" if new_val else "全选关键词")

    def _run_keyword(self):
        selected = [kw for kw, var in self.kw_checkboxes.items() if var.get()]
        if not selected:
            messagebox.showwarning("提示", "请至少选择一个关键词")
            return

        platforms = []
        if self.kw_weibo.get():
            platforms.append("weibo")
        if self.kw_xhs.get():
            platforms.append("xiaohongshu")
        if not platforms:
            messagebox.showwarning("提示", "请至少选择一个平台")
            return

        cmd = [PYTHON, os.path.join(self.script_dir, "scripts", "keyword_search.py"),
               "--keywords", ",".join(selected),
               "--platforms", "both" if len(platforms) == 2 else platforms[0],
               "--per-keyword", self.kw_per.get()]

        if self.kw_visible.get():
            cmd.append("--visible")

        self._run_script_common("keyword", cmd, self.kw_fs.get(), self.kw_agent.get())

    def _run_account(self):
        selected_urls = [id for _, id, var in self.acc_url_vars if var.get()]
        if not selected_urls:
            messagebox.showwarning("提示", "请勾选至少一个账号")
            return
        raw_urls = selected_urls

        cmd = [PYTHON, os.path.join(self.script_dir, "scripts", "competitor_monitor.py"),
               "--urls"] + raw_urls

        cmd += ["--limit", self.acc_limit.get()]
        if not self.acc_content.get():
            cmd.append("--no-content")
        if not self.acc_comment.get():
            cmd.append("--no-comments")
        if self.acc_visible.get():
            cmd.append("--visible")

        self._run_script_common("account", cmd, self.acc_fs.get(), self.acc_agent.get())


def main():
    root = tk.Tk()
    app = SocialMonitorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
