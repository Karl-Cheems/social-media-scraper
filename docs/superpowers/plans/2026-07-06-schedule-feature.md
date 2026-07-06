# 定时任务功能 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 GUI 的「⏰ 定时任务」tab 中实现可配置的定时采集调度器

**Architecture:** 在 GUI 内用一个 polling 线程每隔 30 秒检查一次当前时间是否到达设定的执行时间。到点时调用现有的 `_run_script_common()` 来执行已勾选的任务。

**Tech Stack:** Python tkinter, threading, datetime

---

### Task 1: 构建定时任务 UI

**Files:**
- Modify: `social_monitor_gui.py:545-551`

替换占位的 `_build_tab_schedule` 为完整的 UI。

- [ ] **Step 1: 导入 `threading`, `datetime`, `calendar`**

文件头部已有 `import threading`, `import time`，需要确认。

- [ ] **Step 2: 替换 `_build_tab_schedule` 方法**

```python
def _build_tab_schedule(self, nb):
    f = self._tab_frame(nb, "⏰ 定时任务")
    cfg = self._card_frame(f, "定时设置")

    r0 = ttk.Frame(cfg, style="Card.TLabelframe")
    r0.pack(fill="x", pady=(4, 0))
    self.sch_enabled = tk.BooleanVar(value=False)
    ttk.Checkbutton(r0, text="开启定时任务", variable=self.sch_enabled,
                    font=("Microsoft YaHei UI", 11, "bold")).pack(side="left", padx=(0, 16))

    ttk.Label(r0, text="频率:").pack(side="left", padx=(0, 6))
    self.sch_freq = tk.StringVar(value="daily")
    ttk.Radiobutton(r0, text="每天", variable=self.sch_freq, value="daily").pack(side="left", padx=(0, 8))
    ttk.Radiobutton(r0, text="每周", variable=self.sch_freq, value="weekly").pack(side="left", padx=(0, 8))

    ttk.Label(r0, text="时间:").pack(side="left", padx=(12, 4))
    self.sch_hour = tk.StringVar(value="09")
    self.sch_min = tk.StringVar(value="00")
    ttk.Spinbox(r0, from_=0, to=23, textvariable=self.sch_hour, width=3, format="%02.0f").pack(side="left")
    ttk.Label(r0, text=":").pack(side="left")
    ttk.Spinbox(r0, from_=0, to=59, textvariable=self.sch_min, width=3, format="%02.0f").pack(side="left")

    # 星期选择（每周模式）
    self.sch_week_frame = ttk.Frame(cfg, style="Card.TLabelframe")
    self.sch_week_frame.pack(fill="x", pady=(4, 0))
    ttk.Label(self.sch_week_frame, text="星期:").pack(side="left", padx=(0, 6))
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    self.sch_week_vars = {}
    for w in weekdays:
        self.sch_week_vars[w] = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.sch_week_frame, text=w, variable=self.sch_week_vars[w]).pack(side="left", padx=2)

    # 任务选择
    task_title = ttk.Label(cfg, text="选择要定时执行的任务:", font=("Microsoft YaHei UI", 10))
    task_title.pack(fill="x", padx=8, pady=(6, 0))

    # 热搜
    r1 = ttk.Frame(cfg, style="Card.TLabelframe")
    r1.pack(fill="x", pady=(2, 0))
    self.sch_hot = tk.BooleanVar(value=True)
    ttk.Checkbutton(r1, text="🔥 热搜", variable=self.sch_hot).pack(side="left", padx=(0, 8))
    ttk.Label(r1, text="平台:").pack(side="left", padx=(8, 4))
    self.sch_hot_platform = tk.StringVar(value="merged")
    ttk.Combobox(r1, textvariable=self.sch_hot_platform, values=["weibo_hot", "weibo_ent", "douyin", "merged"],
                 state="readonly", width=10).pack(side="left", padx=(0, 8))
    ttk.Label(r1, text="数量:").pack(side="left", padx=(8, 4))
    self.sch_hot_limit = tk.StringVar(value="15")
    ttk.Spinbox(r1, from_=1, to=50, textvariable=self.sch_hot_limit, width=4).pack(side="left")
    self.sch_hot_agent = tk.BooleanVar(value=True)
    ttk.Checkbutton(r1, text="发送Agent", variable=self.sch_hot_agent).pack(side="right", padx=(8, 4))

    # 关键词搜索
    r2 = ttk.Frame(cfg, style="Card.TLabelframe")
    r2.pack(fill="x", pady=(2, 0))
    self.sch_kw = tk.BooleanVar(value=True)
    ttk.Checkbutton(r2, text="🔍 关键词搜索", variable=self.sch_kw).pack(side="left", padx=(0, 8))
    ttk.Label(r2, text="产品线:").pack(side="left", padx=(8, 4))
    self.sch_kw_product = tk.StringVar(value="")
    ttk.Combobox(r2, textvariable=self.sch_kw_product, values=[], state="readonly", width=12).pack(side="left", padx=(0, 8))
    ttk.Label(r2, text="数量:").pack(side="left", padx=(8, 4))
    self.sch_kw_per = tk.StringVar(value="5")
    ttk.Spinbox(r2, from_=1, to=20, textvariable=self.sch_kw_per, width=4).pack(side="left")
    self.sch_kw_agent = tk.BooleanVar(value=True)
    ttk.Checkbutton(r2, text="发送Agent", variable=self.sch_kw_agent).pack(side="right", padx=(8, 4))

    # 账号监控
    r3 = ttk.Frame(cfg, style="Card.TLabelframe")
    r3.pack(fill="x", pady=(2, 0))
    self.sch_acc = tk.BooleanVar(value=True)
    ttk.Checkbutton(r3, text="📊 账号监控", variable=self.sch_acc).pack(side="left", padx=(0, 8))
    ttk.Label(r3, text="URL文件:").pack(side="left", padx=(8, 4))
    self.sch_acc_file = tk.StringVar(value=self.urls_file)
    ttk.Entry(r3, textvariable=self.sch_acc_file, width=30).pack(side="left", padx=(0, 8))
    ttk.Label(r3, text="数量:").pack(side="left", padx=(8, 4))
    self.sch_acc_limit = tk.StringVar(value="10")
    ttk.Spinbox(r3, from_=1, to=50, textvariable=self.sch_acc_limit, width=4).pack(side="left")
    self.sch_acc_agent = tk.BooleanVar(value=True)
    ttk.Checkbutton(r3, text="发送Agent", variable=self.sch_acc_agent).pack(side="right", padx=(8, 4))

    # 按钮
    btnf = ttk.Frame(f, style="TFrame")
    btnf.pack(fill="x", padx=8, pady=(4, 0))
    self.sch_start_btn = ttk.Button(btnf, text="▶  启动定时任务", style="Accent.TButton",
                                    command=self._toggle_schedule, width=16)
    self.sch_start_btn.pack(side="left", padx=(0, 8))
    ttk.Label(btnf, text="启动后每30秒检查一次，到点时自动执行", style="Hint.TLabel").pack(side="left", padx=(8, 0))

    # 下次执行时间
    self.sch_next_label = ttk.Label(f, text="", font=FONT_SM, foreground=TEXT_SECONDARY)
    self.sch_next_label.pack(fill="x", padx=8, pady=(2, 0))

    self._make_log_area(f, "schedule")

    # 定时器线程引用
    self._schedule_running = False
    self._schedule_thread = None
```

- [ ] **Step 3: 在 `_load_keywords` 加载后同步产品线列表到定时任务下拉框**

```python
# 在 _load_keywords 方法末尾加：
if hasattr(self, 'sch_kw_product'):
    self.sch_kw_product_combo = self.sch_kw_product
```

实际上用 Combobox 的 values 手动设置，在 `_load_keywords()` 调用后同步：

```python
# 在 __init__ 中 self._load_keywords() 之后：
self.root.after(500, self._sync_schedule_products)
```

```python
def _sync_schedule_products(self):
    """同步关键词产品线到定时任务下拉框"""
    if hasattr(self, 'sch_kw_product'):
        products = list(self.kw_checkboxes.keys())
        if products:
            self.sch_kw_product.set(products[0])
        # 用独立 Combobox，不共用同一个
```

更好的做法：在定时任务 tab 中用和关键词搜索 tab 相同的产品线选择——用一个只有显示用途的 Combobox，实际不储存。

---

### Task 2: 实现定时调度逻辑

**Files:**
- Modify: `social_monitor_gui.py`

- [ ] **Step 1: 新增 `_toggle_schedule` 方法**

```python
def _toggle_schedule(self):
    if self._schedule_running:
        self._schedule_running = False
        self.sch_start_btn.config(text="▶  启动定时任务")
        self._log("schedule", "■ 定时任务已停止", "red")
    else:
        self._schedule_running = True
        self.sch_start_btn.config(text="■  停止定时任务")
        self._log("schedule", "▶ 定时任务已启动", "green")
        self._schedule_next_time()
        self._schedule_loop()
```

- [ ] **Step 2: 新增 `_schedule_next_time` 计算下次执行时间**

```python
def _schedule_next_time(self):
    """计算并显示下次执行时间"""
    import datetime as dt
    now = dt.datetime.now()
    hour = int(self.sch_hour.get())
    minute = int(self.sch_min.get())

    if self.sch_freq.get() == "daily":
        # 每天：如果今天已过就明天
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += dt.timedelta(days=1)
        self.sch_next_label.config(text=f"下次执行: {target.strftime('%Y-%m-%d %H:%M')}")
    else:
        # 每周：找下一周的对应日
        weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6}
        today_wd = now.weekday()
        for offset in range(0, 8):
            check = now + dt.timedelta(days=offset)
            wd_name = list(weekday_map.keys())[list(weekday_map.values()).index(check.weekday())]
            if self.sch_week_vars.get(wd_name, tk.BooleanVar(value=False)).get():
                target = check.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now:
                    continue
                self.sch_next_label.config(text=f"下次执行: {target.strftime('%Y-%m-%d %H:%M')} ({wd_name})")
                return
```

- [ ] **Step 3: 新增 `_schedule_loop` 轮询方法**

```python
def _schedule_loop(self):
    """每30秒检查一次是否需要执行。"""
    if not self._schedule_running:
        return

    import datetime as dt
    now = dt.datetime.now()
    hour = int(self.sch_hour.get())
    minute = int(self.sch_min.get())

    should_run = False
    if self.sch_freq.get() == "daily":
        if now.hour == hour and now.minute == minute:
            should_run = True
    else:
        weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6}
        today_wd = now.weekday()
        for name, var in self.sch_week_vars.items():
            if var.get() and weekday_map[name] == today_wd:
                if now.hour == hour and now.minute == minute:
                    should_run = True
                    break

    if should_run and self.sch_enabled.get():
        self._log("schedule", f"\n⏰ 到达执行时间 {now.strftime('%H:%M')}，开始执行任务...", "cyan")
        self._execute_scheduled_tasks()
        # 等待1分钟避免同一分钟重复触发
        self.root.after(60000, self._schedule_loop)
        self._schedule_next_time()
        return

    self.root.after(30000, self._schedule_loop)
```

- [ ] **Step 4: 新增 `_execute_scheduled_tasks` 方法**

```python
def _execute_scheduled_tasks(self):
    """执行所有已勾选的定时任务。"""
    import threading as _th

    def _run_all():
        # 热搜
        if self.sch_hot.get():
            self._log("schedule", "  ▶ 执行: 热搜", "yellow")
            platform = self.sch_hot_platform.get()
            limit = self.sch_hot_limit.get()
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
            self._run_script_common("schedule", cmd, False, self.sch_hot_agent.get())

        # 关键词搜索
        if self.sch_kw.get():
            self._log("schedule", "  ▶ 执行: 关键词搜索", "yellow")
            product = self.sch_kw_product.get()
            keywords = []
            if product and product in self.kw_checkboxes:
                keywords = [kw for kw, var in self.kw_checkboxes.items() if var.get()]
            if not keywords:
                keywords = list(self.kw_checkboxes.keys())[:3] if self.kw_checkboxes else []
            if keywords:
                cmd = [PYTHON, os.path.join(self.script_dir, "scripts", "keyword_search.py"),
                       "--keywords", ",".join(keywords),
                       "--platforms", "both",
                       "--per-keyword", self.sch_kw_per.get()]
                self._run_script_common("schedule", cmd, False, self.sch_kw_agent.get())

        # 账号监控
        if self.sch_acc.get():
            self._log("schedule", "  ▶ 执行: 账号监控", "yellow")
            selected = [id for _, id, var in self.acc_url_vars if var.get()]
            if selected:
                cmd = [PYTHON, os.path.join(self.script_dir, "scripts", "competitor_monitor.py"),
                       "--urls"] + selected
                cmd += ["--limit", self.sch_acc_limit.get()]
                self._run_script_common("schedule", cmd, False, self.sch_acc_agent.get())

        self._log("schedule", "  ✓ 定时任务全部完成", "green")

    _th.Thread(target=_run_all, daemon=True).start()
```

---

### Task 3: 同步产品线到定时任务

**Files:**
- Modify: `social_monitor_gui.py`

- [ ] **Step 1: 在 `_load_keywords` 方法末尾同步产品线**

```python
# 在 _load_keywords 最后添加：
self._sync_schedule_products()
```

```python
def _sync_schedule_products(self):
    if hasattr(self, 'sch_kw_product'):
        products = list(self.kw_checkboxes.keys())
        if products:
            self.sch_kw_product.set(products[0])
```

- [ ] **Step 2: 在 `_build_tab_schedule` 中初始化时调用一次同步**

在 `_build_tab_schedule` 末尾加：
```python
# 同步产品线
self.root.after(300, self._sync_schedule_products)
```

---

### Task 4: 验证并重建 exe

- [ ] **Step 1: 验证语法**

```bash
cd /d D:\Users\Desktop\网络热点搜集
python -c "import py_compile; py_compile.compile('social_monitor_gui.py', doraise=True); print('OK')"
```

- [ ] **Step 2: 重建 exe**

```bash
cd /d D:\Users\Desktop\网络热点搜集
pyinstaller 社交监控工具.spec --clean
```

- [ ] **Step 3: 复制 exe**

```powershell
Copy-Item "D:\Users\Desktop\网络热点搜集\dist\社交监控工具.exe" "D:\Users\Desktop\网络热点搜集\社交监控工具.exe" -Force
```

- [ ] **Step 4: 提交代码**

```bash
cd /d D:\Users\Desktop\网络热点搜集
git add -A
git commit -m "feat: 定时任务tab实现-支持每日/每周+热搜/关键词/账号三功能"
git push
```
