# 微博智搜回答 + 三榜合并 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 改造微博热搜脚本，采智搜回答替代微博评论；新增文娱榜；三榜合并输出。

**Architecture:** weibo_hot_search.py 加 board 参数支持热搜/文娱双入口，`_fetch_topic_detail` 改为找智搜回答。hot_search.py 扩为跑三个榜单。notify 和 GUI 同步更新。

**Tech Stack:** Python, Playwright, asyncio, Pydantic

---

### Task 1: 重构 weibo_hot_search.py 模型和入口

**Files:**
- Modify: `scripts/weibo_hot_search.py:1-462`

- [ ] **Step 1: 替换数据模型**

```python
class ZhishouAnswer(BaseModel):
    """智搜回答"""
    text: str = Field(description="智搜回答正文")
    expanded: str = Field(default="", description="点击「查看更多」后展开的补充内容")
    source_url: str = Field(default="", description="aisearch 页面 URL")

class TopicDetail(BaseModel):
    """热搜/文娱话题详情"""
    rank: int = Field(description="排名")
    title: str = Field(description="热搜词")
    hot_value: str = Field(description="热度标识（热/爆/沸/新/荐等）")
    topic_url: str = Field(description="话题搜索链接")
    board: str = Field(default="hot", description="hot | entertainment")
    zhishou_answer: ZhishouAnswer | None = Field(default=None, description="智搜回答")
```

删除 `TopicPost` 整个类和 `CommentItem` 的 import，改为从 common import 只保留需要的。

- [ ] **Step 2: 修改 import 行**

```python
from common import kill_edge, launch_browser, get_edge_user_data, write_output, random_delay, wait_for_login
```
（去掉 `CommentItem`）

- [ ] **Step 3: 修改 `scrape_hot_search()` 签名和榜单入口**

```python
async def scrape_hot_search(
    limit: int = 10,
    board: str = "hot",
    headless: bool = True,
) -> list[TopicDetail]:
```

在函数内用 board 参数决定入口 URL：
```python
BOARD_URLS = {
    "hot": "https://weibo.com/hot/search",
    "entertainment": "https://weibo.com/hot/entertainment",
}
entry_url = BOARD_URLS.get(board, BOARD_URLS["hot"])
print(f"正在打开{'热搜榜' if board == 'hot' else '文娱榜'}: {entry_url}", file=sys.stderr)
await page.goto(entry_url, wait_until="domcontentloaded", timeout=30000)
```

- [ ] **Step 4: 修改榜单提取后调用 `_fetch_topic_detail` 的参数**

```python
topic = await _fetch_topic_detail(page, item, board=board)
```

- [ ] **Step 5: 修改 `main()` 函数，替换 `--top-posts` 和 `--top-comments` 为 `--board`**

```python
parser.add_argument("--limit", type=int, default=10, help="采集数量上限（默认 10）")
parser.add_argument("--board", default="hot",
                    choices=["hot", "entertainment", "both"],
                    help="榜单类型: hot=热搜, entertainment=文娱, both=两者（默认 hot）")
parser.add_argument("--visible", action="store_true", help="显示浏览器窗口")
parser.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径")
```

main() 逻辑加 board="both" 的分支：
```python
if args.board == "both":
    results = []
    for b in ("hot", "entertainment"):
        batch = asyncio.run(scrape_hot_search(limit=args.limit, board=b, headless=not args.visible))
        results.extend(batch)
        if b == "hot":
            import time, random
            time.sleep(random.uniform(3, 6))
else:
    results = asyncio.run(scrape_hot_search(limit=args.limit, board=args.board, headless=not args.visible))
```

输出格式中 `topics` 每个 topic 保留 `board` 字段。

- [ ] **Step 6: 确认改动后文件保存**

---

### Task 2: 实现智搜回答采集（改写 `_fetch_topic_detail`）

**Files:**
- Modify: `scripts/weibo_hot_search.py:195-367`

现有 `_fetch_topic_detail` 去话题搜索页 → 采集热门微博 → 进详情页拿评论。改为：去搜索页 → 找智搜回答 → 进 aisearch 页面 → 拿回答。

- [ ] **Step 1: 删除 `_extract_comments()` 函数**

删除整个 `_extract_comments` 方法（约 370-428 行）。

- [ ] **Step 2: 重写 `_fetch_topic_detail()`**

```python
async def _fetch_topic_detail(
    page, item: dict, board: str = "hot",
) -> TopicDetail | None:
    """进入热搜话题搜索页，找到智搜回答并采集其内容。"""
    title = item.get("title", "")
    rank = item.get("rank", 0)
    hot = item.get("hot", "")
    topic_url = item.get("url", "")

    # 统一导向热门排序的搜索页
    import re
    if topic_url and "xsort=hot" not in topic_url:
        q_match = re.search(r'[?&]q=([^&]+)', topic_url)
        if q_match:
            topic_url = f"https://s.weibo.com/weibo?q={q_match.group(1)}&xsort=hot"
        else:
            topic_url = f"https://s.weibo.com/weibo?q={title}&xsort=hot"
    elif not topic_url:
        topic_url = f"https://s.weibo.com/weibo?q={title}&xsort=hot"

    await page.goto(topic_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    # 滚动一下加载更多结果
    for _ in range(3):
        await page.evaluate("window.scrollBy(0, 1200)")
        await page.wait_for_timeout(1000)

    # 在 card-wrap 列表中找智搜回答
    zhishou_url = await page.evaluate("""
        () => {
            var wraps = document.querySelectorAll('.card-wrap');
            for (var w of wraps) {
                var txt = (w.textContent || '');
                // 用户名包含"智搜回答"或"智搜"
                var nameEl = w.querySelector('.name, [class*=name], [nick-name]');
                var name = nameEl ? (nameEl.textContent || '').trim() : '';
                if (name.indexOf('智搜') >= 0 || name.indexOf('智搜回答') >= 0 || txt.indexOf('智搜回答') >= 0) {
                    // 获取详情链接
                    var timeLink = w.querySelector('.from a');
                    if (timeLink) {
                        var href = timeLink.getAttribute('href') || '';
                        if (href && href.startsWith('//')) href = 'https:' + href;
                        if (href.indexOf('s.weibo.com') >= 0 || href.indexOf('aisearch') >= 0) return href;
                    }
                }
            }
            return '';
        }
    """)

    zhishou_answer = None
    if zhishou_url:
        print(f"    找到智搜回答: {zhishou_url[:80]}...", file=sys.stderr)
        try:
            zhishou_answer = await _fetch_zhishou_detail(page, zhishou_url)
        except Exception as e:
            print(f"    智搜详情页采集失败: {e}", file=sys.stderr)
    else:
        print(f"    未找到智搜回答", file=sys.stderr)

    return TopicDetail(
        rank=rank,
        title=title,
        hot_value=hot,
        topic_url=topic_url,
        board=board,
        zhishou_answer=zhishou_answer,
    )
```

- [ ] **Step 3: 新增 `_fetch_zhishou_detail()`**

```python
async def _fetch_zhishou_detail(page, zhishou_url: str) -> ZhishouAnswer:
    """进入 aisearch 页面，提取智搜回答正文，展开更多并提取。"""
    await page.goto(zhishou_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    # 提取回答正文
    result = await page.evaluate("""
        () => {
            var r = { text: '', expanded: '' };

            // 找主要内容区域
            var candidates = document.querySelectorAll(
                '.detail, .content, .text, [class*=answer], [class*=result], [class*=content]'
            );
            var best = '';
            for (var el of candidates) {
                var t = (el.textContent || '').trim();
                if (t.length > best.length) best = t;
            }
            r.text = best;

            // 尝试找"查看更多"按钮并获取其后续内容
            var moreBtn = document.querySelector('a[class*=more], a[class*=expand], [class*=more] a, button:contains(查看更多)');
            if (!moreBtn) {
                // 用文本匹配找"查看更多"链接
                var allLinks = document.querySelectorAll('a');
                for (var link of allLinks) {
                    if ((link.textContent || '').indexOf('查看更多') >= 0) {
                        moreBtn = link;
                        break;
                    }
                }
            }

            return r;
        }
    """)

    text = result.get("text", "")
    expanded = result.get("expanded", "")

    # 尝试点击"查看更多"（JS click，不走 DOM 文本匹配）
    try:
        more_clicked = await page.evaluate("""
            () => {
                var links = document.querySelectorAll('a');
                for (var link of links) {
                    if ((link.textContent || '').indexOf('查看更多') >= 0) {
                        link.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        if more_clicked:
            await page.wait_for_timeout(2000)
            # 点击展开后再提取一次完整内容
            expanded_text = await page.evaluate("""
                () => {
                    var candidates = document.querySelectorAll(
                        '.detail, .content, .text, [class*=answer], [class*=result], [class*=content]'
                    );
                    var best = '';
                    for (var el of candidates) {
                        var t = (el.textContent || '').trim();
                        if (t.length > best.length && t !== arguments[0]) best = t;
                    }
                    return best;
                }
            """, text)
            if expanded_text and expanded_text != text:
                expanded = expanded_text
    except Exception:
        pass

    return ZhishouAnswer(
        text=text[:5000],
        expanded=expanded[:5000] if expanded else "",
        source_url=zhishou_url,
    )
```

- [ ] **Step 4: 确认改动后文件保存**

---

### Task 3: 更新 notify_feishu.py 的微博热搜卡片

**Files:**
- Modify: `notify/notify_feishu.py:145-223`

- [ ] **Step 1: 更新 `_build_hot_search()`**

改为展示智搜回答内容，不再显示微博帖子和评论：

```python
def _build_hot_search(data: dict, collected_at: str) -> dict:
    topics = data.get("topics", [])
    board = data.get("board", "hot")
    title = f"🔥 {'微博热搜榜' if board == 'hot' else '微博文娱榜'} ({collected_at})" if board else f"🔥 微博热搜 ({collected_at})"
    elements = []

    for t in topics[:15]:
        rank = t.get("rank", "?")
        title_text = t.get("title", "")
        hot = t.get("hot_value", "")
        badge = f" **[{hot}]**" if hot else ""
        answer = t.get("zhishou_answer") or {}
        answer_text = (answer.get("text", "") or "")[:200]
        answer_line = f"\n> 🤖 {answer_text}" if answer_text else ""
        elements.append(_md(f"**#{rank} {title_text}**{badge}{answer_line}"))
        elements.append(_hr())

    elements.append(_md(f"🕐 采集时间: {collected_at}"))
    return _card_template(title, elements, "red")
```

- [ ] **Step 2: 更新 `_build_merged_hot()`**

新增微博文娱榜区块展示，和微博热搜并列：

```python
def _build_merged_hot(data: dict, collected_at: str) -> dict:
    platforms = data.get("platforms", [])
    title = f"🔥 全平台热搜榜 ({collected_at})"
    elements = []

    # 找各平台数据
    douyin = next((p for p in platforms if p.get("platform") == "douyin"), None)
    weibo_hot = next((p for p in platforms if p.get("platform") == "weibo" and p.get("board") == "hot"), None)
    weibo_ent = next((p for p in platforms if p.get("platform") == "weibo" and p.get("board") == "entertainment"), None)

    # 抖音
    if douyin:
        dy_topics = douyin.get("topics", [])
        if dy_topics:
            elements.append(_md("**🎵 抖音热榜**"))
            for t in dy_topics[:15]:
                rank = t.get("rank", "?")
                title_text = t.get("title", "")
                hot = t.get("hot_value", "")
                badge = t.get("hot_badge", "")
                badge_str = f" **[{badge}]**" if badge else ""
                hot_str = f" ({hot})" if hot else ""
                elements.append(_md(f"**#{rank} {title_text}**{badge_str}{hot_str}"))
            elements.append(_hr())

    # 微博热搜
    if weibo_hot:
        wb_topics = weibo_hot.get("topics", [])
        if wb_topics:
            elements.append(_md("**🔥 微博热搜**"))
            for t in wb_topics[:15]:
                rank = t.get("rank", "?")
                title_text = t.get("title", "")
                hot = t.get("hot_value", "")
                badge = f" **[{hot}]**" if hot else ""
                answer = t.get("zhishou_answer") or {}
                answer_text = (answer.get("text", "") or "")[:150]
                answer_line = f"\n> 🤖 {answer_text}" if answer_text else ""
                elements.append(_md(f"**#{rank} {title_text}**{badge}{answer_line}"))
            elements.append(_hr())

    # 微博文娱
    if weibo_ent:
        wb_topics = weibo_ent.get("topics", [])
        if wb_topics:
            elements.append(_md("**🎬 微博文娱榜**"))
            for t in wb_topics[:15]:
                rank = t.get("rank", "?")
                title_text = t.get("title", "")
                hot = t.get("hot_value", "")
                badge = f" **[{hot}]**" if hot else ""
                answer = t.get("zhishou_answer") or {}
                answer_text = (answer.get("text", "") or "")[:150]
                answer_line = f"\n> 🤖 {answer_text}" if answer_text else ""
                elements.append(_md(f"**#{rank} {title_text}**{badge}{answer_line}"))
            elements.append(_hr())

    if not elements:
        elements.append(_md("(未采集到数据)"))

    elements.append(_md(f"🕐 采集时间: {collected_at}"))
    return _card_template(title, elements, "red")
```

---

### Task 4: 更新 notify_agent.py 的摘要

**Files:**
- Modify: `notify/notify_agent.py`

- [ ] **Step 1: 更新 `build_summary()` 中的微博热搜分支**

在 `"platforms" in data` 分支中，对 weibo 平台显示智搜回答：

```python
if platform == "weibo":
    for t in topics[:20]:
        rank = t.get("rank", "?")
        title = t.get("title", "")
        hot = t.get("hot_value", "")
        badge = t.get("hot_badge", "") or ""
        hot_str = f"({hot})" if hot else ""
        badge_str = f"[{badge}]" if badge else ""
        answer = t.get("zhishou_answer") or {}
        answer_text = (answer.get("text", "") or "")[:150]
        answer_line = f"\n  🤖 {answer_text}" if answer_text else ""
        lines.append(f"#{rank} {title} {hot_str}{badge_str}{answer_line}")
```

其他 `douyin` 分支不变。

- [ ] **Step 2: 在 `"_build_merged_hot"` 类函数中同步飞书卡片的显示**

---

### Task 5: 更新 hot_search.py（合并脚本）

**Files:**
- Modify: `scripts/hot_search.py`

- [ ] **Step 1: 修改参数，去掉 `--weibo-posts` 和 `--weibo-comments`，新增 `--weibo-board`**

```python
parser.add_argument("--weibo-limit", type=int, default=10, help="微博热搜数量（默认 10）")
parser.add_argument("--weibo-board", default="both",
                    choices=["hot", "entertainment", "both"],
                    help="微博榜单: hot=热搜, entertainment=文娱, both=两者（默认 both）")
parser.add_argument("--douyin-limit", type=int, default=10, help="抖音热榜数量（默认 10）")
```

- [ ] **Step 2: 修改微博采集段改为跑两个榜单**

```python
# ── 2. 微博热搜/文娱 ──────────────────────────────
weibo_results = []
wb = importlib.import_module("weibo_hot_search")
boards_to_run = ["hot", "entertainment"] if args.weibo_board == "both" else [args.weibo_board]

for b in boards_to_run:
    board_name = "热搜榜" if b == "hot" else "文娱榜"
    print(f"▶ 阶段 2：采集微博{board_name}", file=sys.stderr)
    try:
        batch = asyncio.run(wb.scrape_hot_search(
            limit=weibo_limit,
            board=b,
            headless=headless,
        ))
        for t in batch:
            t.board = b  # 确保 board 字段正确
        weibo_results.extend(batch)
        print(f"  微博{board_name}完成：{len(batch)} 条", file=sys.stderr)
    except Exception as e:
        print(f"  ❌ 微博{board_name}采集失败: {e}", file=sys.stderr)

    if len(boards_to_run) > 1 and b == boards_to_run[0]:
        delay = random.uniform(3, 6)
        print(f"  ⏳ 榜单切换间隔（等待 {delay:.1f}s）", file=sys.stderr)
        import time
        time.sleep(delay)

# 按榜单分组输出
for b in boards_to_run:
    board_results = [t for t in weibo_results if t.board == b]
    board_name = "热搜榜" if b == "hot" else "文娱榜"
    weibo_output = {
        "platform": "weibo",
        "board": b,
        "total_topics": len(board_results),
        "topics": [r.model_dump(mode="json") for r in board_results],
    }
    platforms_data.append(weibo_output)
```

- [ ] **Step 3: 删除 `--weibo-posts` 和 `--weibo-comments` 相关引用**

---

### Task 6: 更新 social_monitor_gui.py 热搜 Tab

**Files:**
- Modify: `social_monitor_gui.py`

- [ ] **Step 1: 在热搜 tab 中，把平台选择从 [微博/抖音/合并] 改为 [微博热搜/微博文娱/抖音/合并]**

找到 `_build_tab_hot` 中的 `ttk.Radiobutton` 代码块（约 270-290 行），改为：

```python
self.hot_platform = tk.StringVar(value="weibo_hot")
ttk.Radiobutton(r0, text="微博热搜", variable=self.hot_platform,
                value="weibo_hot").pack(side="left", padx=(0, 6))
ttk.Radiobutton(r0, text="微博文娱", variable=self.hot_platform,
                value="weibo_ent").pack(side="left", padx=(0, 6))
ttk.Radiobutton(r0, text="抖音热榜", variable=self.hot_platform,
                value="douyin").pack(side="left", padx=(0, 6))
ttk.Radiobutton(r0, text="合并模式", variable=self.hot_platform,
                value="merged").pack(side="left")
```

- [ ] **Step 2: 修改 `_run_hot()` 方法**

```python
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
        cmd += ["--board", "hot"]
    elif platform == "weibo_ent":
        cmd += ["--board", "entertainment"]

    cmd += ["--limit", str(limit)]
    if visible:
        cmd.append("--visible")

    self._run_script_common("hot", cmd, self.hot_fs.get(), self.hot_agent.get())
```

---

### Task 7: 重建 exe 并验证

**Files:**
- Build: 社交监控工具.spec

- [ ] **Step 1: 验证 Python 环境直接运行**

```bash
cd /d D:\Users\Desktop\网络热点搜集
python scripts/weibo_hot_search.py --limit 3 --board hot --visible
```
验证：浏览器打开热搜榜 → 进入话题页 → 找到智搜回答 → 采集内容
检查 JSON 输出是否包含 `zhishou_answer` 字段。

```bash
python scripts/weibo_hot_search.py --limit 3 --board entertainment --visible
```
验证文娱榜同样流程。

```bash
python scripts/hot_search.py --weibo-limit 3 --douyin-limit 3 --visible
```
验证合并模式输出格式。

- [ ] **Step 2: 重建 exe**

```bash
cd /d D:\Users\Desktop\网络热点搜集
pyinstaller 社交监控工具.spec --clean
```

- [ ] **Step 3: 复制 exe 到桌面目录**

```powershell
Copy-Item "D:\Users\Desktop\网络热点搜集\dist\社交监控工具.exe" "D:\Users\Desktop\网络热点搜集\社交监控工具.exe" -Force
Remove-Item "D:\Users\Desktop\网络热点搜集\dist" -Recurse -Force
Remove-Item "D:\Users\Desktop\网络热点搜集\build" -Recurse -Force
```

- [ ] **Step 4: 从 GUI 测试**

打开 exe → 热搜 tab → 分别测试微博热搜、微博文娱、合并模式 → 确认飞书发送正常
