# 多规则定时任务 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将单频率定时任务改为多条独立规则的调度系统，每条规则独立配置动作、星期、时间、发Agent

**Architecture:** 规则持久化到 `schedule_rules.json`，GUI 内 polling 线程遍历所有 enabled 规则，到点执行。每条规则有 `last_run_date` 防重复

**Tech Stack:** Python tkinter, threading, datetime, uuid, json

---

### Task 1: 替换定时任务 UI 为多规则版

**Files:**
- Modify: `social_monitor_gui.py:551-656` (替换 `_build_tab_schedule`)

将整个 `_build_tab_schedule` 替换为新版，包含：
- 总开关（启停所有规则）
- 添加规则面板（名称 + 动作下拉框 + 动态参数区 + 星期多选 + 时间 + 添加按钮）
- 已设规则列表（可滚动、每行含启用/禁用、立即执行、删除）
- 下次执行时间和日志区

- [ ] **Step 1: 添加数据文件路径常量**

在 `__init__` 中 `self.keywords_file` 后面添加：

```python
self.schedule_file = os.path.join(BASE_DIR, "schedule_rules.json")
self.rules = []  # list[ScheduleRule dict]
self._schedule_running = False
```

- [ ] **Step 2: 替换 `_build_tab_schedule` 方法**

```python
def _build_tab_schedule(self, nb):
    f = self._tab_frame(nb, "⏰ 定时任务")

    # 总开关
    top_frame = ttk.Frame(f, style="TFrame")
    top_frame.pack(fill="x", padx=8, pady=(4, 0))
    self.sch_master_enabled = tk.BooleanVar(value=False)
    ttk.Checkbutton(top_frame, text="开启定时轮询", variable=self.sch_master_enabled,
                    style="Bold.TCheckbutton", command=self._on_schedule_master_toggle).pack(side="left")
    self.sch_start_btn = ttk.Button(top_frame, text="▶  启动轮询", style="Accent.TButton",
                                    command=self._toggle_schedule, width=14)
    self.sch_start_btn.pack(side="right")
    self.sch_next_label = ttk.Label(top_frame, text="", font=FONT_SM, foreground=TEXT_SECONDARY)
    self.sch_next_label.pack(side="right", padx=(8, 0))

    # ── 添加规则 ──
    cfg = self._card_frame(f, "添加规则")

    r0 = ttk.Frame(cfg, style="Card.TLabelframe")
    r0.pack(fill="x", pady=(4, 0))
    ttk.Label(r0, text="规则名称:").pack(side="left", padx=(0, 4))
    self.sch_new_name = tk.StringVar()
    ttk.Entry(r0, textvariable=self.sch_new_name, width=20).pack(side="left", padx=(0, 16))
    ttk.Label(r0, text="动作:").pack(side="left", padx=(0, 4))
    self.sch_new_action = tk.StringVar(value="hot")
    ttk.Combobox(r0, textvariable=self.sch_new_action, values=["hot", "keyword", "account"],
                 state="readonly", width=12).pack(side="left")
    ttk.Button(r0, text="➕ 添加规则", style="Accent.TButton",
               command=self._add_schedule_rule, width=12).pack(side="right", padx=(8, 0))

    # 动态参数区
    self.sch_params_frame = ttk.Frame(cfg, style="Card.TLabelframe")
    self.sch_params_frame.pack(fill="x", pady=(2, 0))
    self._rebuild_schedule_params()

    # 动作切换时重建参数
    self.sch_new_action.trace_add("write", lambda *a: self._rebuild_schedule_params())

    # 星期 + 时间
    r_week = ttk.Frame(cfg, style="Card.TLabelframe")
    r_week.pack(fill="x", pady=(2, 0))
    ttk.Label(r_week, text="星期:").pack(side="left", padx=(0, 6))
    self.sch_new_week_vars = {}
    weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
    for i, w in enumerate(weekday_names):
        self.sch_new_week_vars[i] = tk.BooleanVar(value=False)
        ttk.Checkbutton(r_week, text=w, variable=self.sch_new_week_vars[i]).pack(side="left", padx=2)
    ttk.Label(r_week, text="  时间:").pack(side="left", padx=(12, 4))
    self.sch_new_hour = tk.StringVar(value="09")
    self.sch_new_min = tk.StringVar(value="00")
    ttk.Spinbox(r_week, from_=0, to=23, textvariable=self.sch_new_hour, width=3, format="%02.0f").pack(side="left")
    ttk.Label(r_week, text=":").pack(side="left")
    ttk.Spinbox(r_week, from_=0, to=59, textvariable=self.sch_new_min, width=3, format="%02.0f").pack(side="left")

    # ── 规则列表 ──
    list_frame = self._card_frame(f, "已设规则")
    self.sch_list_canvas = tk.Canvas(list_frame, bg=CARD_BG, highlightthickness=0, height=180)
    scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.sch_list_canvas.yview)
    self.sch_list_inner = ttk.Frame(self.sch_list_canvas, style="Card.TLabelframe")
    self.sch_list_inner.bind("<Configure>", lambda e: self.sch_list_canvas.configure(scrollregion=self.sch_list_canvas.bbox("all")))
    self.sch_list_canvas.create_window((0, 0), window=self.sch_list_inner, anchor="nw")
    self.sch_list_canvas.configure(yscrollcommand=scrollbar.set)
    self.sch_list_canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # 日志
    self._make_log_area(f, "schedule")

    # 加载已存规则并刷新列表
    self._load_schedule_rules()
```

- [ ] **Step 3: 新增 `_rebuild_schedule_params` 方法**

```python
def _rebuild_schedule_params(self):
    """根据动作类型重建动态参数区"""
    for w in self.sch_params_frame.winfo_children():
        w.destroy()
    action = self.sch_new_action.get()

    if action == "hot":
        ttk.Label(self.sch_params_frame, text="平台:").pack(side="left", padx=(0, 4))
        self.sch_new_hot_platform = tk.StringVar(value="merged")
        ttk.Combobox(self.sch_params_frame, textvariable=self.sch_new_hot_platform,
                     values=["weibo_hot", "weibo_ent", "douyin", "merged"],
                     state="readonly", width=10).pack(side="left", padx=(0, 12))
        ttk.Label(self.sch_params_frame, text="数量:").pack(side="left", padx=(0, 4))
        self.sch_new_hot_limit = tk.StringVar(value="15")
        ttk.Spinbox(self.sch_params_frame, from_=1, to=50, textvariable=self.sch_new_hot_limit,
                    width=4).pack(side="left", padx=(0, 12))
        self.sch_new_send_agent = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.sch_params_frame, text="发Agent",
                        variable=self.sch_new_send_agent).pack(side="left")

    elif action == "keyword":
        ttk.Label(self.sch_params_frame, text="产品线:").pack(side="left", padx=(0, 4))
        self.sch_new_kw_product = tk.StringVar()
        combo = ttk.Combobox(self.sch_params_frame, textvariable=self.sch_new_kw_product,
                             state="readonly", width=12)
        combo.pack(side="left", padx=(0, 12))
        # 同步产品线
        if hasattr(self, '_keywords_data') and self._keywords_data:
            combo["values"] = [p["name"] for p in self._keywords_data]
            if not self.sch_new_kw_product.get():
                self.sch_new_kw_product.set([p["name"] for p in self._keywords_data][0])
        ttk.Label(self.sch_params_frame, text="每关键词数:").pack(side="left", padx=(0, 4))
        self.sch_new_kw_per = tk.StringVar(value="5")
        ttk.Spinbox(self.sch_params_frame, from_=1, to=20, textvariable=self.sch_new_kw_per,
                    width=4).pack(side="left", padx=(0, 12))
        self.sch_new_send_agent = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.sch_params_frame, text="发Agent",
                        variable=self.sch_new_send_agent).pack(side="left")

    elif action == "account":
        ttk.Label(self.sch_params_frame, text="URL文件:").pack(side="left", padx=(0, 4))
        self.sch_new_acc_file = tk.StringVar(value=self.urls_file)
        ttk.Entry(self.sch_params_frame, textvariable=self.sch_new_acc_file,
                  width=25).pack(side="left", padx=(0, 12))
        ttk.Label(self.sch_params_frame, text="数量:").pack(side="left", padx=(0, 4))
        self.sch_new_acc_limit = tk.StringVar(value="10")
        ttk.Spinbox(self.sch_params_frame, from_=1, to=50, textvariable=self.sch_new_acc_limit,
                    width=4).pack(side="left", padx=(0, 12))
        self.sch_new_send_agent = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.sch_params_frame, text="发Agent",
                        variable=self.sch_new_send_agent).pack(side="left")
```

- [ ] **Step 4: 新增 `_add_schedule_rule` 方法**

```python
def _add_schedule_rule(self):
    name = self.sch_new_name.get().strip()
    if not name:
        self._log("schedule", "⚠ 请输入规则名称", "orange")
        return
    weekdays = [i for i, var in self.sch_new_week_vars.items() if var.get()]
    if not weekdays:
        self._log("schedule", "⚠ 请至少勾选一个星期", "orange")
        return

    params = {}
    action = self.sch_new_action.get()
    if action == "hot":
        params = {"platform": self.sch_new_hot_platform.get(), "limit": int(self.sch_new_hot_limit.get())}
    elif action == "keyword":
        params = {"product_line": self.sch_new_kw_product.get(), "per_keyword": int(self.sch_new_kw_per.get())}
    elif action == "account":
        params = {"urls_file": self.sch_new_acc_file.get(), "limit": int(self.sch_new_acc_limit.get())}

    rule = {
        "id": str(__import__("uuid").uuid4()),
        "name": name,
        "enabled": True,
        "action_type": action,
        "params": params,
        "weekdays": weekdays,
        "time": f"{self.sch_new_hour.get()}:{self.sch_new_min.get()}",
        "send_agent": self.sch_new_send_agent.get(),
    }
    self.rules.append(rule)
    self._save_schedule_rules()
    self._refresh_schedule_list()
    self._log("schedule", f"✓ 已添加规则: {name}", "green")
    # 清空名称
    self.sch_new_name.set("")
```

- [ ] **Step 5: 新增 `_refresh_schedule_list` 方法**

```python
def _refresh_schedule_list(self):
    """刷新规则列表 UI"""
    for w in self.sch_list_inner.winfo_children():
        w.destroy()
    if not self.rules:
        ttk.Label(self.sch_list_inner, text="暂无规则，请在上方添加",
                  style="Hint.TLabel").pack(pady=20)
        return

    weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
    action_icons = {"hot": "🔥热搜", "keyword": "🔍关键词", "account": "📊账号监控"}

    for rule in self.rules:
        row = ttk.Frame(self.sch_list_inner, style="Card.TLabelframe")
        row.pack(fill="x", pady=2, padx=2)

        # 启用开关
        en_var = tk.BooleanVar(value=rule["enabled"])
        def _toggle_enabled(r=rule, v=en_var):
            r["enabled"] = v.get()
            self._save_schedule_rules()
        ttk.Checkbutton(row, variable=en_var, command=_toggle_enabled).pack(side="left", padx=(4, 4))

        # 名称 + 动作 + 时间
        wd_text = "".join(weekday_names[i] for i in sorted(rule["weekdays"]))
        agent_tag = "·发Agent" if rule["send_agent"] else ""
        info = f"{rule['name']}  {action_icons.get(rule['action_type'], '?')} {wd_text} {rule['time']}{agent_tag}"
        ttk.Label(row, text=info, font=FONT).pack(side="left", padx=(0, 8))

        # 上次执行
        last = rule.get("last_run", "")
        if last:
            status = rule.get("last_status", "")
            icon = "✓" if status == "ok" else "✗"
            ttk.Label(row, text=f"上次:{last} {icon}", font=FONT_SM,
                      foreground=TEXT_SECONDARY).pack(side="left", padx=(8, 0))

        # 按钮
        ttk.Button(row, text="▶", command=lambda r=rule: self._run_single_rule(r),
                   width=3).pack(side="right", padx=2)
        ttk.Button(row, text="🗑", command=lambda r=rule: self._delete_schedule_rule(r),
                   width=3).pack(side="right", padx=2)
```

- [ ] **Step 6: 新增 `_delete_schedule_rule`**

```python
def _delete_schedule_rule(self, rule):
    if rule in self.rules:
        self.rules.remove(rule)
        self._save_schedule_rules()
        self._refresh_schedule_list()
        self._log("schedule", f"已删除规则: {rule['name']}", "yellow")
```

- [ ] **Step 7: 新增 `_run_single_rule`**

```python
def _run_single_rule(self, rule):
    """立即执行一条规则（在后台线程中）"""
    import threading as _th
    self._log("schedule", f"▶ 立即执行: {rule['name']}", "cyan")
    _th.Thread(target=lambda: self._execute_rule(rule), daemon=True).start()
```

- [ ] **Step 8: 新增 `_on_schedule_master_toggle`**

```python
def _on_schedule_master_toggle(self):
    if not self.sch_master_enabled.get() and self._schedule_running:
        self._toggle_schedule()  # 关掉轮询
```

---

### Task 2: 替换调度逻辑 + 持久化

**Files:**
- Modify: `social_monitor_gui.py` (替换 `_sync_schedule_products` 及之后所有调度方法)

- [ ] **Step 1: 新增 `_load_schedule_rules`**

```python
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
```

- [ ] **Step 2: 新增 `_save_schedule_rules`**

```python
def _save_schedule_rules(self):
    with open(self.schedule_file, "w", encoding="utf-8") as f:
        json.dump(self.rules, f, ensure_ascii=False, indent=2)
```

- [ ] **Step 3: 替换 `_toggle_schedule`**

```python
def _toggle_schedule(self):
    if self._schedule_running:
        self._schedule_running = False
        self.sch_start_btn.config(text="▶  启动轮询")
        self.sch_next_label.config(text="")
        self._log("schedule", "■ 定时轮询已停止", "red")
    else:
        self._schedule_running = True
        self.sch_start_btn.config(text="■  停止轮询")
        self._log("schedule", "▶ 定时轮询已启动", "green")
        self._update_next_run_label()
        self._schedule_loop()
```

- [ ] **Step 4: 替换 `_update_next_run_label`（原 `_schedule_next_time`）**

```python
def _update_next_run_label(self):
    """计算所有规则中最近的下次执行时间"""
    import datetime as dt
    now = dt.datetime.now()
    nearest = None
    for rule in self.rules:
        if not rule.get("enabled", False):
            continue
        try:
            h, m = rule["time"].split(":")
            hour, minute = int(h), int(m)
        except (ValueError, KeyError):
            continue
        last_date = rule.get("last_run_date", "")
        for offset in range(0, 8):
            check = now + dt.timedelta(days=offset)
            if check.weekday() not in rule.get("weekdays", []):
                continue
            target = check.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                continue
            date_str = target.strftime("%Y-%m-%d")
            if date_str == last_date:
                continue
            if nearest is None or target < nearest:
                nearest = target
            break

    if nearest:
        weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
        wd = weekday_names[nearest.weekday()]
        self.sch_next_label.config(text=f"下次执行: {nearest.strftime('%m-%d %H:%M')} ({wd})")
    else:
        self.sch_next_label.config(text="(无待执行规则)")
```

- [ ] **Step 5: 替换 `_schedule_loop`**

```python
def _schedule_loop(self):
    if not self._schedule_running:
        return
    if not self.sch_master_enabled.get():
        self.root.after(30000, self._schedule_loop)
        return

    import datetime as dt
    now = dt.datetime.now()

    for rule in self.rules:
        if not rule.get("enabled", False):
            continue
        try:
            h, m = rule["time"].split(":")
            hour, minute = int(h), int(m)
        except (ValueError, KeyError):
            continue

        # 检查星期
        if now.weekday() not in rule.get("weekdays", []):
            continue
        # 检查时间
        if now.hour != hour or now.minute != minute:
            continue
        # 检查是否今日已执行
        today = now.strftime("%Y-%m-%d")
        if rule.get("last_run_date", "") == today:
            continue

        self._log("schedule", f"\n⏰ 到达执行时间，开始: {rule['name']}", "cyan")
        import threading as _th
        _th.Thread(target=lambda r=rule: self._execute_rule(r), daemon=True).start()

    self.root.after(30000, self._schedule_loop)
```

- [ ] **Step 6: 替换 `_execute_scheduled_tasks` 为 `_execute_rule`**

```python
def _execute_rule(self, rule):
    """执行单条规则"""
    import datetime as dt
    try:
        action = rule["action_type"]
        params = rule.get("params", {})
        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

        cmd = None
        if action == "hot":
            platform = params.get("platform", "merged")
            limit = str(params.get("limit", 15))
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

        elif action == "keyword":
            product = params.get("product_line", "")
            per_kw = str(params.get("per_keyword", 5))
            keywords = []
            if product and hasattr(self, '_keywords_data'):
                pl = next((p for p in self._keywords_data if p["name"] == product), None)
                if pl:
                    keywords = pl.get("keywords", [])[:5]
            if not keywords and hasattr(self, 'kw_checkboxes'):
                keywords = list(self.kw_checkboxes.keys())[:3]
            if keywords:
                cmd = [PYTHON, os.path.join(self.script_dir, "scripts", "keyword_search.py"),
                       "--keywords", ",".join(keywords),
                       "--platforms", "both",
                       "--per-keyword", per_kw]

        elif action == "account":
            limit = str(params.get("limit", 10))
            selected = []
            if hasattr(self, 'acc_url_vars'):
                selected = [identifier for _, identifier, var in self.acc_url_vars if var.get()]
            if selected:
                cmd = [PYTHON, os.path.join(self.script_dir, "scripts", "competitor_monitor.py"),
                       "--urls"] + selected + ["--limit", limit]

        if cmd:
            self._run_script_common("schedule", cmd, False, rule.get("send_agent", True))
            rule["last_run"] = now
            rule["last_run_date"] = dt.datetime.now().strftime("%Y-%m-%d")
            rule["last_status"] = "ok"
        else:
            self._log("schedule", f"  ⚠ {rule['name']}: 无可用参数，跳过", "orange")

    except Exception as e:
        self._log("schedule", f"  ✗ {rule['name']}: {e}", "red")
        rule["last_status"] = "fail"

    self._save_schedule_rules()
    self.root.after(0, self._refresh_schedule_list)
    self.root.after(0, self._update_next_run_label)
```

- [ ] **Step 7: 删除不再需要的旧方法**

移除以下方法（已全部被替换）：
- `_sync_schedule_products`
- `_schedule_next_time` (已替换为 `_update_next_run_label`)
- `_execute_scheduled_tasks` (已替换为 `_execute_rule`)

---

### Task 3: 验证并重建

- [ ] **Step 1: 验证语法**

Run:
```bash
D: && cd D:\Users\Desktop\网络热点搜集 && python -c "import py_compile; py_compile.compile('social_monitor_gui.py', doraise=True); print('OK')"
```
Expected: `OK`

- [ ] **Step 2: 重建 exe**

Run:
```bash
D: && cd D:\Users\Desktop\网络热点搜集 && pyinstaller 社交监控工具.spec --clean
```
Expected: Build complete

- [ ] **Step 3: 复制 exe**

Run:
```powershell
Copy-Item "D:\Users\Desktop\网络热点搜集\dist\社交监控工具.exe" "D:\Users\Desktop\网络热点搜集\社交监控工具.exe" -Force
```

- [ ] **Step 4: 提交代码**

Run:
```bash
cd /d D:\Users\Desktop\网络热点搜集 && git add -A && git commit -m "feat: 多规则定时任务-支持独立星期/时间/动作配置"
```
