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
import uuid
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
    # 1) 优先找 exe 同目录下的 python/python.exe（便携版）
    local = os.path.join(os.path.dirname(sys.executable), "python", "python.exe")
    if os.path.isfile(local):
        return local
    try:
        r = subprocess.run(["where", "python"], capture_output=True, text=True, timeout=5)
        if r.stdout:
            for c in [p.strip() for p in r.stdout.strip().split("\n") if p.strip()]:
                if "python" in c.lower() and c.lower().endswith(".exe"):
                    return c
    except Exception:
        pass
    for fb in [
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
        # keywords.json: 编辑写入 exe 同目录，只读回退到 BUNDLE_DIR
        user_kw = os.path.join(BASE_DIR, "keywords.json")
        bundle_kw = os.path.join(BUNDLE_DIR, "keywords.json") if getattr(sys, 'frozen', False) else user_kw
        if getattr(sys, 'frozen', False) and os.path.isfile(user_kw):
            self.keywords_file = user_kw
        else:
            self.keywords_file = bundle_kw

        self.schedule_file = os.path.join(BASE_DIR, "schedule_rules.json")
        self.rules = []
        self._schedule_running = False

        self.tab_processes = {}
        self.tab_logs = {}

        # 串行任务队列（一次只跑一个）
        self._task_queue = []
        self._task_busy = False

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
        style.configure("Bold.TCheckbutton", background=CARD_BG, foreground=TEXT,
                        font=("Microsoft YaHei UI", 11, "bold"))
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
        tk.Label(header, text="一键采集 · AI自动推送", bg=PRIMARY, fg="#c5d9f7",
                 font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(4, 0), pady=12)

        # 定时轮询开关 — 移到 ⏰ 定时任务 Tab
        self.sched_next_label = tk.Label(header, text="", bg=PRIMARY, fg="#c5d9f7",
                                         font=("Microsoft YaHei UI", 9))
        self.sched_next_label.pack(side="right", padx=(0, 8), pady=12)

        nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        self._build_tab_hot(nb)
        self._build_tab_keyword(nb)
        self._build_tab_account_self(nb)
        self._build_tab_account_competitor(nb)
        self._build_tab_detail(nb)
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
                if k.strip() == "AGENT_URL":
                    self.ag_url_var.set(v)
                elif k.strip() == "AGENT_SENDER":
                    self.ag_sender_var.set(v)
                elif k.strip() == "AGENT_CHAT":
                    self.ag_chat_var.set(v)
                elif k.strip() == "AGENT_PREFIX":
                    self.ag_prefix_var.set(v)
                elif k.strip() == "DATA_DIR":
                    self.data_dir_var.set(v)

    def _save_notify_config(self):
        path = self._notify_env_path()
        kv = {
            "AGENT_URL": self.ag_url_var.get(),
            "AGENT_SENDER": self.ag_sender_var.get(),
            "AGENT_CHAT": self.ag_chat_var.get(),
            "AGENT_PREFIX": self.ag_prefix_var.get(),
            "DATA_DIR": self.data_dir_var.get(),
        }
        lines = [
            "# AI Agent",
            f"AGENT_URL={kv['AGENT_URL']}",
            f"AGENT_SENDER={kv['AGENT_SENDER']}",
            f"AGENT_CHAT={kv['AGENT_CHAT']}",
            f"AGENT_PREFIX={kv['AGENT_PREFIX']}",
            f"DATA_DIR={kv['DATA_DIR']}",
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

        r3 = ttk.Frame(cfg, style="Card.TLabelframe")
        r3.pack(fill="x", pady=(6, 8))
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
        ttk.Button(btnf, text="⏰ 设置定时任务", style="Outline.TButton",
                   command=lambda: self._add_schedule_dialog("hot", "🔥热搜"), width=16).pack(side="left", padx=(8, 0))

        self._make_log_area(f, "hot")

    def _add_schedule_dialog(self, tab_type, tab_label):
        """弹出定时任务设置窗口"""
        d = tk.Toplevel(self.root)
        d.title(f"设置定时任务 — {tab_label}")
        d.geometry("400x320")
        d.resizable(False, False)
        d.configure(bg=CARD_BG)
        d.transient(self.root)
        d.grab_set()

        main = ttk.Frame(d, style="TFrame")
        main.pack(fill="both", expand=True, padx=16, pady=12)

        # 规则名称
        ttk.Label(main, text="规则名称:").pack(anchor="w")
        name_var = tk.StringVar(value=f"{tab_label}定时")
        ttk.Entry(main, textvariable=name_var, width=30).pack(fill="x", pady=(2, 8))

        # 星期
        wd_frame = ttk.Frame(main, style="TFrame")
        wd_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(wd_frame, text="星期:").pack(anchor="w")
        wd_inner = ttk.Frame(wd_frame, style="TFrame")
        wd_inner.pack(fill="x", pady=(2, 0))
        weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
        week_vars = {}
        for i, w in enumerate(weekday_names):
            var = tk.BooleanVar(value=(i < 5))
            week_vars[i] = var
            ttk.Checkbutton(wd_inner, text=w, variable=var).pack(side="left", padx=2)

        # 时间
        time_frame = ttk.Frame(main, style="TFrame")
        time_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(time_frame, text="时间:").pack(anchor="w")
        time_inner = ttk.Frame(time_frame, style="TFrame")
        time_inner.pack(fill="x", pady=(2, 0))
        h_var = tk.StringVar(value="09")
        m_var = tk.StringVar(value="00")
        ttk.Spinbox(time_inner, from_=0, to=23, textvariable=h_var, width=4, format="%02.0f").pack(side="left")
        ttk.Label(time_inner, text=" : ").pack(side="left")
        ttk.Spinbox(time_inner, from_=0, to=59, textvariable=m_var, width=4, format="%02.0f").pack(side="left")

        # 发Agent
        agent_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(main, text="发送到 AI Agent", variable=agent_var).pack(anchor="w", pady=(0, 12))

        # 按钮
        btnf = ttk.Frame(main, style="TFrame")
        btnf.pack(fill="x")
        ttk.Button(btnf, text="✗ 取消", command=d.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btnf, text="✓ 确认添加", style="Accent.TButton",
                   command=lambda: self._confirm_add_schedule(
                       d, tab_type, tab_label,
                       name_var.get().strip(),
                       [i for i, v in week_vars.items() if v.get()],
                       h_var.get(), m_var.get(), agent_var.get()
                   )).pack(side="right")

    def _confirm_add_schedule(self, dialog, tab_type, tab_label, name, weekdays, hour, minute, send_agent):
        if not name:
            messagebox.showwarning("提示", "请输入规则名称")
            return
        if not weekdays:
            messagebox.showwarning("提示", "请至少选择一个星期")
            return
        rule = {
            "id": str(uuid.uuid4()),
            "name": name,
            "tab_type": tab_type,
            "enabled": True,
            "weekdays": sorted(weekdays),
            "hour": int(hour),
            "minute": int(minute),
            "send_agent": send_agent,
        }
        self.rules.append(rule)
        self._save_schedule_rules()
        self._refresh_schedule_list()
        dialog.destroy()
        self._log(tab_type, f"✅ 已添加定时任务: {name}", "green")

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
        ttk.Label(r2, text="每个关键词:").pack(side="left", padx=(0, 4))
        self.kw_per = tk.StringVar(value="5")
        ttk.Spinbox(r2, from_=1, to=20, textvariable=self.kw_per, width=5).pack(side="left", padx=(0, 4))
        ttk.Label(r2, text="条  ").pack(side="left")
        ttk.Label(r2, text="    评论数/条:").pack(side="left", padx=(0, 4))
        self.kw_max_comments = tk.StringVar(value="30")
        ttk.Spinbox(r2, from_=0, to=100, textvariable=self.kw_max_comments, width=5).pack(side="left", padx=(0, 4))
        ttk.Label(r2, text="条").pack(side="left")

        r_sort = ttk.Frame(cfg, style="Card.TLabelframe")
        r_sort.pack(fill="x", pady=(2, 0))
        ttk.Label(r_sort, text="排序方式:").pack(side="left", padx=(0, 8))
        self.kw_sort_by = tk.StringVar(value="likes")
        ttk.Radiobutton(r_sort, text="最多点赞", variable=self.kw_sort_by, value="likes").pack(side="left", padx=(0, 4))
        ttk.Radiobutton(r_sort, text="最多评论", variable=self.kw_sort_by, value="comments").pack(side="left", padx=(0, 4))
        ttk.Separator(r_sort, orient="vertical").pack(side="left", padx=(12, 8), fill="y")
        ttk.Label(r_sort, text="内容类型:").pack(side="left", padx=(0, 8))
        self.kw_content_type = tk.StringVar(value="all")
        ttk.Radiobutton(r_sort, text="不限", variable=self.kw_content_type, value="all").pack(side="left", padx=(0, 4))
        ttk.Radiobutton(r_sort, text="仅图文", variable=self.kw_content_type, value="image_text").pack(side="left", padx=(0, 4))

        r3 = ttk.Frame(cfg, style="Card.TLabelframe")
        r3.pack(fill="x", pady=(6, 8))
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
        ttk.Button(btnf, text="⏰ 设置定时任务", style="Outline.TButton",
                   command=lambda: self._add_schedule_dialog("keyword", "🔍关键词"), width=16).pack(side="left", padx=(8, 0))

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

    # ── Tab: 🏠 自有账号 ────────────────────────────────

    def _build_tab_account_self(self, nb):
        f = self._tab_frame(nb, "🏠 自有账号")
        cfg = self._card_frame(f, "自有账号配置")

        # 固定显示元气森林账号
        r0 = ttk.Frame(cfg, style="Card.TLabelframe")
        r0.pack(fill="x", pady=(4, 0))
        ttk.Label(r0, text="监控账号:", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=4, pady=(4, 2))
        for label in ["元气森林（小红书）27247124186", "元气森林（微博）genkiforest"]:
            ttk.Label(r0, text=f"  📕 {label}", style="Hint.TLabel").pack(anchor="w", padx=(12, 4))

        self.acc_self_urls = [
            "27247124186",
            "https://weibo.com/genkiforest",
        ]

        r3 = ttk.Frame(cfg, style="Card.TLabelframe")
        r3.pack(fill="x", pady=(6, 0))
        self.acc_self_limit = tk.StringVar(value="10")
        ttk.Label(r3, text="采集数量:").pack(side="left", padx=(0, 8))
        ttk.Spinbox(r3, from_=1, to=50, textvariable=self.acc_self_limit, width=6).pack(side="left", padx=(0, 24))
        self.acc_self_content = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="获取正文", variable=self.acc_self_content).pack(side="left", padx=(0, 12))
        self.acc_self_comment = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="获取评论", variable=self.acc_self_comment).pack(side="left", padx=(0, 12))
        ttk.Label(r3, text="评论数/条:").pack(side="left", padx=(0, 4))
        self.acc_self_max_comments = tk.StringVar(value="30")
        ttk.Spinbox(r3, from_=0, to=100, textvariable=self.acc_self_max_comments, width=5).pack(side="left", padx=(0, 4))
        ttk.Label(r3, text="条").pack(side="left")

        r4 = ttk.Frame(cfg, style="Card.TLabelframe")
        r4.pack(fill="x", pady=(6, 8))
        self.acc_self_agent = tk.BooleanVar(value=True)
        ttk.Checkbutton(r4, text="发送到 AI Agent", variable=self.acc_self_agent).pack(side="left")

        btnf = ttk.Frame(f, style="TFrame")
        btnf.pack(fill="x", padx=8, pady=(4, 0))
        self.acc_self_run_btn = ttk.Button(btnf, text="▶  开始采集", style="Accent.TButton",
                                           command=lambda: self._run_account_self(), width=14)
        self.acc_self_run_btn.pack(side="left", padx=(0, 8))
        self.acc_self_stop_btn = ttk.Button(btnf, text="■  停止", style="Danger.TButton",
                                            command=lambda: self._stop_tab("account_self"), state="disabled", width=10)
        self.acc_self_stop_btn.pack(side="left")
        ttk.Button(btnf, text="⏰ 设置定时任务", style="Outline.TButton",
                   command=lambda: self._add_schedule_dialog("account_self", "🏠自有"), width=16).pack(side="left", padx=(8, 0))

        self._make_log_area(f, "account_self")

    # ── Tab: 🏢 竞品账号 ────────────────────────────────

    def _build_tab_account_competitor(self, nb):
        f = self._tab_frame(nb, "🏢 竞品账号")
        cfg = self._card_frame(f, "监控配置")

        r0 = ttk.Frame(cfg, style="Card.TLabelframe")
        r0.pack(fill="x", pady=(4, 0))
        ttk.Label(r0, text="从 URL 文件读取账号：", font=FONT).pack(side="left")

        self.acc_comp_url_vars = []

        self.acc_comp_file_frame = ttk.Frame(cfg, style="Card.TLabelframe")
        ttk.Label(self.acc_comp_file_frame, text="URL 文件:").pack(side="left", padx=(0, 6))
        self.acc_comp_file_var = tk.StringVar(value=self.urls_file)
        ttk.Entry(self.acc_comp_file_frame, textvariable=self.acc_comp_file_var, width=40).pack(side="left", padx=(0, 6))
        ttk.Button(self.acc_comp_file_frame, text="📂 浏览", style="Outline.TButton",
                   command=lambda: self._pick_file("acc_comp_file_var")).pack(side="left")
        ttk.Button(self.acc_comp_file_frame, text="📋 读取列表", style="Outline.TButton",
                   command=self._load_comp_file_urls, width=10).pack(side="left", padx=(6, 0))
        self.acc_comp_file_frame.pack(fill="x", pady=(4, 0))

        # 可滚动列表容器
        self.acc_comp_canvas_frame = ttk.Frame(cfg, style="Card.TLabelframe")
        self.acc_comp_canvas = tk.Canvas(self.acc_comp_canvas_frame, bg=CARD_BG, highlightthickness=0, height=150)
        self.acc_comp_scrollbar = ttk.Scrollbar(self.acc_comp_canvas_frame, orient="vertical", command=self.acc_comp_canvas.yview)
        self.acc_comp_scroll_inner = ttk.Frame(self.acc_comp_canvas, style="Card.TLabelframe")
        self.acc_comp_scroll_inner.bind("<Configure>", lambda e: self.acc_comp_canvas.configure(scrollregion=self.acc_comp_canvas.bbox("all")))
        self.acc_comp_canvas.create_window((0, 0), window=self.acc_comp_scroll_inner, anchor="nw")
        self.acc_comp_canvas.configure(yscrollcommand=self.acc_comp_scrollbar.set)
        def _on_mousewheel_comp(event):
            self.acc_comp_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.acc_comp_canvas.bind("<MouseWheel>", _on_mousewheel_comp)
        self.acc_comp_scroll_inner.bind("<MouseWheel>", _on_mousewheel_comp)

        r3 = ttk.Frame(cfg, style="Card.TLabelframe")
        r3.pack(fill="x", pady=(6, 0))
        self.acc_comp_limit = tk.StringVar(value="10")
        ttk.Label(r3, text="采集数量:").pack(side="left", padx=(0, 8))
        ttk.Spinbox(r3, from_=1, to=50, textvariable=self.acc_comp_limit, width=6).pack(side="left", padx=(0, 24))
        self.acc_comp_content = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="获取正文", variable=self.acc_comp_content).pack(side="left", padx=(0, 12))
        self.acc_comp_comment = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="获取评论", variable=self.acc_comp_comment).pack(side="left", padx=(0, 12))
        ttk.Label(r3, text="评论数/条:").pack(side="left", padx=(0, 4))
        self.acc_comp_max_comments = tk.StringVar(value="30")
        ttk.Spinbox(r3, from_=0, to=100, textvariable=self.acc_comp_max_comments, width=5).pack(side="left", padx=(0, 4))
        ttk.Label(r3, text="条").pack(side="left")

        r4 = ttk.Frame(cfg, style="Card.TLabelframe")
        r4.pack(fill="x", pady=(6, 8))
        self.acc_comp_agent = tk.BooleanVar(value=True)
        ttk.Checkbutton(r4, text="发送到 AI Agent", variable=self.acc_comp_agent).pack(side="left")

        btnf = ttk.Frame(f, style="TFrame")
        btnf.pack(fill="x", padx=8, pady=(4, 0))
        self.acc_comp_run_btn = ttk.Button(btnf, text="▶  开始采集", style="Accent.TButton",
                                           command=lambda: self._run_account_comp(), width=14)
        self.acc_comp_run_btn.pack(side="left", padx=(0, 8))
        self.acc_comp_stop_btn = ttk.Button(btnf, text="■  停止", style="Danger.TButton",
                                            command=lambda: self._stop_tab("account_comp"), state="disabled", width=10)
        self.acc_comp_stop_btn.pack(side="left")
        ttk.Button(btnf, text="⏰ 设置定时任务", style="Outline.TButton",
                   command=lambda: self._add_schedule_dialog("account_comp", "🏢竞品"), width=16).pack(side="left", padx=(8, 0))

        self._make_log_area(f, "account_comp")

        # 读取 url 文件（自动加载）
        self._load_comp_file_urls()

    def _load_comp_file_urls(self):
        filepath = self.acc_comp_file_var.get()
        if not os.path.isfile(filepath):
            messagebox.showwarning("提示", f"文件不存在: {filepath}")
            return
        for w in self.acc_comp_scroll_inner.winfo_children():
            w.destroy()
        self.acc_comp_url_vars.clear()

        entries = []
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

        # 过滤掉元气森林（自有账号）
        entries = [e for e in entries if e[0] != "元气森林"]

        if not entries:
            messagebox.showinfo("提示", "文件中没有解析到有效竞品账号")
            return

        header = ttk.Frame(self.acc_comp_scroll_inner, style="Card.TLabelframe")
        header.pack(fill="x", pady=(2, 0))
        ttk.Label(header, text=f"共 {len(entries)} 个竞品条目，勾选需要采集的：",
                  font=FONT_SM).pack(side="left", padx=4)

        select_all_btn = ttk.Button(header, text="全选/取消", style="Outline.TButton",
                                    command=self._toggle_all_comp_urls, width=10)
        select_all_btn.pack(side="right", padx=4)

        for brand, identifier, platform in entries:
            var = tk.BooleanVar(value=True)
            icon = "📱" if platform == "weibo" else "📕"
            label = f"{brand} ({'微博' if platform == 'weibo' else '小红书'})"
            rf = ttk.Frame(self.acc_comp_scroll_inner, style="Card.TLabelframe")
            rf.pack(fill="x", pady=1)
            cb = ttk.Checkbutton(rf, text=f"{icon} {label}", variable=var)
            cb.pack(side="left", padx=(4, 8))
            self.acc_comp_url_vars.append((brand, identifier, var))

        self.acc_comp_canvas_frame.pack(fill="x", pady=(4, 0))
        self.acc_comp_canvas.pack(side="left", fill="both", expand=True)
        self.acc_comp_scrollbar.pack(side="right", fill="y")

    def _toggle_all_comp_urls(self):
        if not self.acc_comp_url_vars:
            return
        any_checked = any(var.get() for _, _, var in self.acc_comp_url_vars)
        new_val = not any_checked
        for _, _, var in self.acc_comp_url_vars:
            var.set(new_val)

    def _pick_file(self, var_name):
        p = filedialog.askopenfilename(title="选择 URL 文件",
                                       filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
                                       initialdir=self.script_dir)
        if p:
            getattr(self, var_name).set(p)

    # ── Tab: 📝 内容详情采集 ──────────────────────────

    def _build_tab_detail(self, nb):
        f = self._tab_frame(nb, "📝 内容详情")
        cfg = self._card_frame(f, "采集配置")

        r1 = ttk.Frame(cfg, style="Card.TLabelframe")
        r1.pack(fill="x", pady=(4, 0))
        ttk.Label(r1, text="内容 URL:").pack(side="left", padx=(0, 8))
        self.detail_url = tk.StringVar()
        ttk.Entry(r1, textvariable=self.detail_url, width=60).pack(side="left", fill="x", expand=True, padx=(0, 8))

        r2 = ttk.Frame(cfg, style="Card.TLabelframe")
        r2.pack(fill="x", pady=(6, 0))
        ttk.Label(r2, text="评论数量:").pack(side="left", padx=(0, 8))
        self.detail_comments = tk.StringVar(value="30")
        ttk.Spinbox(r2, from_=1, to=100, textvariable=self.detail_comments, width=6).pack(side="left", padx=(0, 24))

        r3 = ttk.Frame(cfg, style="Card.TLabelframe")
        r3.pack(fill="x", pady=(6, 8))
        self.detail_agent = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="发送到 AI Agent 总结", variable=self.detail_agent).pack(side="left")

        btnf = ttk.Frame(f, style="TFrame")
        btnf.pack(fill="x", padx=8, pady=(4, 0))
        self.detail_run_btn = ttk.Button(btnf, text="▶  采集并总结", style="Accent.TButton",
                                         command=lambda: self._run_detail(), width=16)
        self.detail_run_btn.pack(side="left", padx=(0, 8))
        self.detail_stop_btn = ttk.Button(btnf, text="■  停止", style="Danger.TButton",
                                          command=lambda: self._stop_tab("detail"), state="disabled", width=10)
        self.detail_stop_btn.pack(side="left")

        self._make_log_area(f, "detail")

    def _run_detail(self):
        url = self.detail_url.get().strip()
        if not url:
            messagebox.showwarning("提示", "请输入内容 URL")
            return
        if "xiaohongshu.com" not in url and "weibo.com" not in url:
            messagebox.showwarning("提示", "请提供小红书或微博的内容链接")
            return

        cmd = [PYTHON, os.path.join(self.script_dir, "scripts", "url_detail.py"),
               "--url", url,
               "--max-comments", self.detail_comments.get()]

        self._run_script_common("detail", cmd, self.detail_agent.get(), source_type="detail")

    # ── 定时轮询 ──────────────────────────────────────────

    def _toggle_schedule(self):
        if self._schedule_running:
            self._schedule_running = False
            self.sch_start_btn.config(text="▶ 启动定时轮询")
            self.sched_next_label.config(text="")
            self._log("schedule", "■ 定时轮询已停止", "red")
        else:
            self._schedule_running = True
            self.sch_start_btn.config(text="■ 停止定时轮询")
            self._log("schedule", "▶ 定时轮询已启动", "green")
            self._update_next_run_label()
            self._schedule_loop()

    def _update_next_run_label(self):
        """计算所有规则中最近的下次执行时间"""
        import datetime as dt
        now = dt.datetime.now()
        nearest = None
        for rule in self.rules:
            if not rule.get("enabled"):
                continue
            try:
                hour, minute = rule["hour"], rule["minute"]
            except (KeyError, ValueError):
                continue
            last_date = rule.get("last_run_date", "")
            for offset in range(0, 8):
                check = now + dt.timedelta(days=offset)
                if check.weekday() not in rule.get("weekdays", []):
                    continue
                target = check.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now:
                    continue
                if target.strftime("%Y-%m-%d") == last_date:
                    continue
                if nearest is None or target < nearest:
                    nearest = target
                break
        if nearest:
            wd_names = ["一", "二", "三", "四", "五", "六", "日"]
            wd = wd_names[nearest.weekday()]
            self.sched_next_label.config(text=f"⏰ 下次: {nearest.strftime('%m-%d %H:%M')} ({wd})")
        else:
            self.sched_next_label.config(text="(无待执行定时)")

    def _schedule_loop(self):
        if not self._schedule_running:
            return
        import datetime as dt
        now = dt.datetime.now()
        today = now.strftime("%Y-%m-%d")

        for rule in list(self.rules):
            if not rule.get("enabled"):
                continue
            try:
                hour, minute = rule["hour"], rule["minute"]
            except (KeyError, ValueError):
                continue
            if now.weekday() not in rule.get("weekdays", []):
                continue
            if now.hour != hour or now.minute != minute:
                continue
            if rule.get("last_run_date", "") == today:
                continue

            tab_type = rule.get("tab_type", "hot")
            self._log("schedule", f"\n⏰ 到达执行时间: {rule['name']}", "cyan")
            import threading as _th
            _th.Thread(target=lambda r=rule: self._run_scheduled_rule(r), daemon=True).start()

        self.root.after(30000, self._schedule_loop)

    def _run_scheduled_rule(self, rule):
        """执行一条定时规则"""
        import datetime as dt
        tab_type = rule.get("tab_type", "hot")
        try:
            cmd = None
            st = tab_type

            if tab_type == "hot":
                platform = self.hot_platform.get()
                limit = self.hot_limit.get()
                script_map = {
                    "weibo_hot": "weibo_hot_search", "weibo_ent": "weibo_hot_search",
                    "douyin": "douyin_hot_search", "merged": "hot_search",
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

            elif tab_type == "keyword":
                selected = [kw for kw, var in self.kw_checkboxes.items() if var.get()]
                platforms = []
                if self.kw_weibo.get(): platforms.append("weibo")
                if self.kw_xhs.get(): platforms.append("xiaohongshu")
                per_kw = self.kw_per.get()
                if selected and platforms:
                    cmd = [PYTHON, os.path.join(self.script_dir, "scripts", "keyword_search.py"),
                           "--keywords", ",".join(selected),
                           "--platforms", "both" if len(platforms) == 2 else platforms[0],
                           "--per-keyword", per_kw,
                           "--max-comments", self.kw_max_comments.get(),
                           "--sort-by", self.kw_sort_by.get(),
                           "--content-type", self.kw_content_type.get()]

            elif tab_type == "account_self":
                if hasattr(self, 'acc_self_urls') and self.acc_self_urls:
                    cmd = [PYTHON, os.path.join(self.script_dir, "scripts", "competitor_monitor.py"),
                           "--urls"] + list(self.acc_self_urls)
                    cmd += ["--limit", self.acc_self_limit.get()]
                    cmd += ["--max-comments", self.acc_self_max_comments.get()]

            elif tab_type == "account_comp":
                selected = []
                if hasattr(self, 'acc_comp_url_vars'):
                    selected = [identifier for _, identifier, var in self.acc_comp_url_vars if var.get()]
                if selected:
                    cmd = [PYTHON, os.path.join(self.script_dir, "scripts", "competitor_monitor.py"),
                           "--urls"] + selected
                    cmd += ["--limit", self.acc_comp_limit.get()]
                    cmd += ["--max-comments", self.acc_comp_max_comments.get()]

            if cmd:
                send_agent = rule.get("send_agent", True)
                self._run_script_common("schedule", cmd, send_agent, source_type=st)
                rule["last_run_date"] = dt.datetime.now().strftime("%Y-%m-%d")
                self._save_schedule_rules()
                self.root.after(0, self._refresh_schedule_list)
        except Exception as e:
            self._log("schedule", f"  ✗ {rule['name']}: {e}", "red")

    def _load_schedule_rules(self):
        if os.path.isfile(self.schedule_file):
            try:
                with open(self.schedule_file, encoding="utf-8") as f:
                    self.rules = json.load(f)
            except Exception:
                self.rules = []
        else:
            self.rules = []
        self._refresh_schedule_list()

    def _save_schedule_rules(self):
        with open(self.schedule_file, "w", encoding="utf-8") as f:
            json.dump(self.rules, f, ensure_ascii=False, indent=2)

    def _delete_schedule_rule(self, rule):
        if rule in self.rules:
            self.rules.remove(rule)
            self._save_schedule_rules()
            self._refresh_schedule_list()
            self._log("schedule", f"已删除规则: {rule['name']}", "yellow")

    def _toggle_rule_enabled(self, rule, var):
        rule["enabled"] = var.get()
        self._save_schedule_rules()
        self._update_next_run_label()

    def _refresh_schedule_list(self):
        for w in self.sch_list_inner.winfo_children():
            w.destroy()
        if not self.rules:
            ttk.Label(self.sch_list_inner, text="暂无规则，可在各功能Tab中设置",
                      style="Hint.TLabel").pack(pady=20)
            return
        weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
        tab_icons = {"hot": "🔥热搜", "keyword": "🔍关键词", "account": "📊账号",
                      "account_self": "🏠自有", "account_comp": "🏢竞品"}
        for rule in self.rules:
            row = ttk.Frame(self.sch_list_inner, style="Card.TLabelframe")
            row.pack(fill="x", pady=2, padx=2)
            en_var = tk.BooleanVar(value=rule.get("enabled", True))
            en_var.trace_add("write", lambda *a, r=rule, v=en_var: self._toggle_rule_enabled(r, v))
            ttk.Checkbutton(row, variable=en_var).pack(side="left", padx=(4, 4))
            wd_text = "".join(weekday_names[d] for d in sorted(rule.get("weekdays", [])))
            tag = "·发Agent" if rule.get("send_agent") else ""
            info = f"{rule['name']}  {tab_icons.get(rule['tab_type'], '?')}  {wd_text}  {rule.get('hour',9):02d}:{rule.get('minute',0):02d}{tag}"
            ttk.Label(row, text=info, font=FONT).pack(side="left", padx=(0, 8))
            last = rule.get("last_run_date", "")
            if last:
                ttk.Label(row, text=f"上次:{last}", font=FONT_SM,
                          foreground=TEXT_SECONDARY).pack(side="left", padx=(8, 0))
            ttk.Button(row, text="🗑", command=lambda r=rule: self._delete_schedule_rule(r),
                       width=3).pack(side="right", padx=2)
        self.sch_list_inner.update_idletasks()
        self.sch_list_canvas.configure(scrollregion=self.sch_list_canvas.bbox("all"))

    def _build_tab_schedule(self, nb):
        f = self._tab_frame(nb, "⏰ 定时任务")
        top_frame = ttk.Frame(f, style="TFrame")
        top_frame.pack(fill="x", padx=8, pady=(4, 0))
        self.sch_start_btn = ttk.Button(top_frame, text="▶ 启动定时轮询", style="Accent.TButton",
                                        command=self._toggle_schedule, width=16)
        self.sch_start_btn.pack(side="left")
        ttk.Label(top_frame, text="启动后每30秒检查一次，到点的规则自动执行",
                  style="Hint.TLabel").pack(side="left", padx=(8, 0))
        self.sched_next_label_copy = ttk.Label(top_frame, text="", font=FONT_SM, foreground=TEXT_SECONDARY)
        self.sched_next_label_copy.pack(side="right", padx=(8, 0))

        list_frame = ttk.LabelFrame(f, text="定时规则列表", style="Card.TLabelframe")
        list_frame.pack(fill="both", expand=True, padx=8, pady=(6, 0))

        list_inner_f = ttk.Frame(list_frame, style="Card.TLabelframe")
        list_inner_f.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.sch_list_canvas = tk.Canvas(list_inner_f, bg=CARD_BG, highlightthickness=0, height=200)
        scrollbar = ttk.Scrollbar(list_inner_f, orient="vertical", command=self.sch_list_canvas.yview)
        self.sch_list_inner = ttk.Frame(self.sch_list_canvas, style="Card.TLabelframe")
        self.sch_list_inner.bind("<Configure>",
                                 lambda e: self.sch_list_canvas.configure(scrollregion=self.sch_list_canvas.bbox("all")))
        self.sch_list_canvas.create_window((0, 0), window=self.sch_list_inner, anchor="nw")
        self.sch_list_canvas.configure(yscrollcommand=scrollbar.set)
        self.sch_list_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._make_log_area(f, "schedule")
        self._load_schedule_rules()

    def _build_tab_notify(self, nb):
        f = self._tab_frame(nb, "⚙️ 配置")

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
        ttk.Label(nf2, text="前缀提示词").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=4)
        self.ag_prefix_var = tk.StringVar(value="使用social-intelligence-refinery处理以下内容")
        ttk.Entry(nf2, textvariable=self.ag_prefix_var, width=55).grid(row=3, column=1, pady=4, sticky="ew")
        nf2.columnconfigure(1, weight=1)

        # 数据保存目录
        nf_save = self._card_frame(f, "数据存储")
        ttk.Label(nf_save, text="JSON 保存目录:").pack(anchor="w")
        self.data_dir_var = tk.StringVar(value=os.path.join(BASE_DIR, "data"))
        entry = ttk.Entry(nf_save, textvariable=self.data_dir_var, width=50)
        entry.pack(fill="x", pady=(2, 4))
        ttk.Button(nf_save, text="📂 浏览", style="Outline.TButton",
                   command=lambda: self._pick_data_dir()).pack()

        nf3 = ttk.Frame(f, style="TFrame")
        nf3.pack(fill="x", padx=8, pady=(12, 0))
        ttk.Button(nf3, text="💾 保存为默认配置", style="Accent.TButton",
                   command=self._save_notify_config, width=20).pack()
        ttk.Label(nf3, text="保存到 .env 文件", style="Hint.TLabel").pack(pady=(2, 0))

    def _pick_data_dir(self):
        p = filedialog.askdirectory(title="选择数据保存目录", initialdir=self.data_dir_var.get())
        if p:
            self.data_dir_var.set(p)

    # ── Tab 切换 ──────────────────────────────────────────

    def _current_tab(self):
        sel = self.notebook.index(self.notebook.select())
        return ["hot", "keyword", "account_self", "account_comp", "detail", "schedule", "notify"][sel]

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
            "account_self": (self.acc_self_run_btn, self.acc_self_stop_btn),
            "account_comp": (self.acc_comp_run_btn, self.acc_comp_stop_btn),
            "detail": (self.detail_run_btn, self.detail_stop_btn),
        }
        run_btn, stop_btn = btn_map.get(tab_name, (None, None))
        if run_btn:
            run_btn.config(state="disabled" if running else "normal")
        if stop_btn:
            stop_btn.config(state="normal" if running else "disabled")

    def _run_script_common(self, tab_name, cmd, send_agent, source_type=None):
        """将任务加入串行队列，一次只执行一个"""
        self._task_queue.append((tab_name, cmd, send_agent, source_type))
        self._log(tab_name, "⏳ 已加入队列，等待执行...", "yellow")
        self._process_queue()

    def _process_queue(self):
        """串行执行队列中的下一个任务"""
        if self._task_busy or not self._task_queue:
            return
        self._task_busy = True
        tab_name, cmd, send_agent, source_type = self._task_queue.pop(0)

        self._clear_log(tab_name)
        self._set_tab_buttons(tab_name, running=True)
        self.status_var.set("⏳ 运行中...")
        self._log(tab_name, f"▶ 开始执行: {os.path.basename(cmd[1])}", "cyan")

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        # 把采集数据保存目录传给子进程（可在配置页修改）
        data_root = self.data_dir_var.get()
        env["SOCIAL_MONITOR_DATA_DIR"] = data_root
        # 把 scripts/ 目录加入 PYTHONPATH，子进程才能找到 common.py
        scripts_dir = os.path.join(self.script_dir, "scripts")
        env.setdefault("PYTHONPATH", scripts_dir)

        tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json",
            delete=False, dir=BASE_DIR, prefix="_gui_")
        tmp_path = tmp.name
        tmp.close()

        log_tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".log",
            delete=False, dir=BASE_DIR, prefix="_gui_log_")
        log_path = log_tmp.name
        log_tmp.close()

        def work(tn=tab_name, c=cmd, sa=send_agent, st=source_type):
            try:
                full_cmd = c + ["-o", tmp_path]

                # ── 实时日志：边跑边显示 ──
                proc = subprocess.Popen(
                    full_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    bufsize=1, cwd=self.script_dir, env=env,
                )
                self.tab_processes[tn] = proc

                def _read_stdout(p, tt, lpath):
                    import io
                    for raw_line in iter(p.stdout.readline, b''):
                        if not raw_line:
                            break
                        try:
                            line = raw_line.decode("utf-8", errors="replace").rstrip()
                        except Exception:
                            line = str(raw_line).rstrip()
                        if line:
                            self.root.after(0, lambda l=line: self._log(tt, l))
                    p.stdout.close()
                    # 也把完整日志写文件，方便调试
                    try:
                        if os.path.isfile(lpath):
                            with open(lpath, "a", encoding="utf-8") as lf:
                                pass
                    except Exception:
                        pass

                import threading as _th
                _th.Thread(target=_read_stdout, args=(proc, tn, log_path), daemon=True).start()
                proc.wait()

                if proc.returncode != 0:
                    self._log(tn, f"\n✗ 脚本异常退出 ({proc.returncode})", "red")
                    self.status_var.set("❌ 执行失败")
                    self.root.after(0, lambda: self._set_tab_buttons(tn, running=False))
                    return

                self._log(tn, "\n✓ 采集完成", "green")

                # ── 无论是否发Agent，都保存数据到用户配置的目录 ──
                data_root = self.data_dir_var.get()
                sub_map = {"hot": "hot", "keyword": "keyword", "account": "account",
                           "self_account": "account", "competitor_account": "account", "detail": "detail"}
                sub = sub_map.get(st or "", "")
                target_dir = os.path.join(data_root, sub) if sub else data_root
                os.makedirs(target_dir, exist_ok=True)
                if os.path.isfile(tmp_path):
                    from datetime import datetime as _dt
                    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                    save_path = os.path.join(target_dir, f"{st or 'data'}_{ts}.json")
                    try:
                        import shutil
                        shutil.copy2(tmp_path, save_path)
                        self._log(tn, f"  💾 数据已保存: {save_path}", "green")
                    except Exception as e:
                        self._log(tn, f"  ⚠ 保存失败: {e}", "orange")

                # ── 发送到 Agent（可选） ──
                if sa:
                    self._log(tn, "  正在发送到 AI Agent...", "yellow")
                    acmd = [PYTHON, os.path.join(self.script_dir, "notify", "notify_agent.py"),
                            "-i", tmp_path]
                    if st:
                        acmd += ["--source-type", st]
                    ag_url = self.ag_url_var.get().strip()
                    ag_sender = self.ag_sender_var.get().strip()
                    ag_chat = self.ag_chat_var.get().strip()
                    ag_prefix = self.ag_prefix_var.get().strip()
                    if ag_url:
                        acmd += ["--url", ag_url]
                    if ag_sender:
                        acmd += ["--sender", ag_sender]
                    if ag_chat:
                        acmd += ["--chat", ag_chat]
                    if ag_prefix:
                        acmd += ["--prefix", ag_prefix]
                    ap = subprocess.Popen(acmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          cwd=self.script_dir, env=env)
                    _, ae = ap.communicate()
                    for ln in (ae.decode("utf-8", errors="replace") or "").split("\n"):
                        if ln.strip():
                            self._log(tn, "  " + ln.strip())
                    self._log(tn, "✅ 已发送到 AI Agent" if ap.returncode == 0 else "❌ Agent 发送失败",
                              "green" if ap.returncode == 0 else "red")

                self.status_var.set("✅ 完成")
            except Exception as e:
                self._log(tn, f"\n✗ 异常: {e}", "red")
                self.status_var.set("❌ 出错")
                import traceback
                self._log(tn, traceback.format_exc(), "red")
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                try:
                    os.unlink(log_path)
                except Exception:
                    pass
                self.root.after(0, lambda: self._set_tab_buttons(tn, running=False))
                self._task_busy = False
                self.root.after(0, self._process_queue)

        threading.Thread(target=work, daemon=True).start()

    def _run_hot(self):
        platform = self.hot_platform.get()
        limit = self.hot_limit.get()

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

        

        self._run_script_common("hot", cmd, self.hot_agent.get(), source_type="hot")

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
               "--per-keyword", self.kw_per.get(),
               "--max-comments", self.kw_max_comments.get(),
               "--sort-by", self.kw_sort_by.get(),
               "--content-type", self.kw_content_type.get()]

        self._run_script_common("keyword", cmd, self.kw_agent.get(), source_type="keyword")

    def _run_account_self(self):
        urls = self.acc_self_urls
        cmd = [PYTHON, os.path.join(self.script_dir, "scripts", "competitor_monitor.py"),
               "--urls"] + urls
        cmd += ["--limit", self.acc_self_limit.get()]
        cmd += ["--max-comments", self.acc_self_max_comments.get()]
        if not self.acc_self_content.get():
            cmd.append("--no-content")
        if not self.acc_self_comment.get():
            cmd.append("--no-comments")
        self._run_script_common("account_self", cmd, self.acc_self_agent.get(), source_type="self_account")

    def _run_account_comp(self):
        selected = [id for _, id, var in self.acc_comp_url_vars if var.get()]
        if not selected:
            messagebox.showwarning("提示", "请至少勾选一个竞品账号")
            return
        cmd = [PYTHON, os.path.join(self.script_dir, "scripts", "competitor_monitor.py"),
               "--urls"] + selected
        cmd += ["--limit", self.acc_comp_limit.get()]
        cmd += ["--max-comments", self.acc_comp_max_comments.get()]
        if not self.acc_comp_content.get():
            cmd.append("--no-content")
        if not self.acc_comp_comment.get():
            cmd.append("--no-comments")
        self._run_script_common("account_comp", cmd, self.acc_comp_agent.get(), source_type="competitor_account")


def main():
    root = tk.Tk()
    app = SocialMonitorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
