# UI 重构 + 关键词搜索 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 GUI 为 Tab 布局 + 新增关键词搜索功能 + 抽取公共代码

**Architecture:** 先创建 common.py 提取重复代码并改造已有脚本，再创建 keywords.json + keyword_search.py 新功能，然后更新 notify 适配，最后重写 GUI。GUI 使用 ttk.Notebook 实现 Tab 布局，每个 Tab 独立配置/日志/进程。

**Tech Stack:** Python 3.12, Playwright, PyInstaller, tkinter/ttk

---

### Task 1: 创建 `scripts/common.py` 公共模块

**Files:**
- Create: `scripts/common.py`

- [ ] **Step 1: 写入 common.py**

`weibo_scraper.py` 的 `CommentItem` 和 `_kill_edge()` 代码已经过验证可以直接使用。`_launch_browser()` 取 weibo_scraper.py 版本（带重试 + 临时目录兜底）。新增 `write_output()`。

```python
"""
公共工具模块 - 浏览器启动 / Edge 管理 / 输出 / 数据模型
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pydantic import BaseModel, Field


class CommentItem(BaseModel):
    """单条评论"""
    user: str = Field(description="评论用户")
    content: str = Field(description="评论内容")
    likes: int = Field(description="评论点赞数")


def kill_edge():
    """关闭正在运行的 Edge 进程（User Data 被占用时 Playwright 无法启动）。"""
    try:
        result = subprocess.run(
            ["tasklist", "/fi", "imagename eq msedge.exe", "/nh"],
            capture_output=True, text=True, timeout=10
        )
        if "msedge.exe" in result.stdout:
            print("检测到 Edge 正在运行，正在关闭...", file=sys.stderr)
            subprocess.run(["taskkill", "/f", "/im", "msedge.exe"],
                           capture_output=True, timeout=10)
            print("Edge 已关闭", file=sys.stderr)
    except Exception:
        pass


async def launch_browser(p, headless: bool, user_data_dir: str, label: str = "app", **kwargs):
    """
    安全启动 Edge，如遇 User Data 被占用则自动杀进程重试。
    最终兜底：临时目录 + 非无头（需要用户手动登录）。
    Returns: (context, page)
    """
    from playwright._impl._errors import TargetClosedError

    for attempt in range(2):
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                channel="msedge",
                headless=headless,
                args=["--disable-sync"],
                viewport={"width": 1920, "height": 1080},
                **kwargs,
            )
            page = await context.new_page()
            return context, page
        except TargetClosedError:
            print(f"  Edge 启动失败（attempt {attempt+1}），正在关闭已有 Edge 进程...", file=sys.stderr)
            kill_edge()
            await asyncio.sleep(2)

    print(f"  使用临时用户目录启动 Edge（将弹出登录窗口）...", file=sys.stderr)
    tdir = tempfile.mkdtemp(prefix=f"{label}_")
    try:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=tdir,
            channel="msedge",
            headless=False,
            args=["--disable-sync"],
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()
        print("  请在浏览器窗口中登录", file=sys.stderr)
        return context, page
    except Exception:
        import shutil
        shutil.rmtree(tdir, ignore_errors=True)
        raise


def get_edge_user_data() -> str:
    """获取 Edge 用户数据目录路径。"""
    return os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data"
    )


def write_output(output: dict, output_path: str | None = None):
    """
    统一 JSON 输出。
    如果 output_path 为 None，写入临时文件然后打印到 stdout（供管道使用）。
    """
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"结果已保存到: {output_path}")
    else:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", delete=False
        )
        json.dump(output, tmp, ensure_ascii=False, indent=2)
        tmp.close()
        with open(tmp.name, "r", encoding="utf-8") as f:
            sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace")
            print(f.read())
        os.unlink(tmp.name)
```

- [ ] **Step 2: 验证 common.py 可导入**

```bash
cd "D:\Users\Desktop\网络热点搜集"
python -c "from scripts.common import CommentItem, kill_edge, get_edge_user_data, write_output; print('ok')"
```
Expected: prints "ok"

---

### Task 2: 创建 `keywords.json` 配置

**Files:**
- Create: `keywords.json`

- [ ] **Step 1: 写入 keywords.json**

```json
{
  "product_lines": [
    {
      "name": "气泡水",
      "brand": "元气森林",
      "keywords": ["职场整活", "蓝V", "热梗", "玩法", "官号", "本周热梗", "meme", "运营", "调饮", "挑战", "xx文学", "聚会", "朋友", "出门玩"]
    },
    {
      "name": "外星人",
      "brand": "元气森林",
      "keywords": ["抽象", "疯癫", "整活", "蓝V", "热梗", "玩法", "官号", "本周热梗", "meme", "运动", "搞笑", "反转", "挑战"]
    },
    {
      "name": "好自在",
      "brand": "元气森林",
      "keywords": ["养生", "照顾自己", "治愈日常", "一个人", "慢生活", "小确幸", "放松一刻", "内耗", "手工DIY", "独处时光"]
    }
  ]
}
```

---

### Task 3: 改造 `weibo_scraper.py` 使用 common 模块

**Files:**
- Modify: `scripts/weibo_scraper.py`

- [ ] **Step 1: 删除 CommentItem 定义**（改用 from common import CommentItem）

- [ ] **Step 2: 替换 _kill_edge / _launch_browser / get_edge_user_data** 为 common 模块调用

```python
# 顶部替换：
from scripts.common import CommentItem, kill_edge, launch_browser, get_edge_user_data, write_output

# 删除：
# - class CommentItem
# - def _kill_edge()
# - async def _launch_browser()
# - 本地的 edge_user_data 路径拼接

# 替换 _launch_browser 调用：
context, page = await launch_browser(p, headless=headless, user_data_dir=edge_user_data, label="weibo_scraper")

# 替换 edge_user_data 获取：
edge_user_data = get_edge_user_data()
```

- [ ] **Step 3: 替换 write_output 调用**

```python
# 原来 50 行的 if args.output / else / tempfile 代码替换为：
write_output(output, args.output)
```

- [ ] **Step 4: 验证**

```bash
cd "D:\Users\Desktop\网络热点搜集"
python -c "from scripts.weibo_scraper import scrape_profile; print('import ok')"
```
Expected: prints "import ok"

---

### Task 4: 改造 `weibo_hot_search.py` 使用 common 模块

**Files:**
- Modify: `scripts/weibo_hot_search.py`

- [ ] **Step 1: 替换 import 和删除重复代码**

同上，将 `CommentItem`、`_kill_edge()`、`_launch_browser()`、`edge_user_data` 路径拼接、末尾 `if args.output / else` 全部替换为 common 模块。

```python
# 顶部：
from scripts.common import CommentItem, kill_edge, launch_browser, get_edge_user_data, write_output

# main() 输出替换为：
write_output(output, args.output)
```

- [ ] **Step 2: 验证**

```bash
cd "D:\Users\Desktop\网络热点搜集"
python -c "from scripts.weibo_hot_search import scrape_hot_search; print('import ok')"
```

---

### Task 5: 改造 `douyin_hot_search.py` 使用 common 模块

**Files:**
- Modify: `scripts/douyin_hot_search.py`

- [ ] **Step 1: 替换 import 和删除重复代码**

同上，替换 `_kill_edge()`、`_launch_browser()`、末尾输出。

注意：douyin_hot_search.py 没有自己的 CommentItem 类（HotItem 是特有的），所以只需替换浏览器相关函数。

```python
# 顶部：
from scripts.common import kill_edge, launch_browser, get_edge_user_data, write_output

# main() 输出替换为：
write_output(output, args.output)
```

- [ ] **Step 2: 验证**

```bash
cd "D:\Users\Desktop\网络热点搜集"
python -c "from scripts.douyin_hot_search import scrape_hot_search; print('import ok')"
```

---

### Task 6: 改造 `xiaohongshu_scraper.py` 使用 common 模块 + 加 Edge 重启逻辑

**Files:**
- Modify: `scripts/xiaohongshu_scraper.py`

- [ ] **Step 1: 替换 CommentItem import，删除本地定义**

- [ ] **Step 2: 用 common.launch_browser 替换直接启动**

当前 xiaohongshu_scraper.py 直接调用 `context = await p.chromium.launch_persistent_context(...)` 无重试。替换为 `common.launch_browser()` 获得杀进程+重试能力。

```python
# 顶部：
from scripts.common import CommentItem, launch_browser, get_edge_user_data, write_output

# 替换启动部分：
edge_user_data = get_edge_user_data()
context, page = await launch_browser(p, headless=headless, user_data_dir=edge_user_data, label="xiaohongshu")
```

- [ ] **Step 3: 末尾输出替换为 write_output**

```python
write_output(output, args.output)
```

- [ ] **Step 4: 验证**

```bash
cd "D:\Users\Desktop\网络热点搜集"
python -c "from scripts.xiaohongshu_scraper import scrape_profile; print('import ok')"
```

---

### Task 7: 创建 `scripts/keyword_search.py` — 关键词搜索脚本

**Files:**
- Create: `scripts/keyword_search.py`

- [ ] **Step 1: 写入完整的 keyword_search.py**

```python
"""
关键词搜索采集脚本
在微博和小红书按关键词搜索内容，提取互动数据。

用法：
    python keyword_search.py --keywords 职场整活,蓝V --platforms both
    python keyword_search.py --keywords 养生 --platforms xiaohongshu --deep
    python keyword_search.py --keywords 热梗 --platforms weibo --per-keyword 5 -o result.json
"""

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta
from urllib.parse import quote

from pydantic import BaseModel, Field
from playwright.async_api import async_playwright

from scripts.common import (
    CommentItem, kill_edge, launch_browser,
    get_edge_user_data, write_output
)


class SearchItem(BaseModel):
    """单条搜索结果"""
    title: str = Field(default="", description="标题（如有）")
    text: str = Field(default="", description="正文/摘要")
    author: str = Field(default="", description="发布者")
    likes: int = Field(default=-1, description="点赞数")
    comments: int = Field(default=-1, description="评论数")
    collects: int = Field(default=-1, description="收藏数")
    reposts: int = Field(default=-1, description="转发数")
    url: str = Field(default="", description="内容链接")
    time: str = Field(default="", description="发布时间")
    comments_list: list[CommentItem] = Field(default_factory=list, description="评论列表")
    platform: str = Field(default="", description="来源平台")


async def search_weibo(
    page, keyword: str, per_keyword: int, deep: bool, max_comments: int
) -> list[dict]:
    """
    在微博搜索关键词，返回搜索结果列表。
    """
    encoded = quote(keyword)
    search_url = f"https://s.weibo.com/weibo?q={encoded}&xsort=hot"
    print(f"  微博搜索: {keyword}", file=sys.stderr)

    await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(5000)

    # 滚动加载
    for _ in range(3):
        await page.evaluate("window.scrollBy(0, 1000)")
        await page.wait_for_timeout(1000)

    items = await page.evaluate(f"""
        (maxItems) => {{
            var wraps = document.querySelectorAll('.card-wrap');
            var results = [];
            for (var i = 0; i < wraps.length && results.length < maxItems; i++) {{
                var w = wraps[i];
                if ((w.textContent || '').indexOf('广告') >= 0) continue;

                var txtEl = w.querySelector('.card-feed .content .txt');
                var text = txtEl ? (txtEl.textContent || '').trim() : '';

                var authorEl = w.querySelector('.card-feed .content .name');
                var author = authorEl ? (authorEl.textContent || '').trim() : '';

                var timeEl = w.querySelector('.from a');
                var detailUrl = '';
                if (timeEl) {{
                    var href = timeEl.getAttribute('href') || '';
                    if (href && href.startsWith('//')) href = 'https:' + href;
                    detailUrl = href;
                }}

                // 互动数
                var actEl = w.querySelector('.card-act');
                var actText = actEl ? (actEl.textContent || '').trim() : '';
                var reposts = -1, comments = -1, likes = -1;
                if (actText) {{
                    var nums = [];
                    for (var p of actText.split(/\\s+/)) {{
                        var n = parseInt(p.replace(/,/g, ''), 10);
                        if (!isNaN(n)) nums.push(n);
                    }}
                    if (nums.length > 0) reposts = nums[0];
                    if (nums.length > 1) comments = nums[1];
                    if (nums.length > 2) likes = nums[2];
                }}

                if (text.length > 10) {{
                    results.push({{
                        text: text, author: author, reposts: reposts,
                        comments: comments, likes: likes, url: detailUrl,
                        title: '', collects: -1
                    }});
                }}
            }}
            return results;
        }}
    """, per_keyword)

    return items


async def search_xiaohongshu(
    page, keyword: str, per_keyword: int, deep: bool, max_comments: int
) -> list[dict]:
    """
    在小红书搜索关键词，返回搜索结果列表。
    """
    encoded = quote(keyword)
    search_url = f"https://www.xiaohongshu.com/search_result?keyword={encoded}&source=web_search_result_notes"
    print(f"  小红书搜索: {keyword}", file=sys.stderr)

    await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(5000)

    # 滚动加载
    for _ in range(3):
        await page.evaluate("window.scrollBy(0, 1200)")
        await page.wait_for_timeout(1500)

    items = await page.evaluate(f"""
        (maxItems) => {{
            function parseCount(s) {{
                if (!s) return -1;
                s = s.replace(',', '');
                if (s.includes('万')) return Math.round(parseFloat(s) * 10000);
                var n = parseInt(s, 10);
                return isNaN(n) ? -1 : n;
            }}

            var cards = document.querySelectorAll('section.note-item');
            var results = [];
            for (var i = 0; i < cards.length && results.length < maxItems; i++) {{
                var card = cards[i];

                var coverLink = card.querySelector('a.cover');
                if (!coverLink) continue;
                var href = coverLink.getAttribute('href') || '';
                var url = href.startsWith('http') ? href : 'https://www.xiaohongshu.com' + href;

                var titleEl = card.querySelector('.title span, .footer .title');
                var title = titleEl ? (titleEl.textContent || '').trim() : '';

                var nums = [];
                var likeEl = card.querySelector('.like-wrapper .count');
                if (likeEl) nums.push(parseCount((likeEl.textContent || '').trim()));
                var bottom = card.querySelector('.card-bottom-wrapper');
                if (bottom && nums.length < 3) {{
                    var clone = bottom.cloneNode(true);
                    var authorA = clone.querySelector('a[href*="/user/"]');
                    if (authorA) authorA.remove();
                    var text = clone.textContent || '';
                    var found = text.match(/\\d+/g);
                    if (found) {{
                        for (var n of found) nums.push(parseInt(n, 10));
                    }}
                }}

                results.push({{
                    title: title, text: '', author: '',
                    likes: nums.length > 0 ? nums[0] : -1,
                    collects: nums.length > 1 ? nums[1] : -1,
                    comments: nums.length > 2 ? nums[2] : -1,
                    reposts: -1, url: url
                }});
            }}
            return results;
        }}
    """, per_keyword)

    return items


async def fetch_deep_detail(page, item: dict, max_comments: int, platform: str) -> dict:
    """进入内容详情页，提取完整正文和评论。"""
    url = item.get("url", "")
    if not url:
        return item

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)

        if platform == "weibo":
            # 提取完整正文
            full_text = await page.evaluate("""
                () => {
                    var candidates = document.querySelectorAll(
                        '[class*=_ogText_], [class*=_text_], [class*=_wbtext_]'
                    );
                    var best = '';
                    for (var el of candidates) {
                        var t = (el.textContent || '').trim();
                        if (t.length > best.length) best = t;
                    }
                    return best.length > 20 ? best : '';
                }
            """)
            if full_text:
                item["text"] = full_text

            # 评论
            if max_comments > 0:
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 1000)")
                    await page.wait_for_timeout(1000)

                cl = await page.evaluate(f"""
                    (maxC) => {{
                        var text = document.body.innerText || '';
                        var lines = text.split('\\\\n').filter(function(l){{return l.trim()}});
                        var commentStart = -1;
                        for (var i = 0; i < lines.length; i++) {{
                            if (lines[i] === '评论') {{ commentStart = i + 1; break; }}
                        }}
                        if (commentStart < 0) return [];
                        var idx = commentStart;
                        while (idx < lines.length && (lines[idx] === '按热度' || lines[idx] === '按时间')) idx++;
                        idx += 4;
                        var result = [];
                        var pendingUser = '', pendingContent = '', inContent = false;
                        for (var j = idx; j < lines.length; j++) {{
                            var l = lines[j];
                            if (l === '已加载全部评论' || l === '分享这条博文') break;
                            if (result.length >= maxC) break;
                            if (l.indexOf(':') === 0) {{
                                pendingContent = l.substring(1).trim(); inContent = true;
                            }} else if (/^\\\\d{{1,2}}-\\\\d{{1,2}}-\\\\d{{1,2}}/.test(l) || l.indexOf('发布于') >= 0 || l.indexOf('来自') >= 0) {{
                                if (inContent) {{ result.push({{user: pendingUser || '(未知)', content: pendingContent || '', likes: 0}}); pendingUser = ''; pendingContent = ''; inContent = false; }}
                            }} else if (!/^\\\\d+$/.test(l)) {{
                                if (inContent) {{ result.push({{user: pendingUser || '(未知)', content: pendingContent || '', likes: 0}}); pendingUser = ''; pendingContent = ''; }}
                                pendingUser = l; pendingContent = ''; inContent = false;
                            }}
                        }}
                        if (pendingUser && inContent) {{ result.push({{user: pendingUser, content: pendingContent || '', likes: 0}}); }}
                        return result;
                    }}
                """, max_comments)
                item["comments_list"] = [{"user": c["user"], "content": c["content"], "likes": c["likes"]} for c in cl]

        elif platform == "xiaohongshu":
            detail = await page.evaluate("""
                () => {
                    var result = { note_text: '' };
                    var candidates = document.querySelectorAll(
                        '.note-text, [class*="content"] [class*="text"], [class*="desc"]'
                    );
                    var best = '';
                    for (var el of candidates) {
                        var t = (el.textContent || '').trim();
                        if (t.length > best.length) best = t;
                    }
                    result.note_text = best;
                    return result;
                }
            """)
            if detail.get("note_text"):
                item["text"] = detail["note_text"]

            if max_comments > 0:
                await page.wait_for_timeout(2000)
                cl = await page.evaluate(f"""
                    (maxC) => {{
                        var items = document.querySelectorAll('.comments-container .parent-comment');
                        var result = [];
                        for (var i = 0; i < items.length && i < maxC; i++) {{
                            var c = items[i];
                            var nameEl = c.querySelector('.author .name');
                            var userName = nameEl ? nameEl.textContent.trim() : '';
                            var noteText = c.querySelector('.content .note-text');
                            var content = noteText ? noteText.textContent.trim() : '';
                            var likeNum = c.querySelector('.like-wrapper .count');
                            var likeText = likeNum ? likeNum.textContent.trim() : '';
                            var likes = 0;
                            if (likeText && likeText !== '赞') likes = parseInt(likeText, 10) || 0;
                            if (userName && content) result.push({{user: userName, content: content, likes: likes}});
                        }}
                        return result;
                    }}
                """, max_comments)
                item["comments_list"] = [{"user": c["user"], "content": c["content"], "likes": c["likes"]} for c in cl]

    except Exception as e:
        print(f"    详情页异常: {e}", file=sys.stderr)

    return item


async def search_keywords(
    keywords: list[str],
    platforms: list[str],
    per_keyword: int = 5,
    deep: bool = False,
    max_comments: int = 3,
    headless: bool = True,
) -> dict:
    """
    主入口：按关键词列表在各个平台搜索。
    返回合并后的数据结构。
    """
    results_by_platform = []

    async with async_playwright() as p:
        edge_user_data = get_edge_user_data()
        context, page = await launch_browser(p, headless=headless, user_data_dir=edge_user_data, label="keyword_search")

        try:
            for keyword in keywords:
                for platform in platforms:
                    if platform == "weibo":
                        raw = await search_weibo(page, keyword, per_keyword, deep, max_comments)
                    elif platform == "xiaohongshu":
                        raw = await search_xiaohongshu(page, keyword, per_keyword, deep, max_comments)
                    else:
                        continue

                    items = []
                    for item in raw:
                        if deep:
                            item = await fetch_deep_detail(page, item, max_comments, platform)
                        items.append(item)

                    results_by_platform.append({
                        "platform": platform,
                        "keyword": keyword,
                        "total_items": len(items),
                        "items": items,
                    })

                    print(f"  ✓ {keyword} @ {platform}: {len(items)} 条", file=sys.stderr)

        finally:
            await context.close()

    from datetime import datetime
    return {
        "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "keywords": keywords,
        "platforms": results_by_platform,
    }


def main():
    parser = argparse.ArgumentParser(description="关键词搜索采集工具")
    parser.add_argument("--keywords", required=True, help="关键词列表（逗号分隔）")
    parser.add_argument("--platforms", default="both", choices=["weibo", "xiaohongshu", "both"],
                        help="搜索平台（默认 both）")
    parser.add_argument("--per-keyword", type=int, default=5, help="每个关键词取多少条（默认 5）")
    parser.add_argument("--deep", action="store_true", help="进入详情页取完整正文和评论")
    parser.add_argument("--max-comments", type=int, default=3, help="每条内容最多评论数（默认 3）")
    parser.add_argument("--visible", action="store_true", help="显示浏览器窗口")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径")

    args = parser.parse_args()
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    platforms = ["weibo", "xiaohongshu"] if args.platforms == "both" else [args.platforms]

    result = asyncio.run(search_keywords(
        keywords=keywords,
        platforms=platforms,
        per_keyword=args.per_keyword,
        deep=args.deep,
        max_comments=args.max_comments,
        headless=not args.visible,
    ))

    write_output(result, args.output)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证可导入**

```bash
cd "D:\Users\Desktop\网络热点搜集"
python -c "from scripts.keyword_search import search_keywords; print('ok')"
```

---

### Task 8: 更新 `notify_feishu.py` — 添加 keyword_search 卡片

**Files:**
- Modify: `notify/notify_feishu.py`

- [ ] **Step 1: 在 detect_type 中新增 keyword_search 检测**

在 `def detect_type()` 顶部加：
```python
if "platforms" in data and "keywords" in data:
    return "keyword_search"
```

注意：merged_hot 也有 platforms 字段，所以必须用 `keywords` 字段区分。keyword_search 的输出包含 `keywords` 数组，merged_hot 没有。

- [ ] **Step 2: 在 build_message 中添加分支**

```python
elif data_type == "keyword_search":
    return _build_keyword_search(data, collected_at)
```

- [ ] **Step 3: 添加 _build_keyword_search 函数**

```python
def _build_keyword_search(data: dict, collected_at: str) -> dict:
    """
    关键词搜索结果卡片：按产品线归类展示（GUI 层会在调 notify 前将 product_lines 合并到数据中）。
    """
    keywords = data.get("keywords", [])
    platforms = data.get("platforms", [])
    kw_str = "、".join(keywords[:5])
    if len(keywords) > 5:
        kw_str += f" 等{len(keywords)}个关键词"
    title = f"🔍 关键词搜索结果 ({collected_at})"
    elements = [_md(f"**搜索关键词：** {kw_str}")]

    # 按平台分组展示
    for p in platforms:
        platform = p.get("platform", "")
        keyword = p.get("keyword", "")
        items = p.get("items", [])
        icon = "📱" if platform == "weibo" else "📕"
        name = "微博" if platform == "weibo" else "小红书"
        elements.append(_md(f"\n**{icon} {name} · {keyword}**（{len(items)} 条）"))
        for item in items[:5]:
            text = (item.get("text", "") or item.get("title", "") or "")[:80]
            likes = item.get("likes", "?")
            comments_cnt = item.get("comments", "?")
            collects = item.get("collects", "?")
            line = f"> 📝 {text}"
            if platform == "weibo":
                line += f"  (👍{likes} 💬{comments_cnt})"
            else:
                line += f"  (👍{likes} 📂{collects} 💬{comments_cnt})"
            cc = item.get("comments_list", [])
            for c in cc[:3]:
                line += f"\n> 💬 {c.get('user', '')}: {(c.get('content', '') or '')[:40]}"
            elements.append(_md(line))
        elements.append(_hr())

    elements.append(_md(f"🕐 采集时间: {collected_at}"))
    return _card_template(title, elements, "indigo")
```

- [ ] **Step 4: 验证语法**

```bash
cd "D:\Users\Desktop\网络热点搜集"
python -c "from notify.notify_feishu import detect_type, build_message; print('ok')"
```

---

### Task 9: 更新 `notify_agent.py` — 添加 keyword_search 摘要

**Files:**
- Modify: `notify/notify_agent.py`

- [ ] **Step 1: 在 detect_type 中新增检测**

```python
if "platforms" in data and "keywords" in data:
    return "关键词搜索"
```

- [ ] **Step 2: 在 build_summary 中新增 platforms+keywords 分支，放在现有 platforms 分支前面**

```python
if "platforms" in data and "keywords" in data:
    keywords = data.get("keywords", [])
    lines.append(f"关键词: {'、'.join(keywords)}")
    for p in data["platforms"]:
        platform = p.get("platform", "")
        keyword = p.get("keyword", "")
        items = p.get("items", [])
        name = "微博" if platform == "weibo" else "小红书"
        lines.append(f"\n【{name} · {keyword}】（{len(items)} 条）")
        for item in items[:5]:
            text = (item.get("text", "") or item.get("title", "") or "")[:80]
            likes = item.get("likes", "?")
            comments_cnt = item.get("comments", "?")
            lines.append(f"  {text} (👍{likes} 💬{comments_cnt})")
            cc = item.get("comments_list", [])
            for c in cc[:3]:
                lines.append(f"    💬 {c.get('user', '')}: {(c.get('content', '') or '')[:40]}")

elif "platforms" in data:  # 原有的 merged_hot
    ...
```

- [ ] **Step 3: 验证**

```bash
cd "D:\Users\Desktop\网络热点搜集"
python -c "from notify.notify_agent import detect_type, build_summary; print('ok')"
```

---

### Task 10: 重写 `social_monitor_gui.py` — Tab 布局

**Files:**
- Rewrite: `social_monitor_gui.py`

这是最大的改动。完整重写为 Tab 布局，使用 ttk.Notebook。每个 Tab 是一个 Frame，包含自己的配置区 + Run/Stop 按钮 + 日志 Text。

因为文件约 650+ 行，这里给出完整代码的关键结构和每个 Tab 的配置区代码。

- [ ] **Step 1: 写入完整的 GUI 新代码**

```python
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
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox

# 高 DPI 支持（保持不变）
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

# 路径
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

# 样式常量
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

        self.script_dir = BASE_DIR
        self.urls_file = os.path.join(self.script_dir, "urls.txt")
        self.keywords_file = os.path.join(self.script_dir, "keywords.json")

        # 每个 Tab 独立的状态
        self.tab_processes = {}     # tab_name -> subprocess.Popen
        self.tab_logs = {}          # tab_name -> list of (text, color)

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
        """创建卡片容器，返回内部 Frame。"""
        f = ttk.LabelFrame(parent, text=text, style="Card.TLabelframe", **kw)
        f.pack(fill="x", padx=8, pady=(6, 0))
        inner = ttk.Frame(f, style="Card.TLabelframe")
        inner.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        return inner

    def _tab_frame(self, notebook, tab_name):
        """创建一个 Tab 页的框架。"""
        f = ttk.Frame(notebook, style="TFrame")
        notebook.add(f, text=tab_name)
        return f

    def _make_log_area(self, parent, tab_name):
        """为 Tab 创建日志输出区域，返回 Text widget。"""
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
        """向指定 Tab 的日志区域追加一行。"""
        w = self.tab_logs.get(tab_name)
        if not w:
            return
        w.config(state="normal")
        if color:
            w.tag_configure(color, foreground=color, font=FONT_MONO)
            w.insert(tk.END, text + "\n", color)
        else:
            w.insert(tk.END, text + "\n")
        w.see(tk.END)
        w.config(state="disabled")
        self.root.update_idletasks()

    def _clear_log(self, tab_name):
        w = self.tab_logs.get(tab_name)
        if w:
            w.config(state="normal")
            w.delete("1.0", tk.END)
            w.config(state="disabled")

    def _build_ui(self):
        outer = ttk.Frame(self.root, style="TFrame")
        outer.pack(fill="both", expand=True)

        # ── 标题栏 ──
        header = tk.Frame(outer, bg=PRIMARY, height=56)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="📊 社交媒体监控", bg=PRIMARY, fg="white",
                 font=("Microsoft YaHei UI", 16, "bold")).pack(side="left", padx=20, pady=12)
        tk.Label(header, text="一键采集 · 自动推送飞书", bg=PRIMARY, fg="#c5d9f7",
                 font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(4, 0), pady=12)

        # ── 可折叠通知配置 ──
        self._build_notify_bar(outer)

        # ── Notebook ──
        nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        self._build_tab_hot(nb)
        self._build_tab_keyword(nb)
        self._build_tab_account(nb)
        self._build_tab_schedule(nb)

        nb.bind("<<NotebookTabChanged>>", self._on_tab_change)
        self.notebook = nb

        # ── 状态栏 ──
        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(outer, textvariable=self.status_var, style="StatusBar.TLabel")
        status_bar.pack(fill="x", side="bottom")

    # ── 通知配置 ──────────────────────────────────────

    def _build_notify_bar(self, parent):
        """可折叠通知配置栏。"""
        self._notify_visible = tk.BooleanVar(value=False)
        bar = ttk.Frame(parent, style="TFrame")
        bar.pack(fill="x", padx=8, pady=(4, 0))

        toggle_btn = ttk.Button(bar, text="🔔 通知配置 ▼", style="Outline.TButton",
                                command=self._toggle_notify, width=16)
        toggle_btn.pack(side="left")

        self.notify_frame = ttk.Frame(parent, style="Card.TLabelframe")

        nf = ttk.Frame(self.notify_frame, style="Card.TLabelframe")
        nf.pack(fill="x", padx=8, pady=(6, 0))

        ttk.Label(nf, text="飞书 Webhook").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)
        self.fs_webhook_var = tk.StringVar(value="")
        ttk.Entry(nf, textvariable=self.fs_webhook_var, width=55).grid(row=0, column=1, columnspan=3, sticky="ew", pady=3)

        ttk.Label(nf, text="Agent RPC").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=3)
        self.ag_url_var = tk.StringVar(value="")
        ttk.Entry(nf, textvariable=self.ag_url_var, width=55).grid(row=1, column=1, columnspan=3, sticky="ew", pady=3)

        ttk.Label(nf, text="Sender ID").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=3)
        self.ag_sender_var = tk.StringVar(value="")
        ttk.Entry(nf, textvariable=self.ag_sender_var, width=28).grid(row=2, column=1, sticky="w", pady=3)
        ttk.Label(nf, text="Chat ID").grid(row=2, column=2, sticky="w", padx=(12, 6), pady=3)
        self.ag_chat_var = tk.StringVar(value="")
        ttk.Entry(nf, textvariable=self.ag_chat_var, width=28).grid(row=2, column=3, sticky="w", pady=3)

        nf2 = ttk.Frame(self.notify_frame, style="Card.TLabelframe")
        nf2.pack(fill="x", padx=8, pady=(4, 8))
        ttk.Button(nf2, text="💾 保存为默认配置", style="Outline.TButton",
                   command=self._save_notify_config, width=18).pack(side="left", pady=3)
        ttk.Label(nf2, text="保存到 .env 文件", style="Hint.TLabel").pack(side="left", padx=(10, 0), pady=3)

    def _toggle_notify(self):
        if self._notify_visible.get():
            self.notify_frame.pack_forget()
            self._notify_visible.set(False)
        else:
            self.notify_frame.pack(fill="x", padx=8, pady=(2, 0), after=self.notify_frame.master.winfo_children()[1])
            self._notify_visible.set(True)

    def _notify_env_path(self):
        return os.path.join(self.script_dir, ".env")

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
                if k.strip() == "FEISHU_WEBHOOK": self.fs_webhook_var.set(v)
                elif k.strip() == "AGENT_URL": self.ag_url_var.set(v)
                elif k.strip() == "AGENT_SENDER": self.ag_sender_var.set(v)
                elif k.strip() == "AGENT_CHAT": self.ag_chat_var.set(v)

    def _save_notify_config(self):
        path = self._notify_env_path()
        kv = {
            "FEISHU_WEBHOOK": self.fs_webhook_var.get(),
            "AGENT_URL": self.ag_url_var.get(),
            "AGENT_SENDER": self.ag_sender_var.get(),
            "AGENT_CHAT": self.ag_chat_var.get(),
        }
        lines = ["# 飞书通知", f"FEISHU_WEBHOOK={kv['FEISHU_WEBHOOK']}",
                 "", "# AI Agent", f"AGENT_URL={kv['AGENT_URL']}",
                 f"AGENT_SENDER={kv['AGENT_SENDER']}", f"AGENT_CHAT={kv['AGENT_CHAT']}"]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self._log(self._current_tab(), "💾 通知配置已保存", "green")
        self.status_var.set("✅ 配置已保存")

    # ── Tab: 🔥 热搜 ────────────────────────────────

    def _build_tab_hot(self, nb):
        f = self._tab_frame(nb, "🔥 热搜")
        cfg = self._card_frame(f, "采集配置")

        # 单选平台
        r1 = ttk.Frame(cfg, style="Card.TLabelframe")
        r1.pack(fill="x", pady=(4, 0))
        ttk.Label(r1, text="采集平台:").pack(side="left", padx=(0, 8))
        self.hot_platform = tk.StringVar(value="merged")
        for val, txt in [("weibo", "微博热搜"), ("douyin", "抖音热榜"), ("merged", "微博+抖音合并")]:
            ttk.Radiobutton(r1, text=txt, variable=self.hot_platform,
                            value=val).pack(side="left", padx=(0, 12))

        # 数量
        r2 = ttk.Frame(cfg, style="Card.TLabelframe")
        r2.pack(fill="x", pady=(6, 0))
        ttk.Label(r2, text="采集数量:").pack(side="left", padx=(0, 8))
        self.hot_limit = tk.StringVar(value="15")
        ttk.Spinbox(r2, from_=1, to=50, textvariable=self.hot_limit, width=6).pack(side="left", padx=(0, 24))
        self.hot_visible = tk.BooleanVar(value=False)
        ttk.Checkbutton(r2, text="显示浏览器", variable=self.hot_visible).pack(side="left", padx=(0, 16))

        # 发送
        r3 = ttk.Frame(cfg, style="Card.TLabelframe")
        r3.pack(fill="x", pady=(6, 8))
        self.hot_fs = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="发送到飞书", variable=self.hot_fs).pack(side="left", padx=(0, 12))
        self.hot_agent = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="发送到 AI Agent", variable=self.hot_agent).pack(side="left")

        # 按钮
        btnf = ttk.Frame(f, style="TFrame")
        btnf.pack(fill="x", padx=8, pady=(4, 0))
        self.hot_run_btn = ttk.Button(btnf, text="▶  开始采集", style="Accent.TButton",
                                      command=lambda: self._run_hot(), width=14)
        self.hot_run_btn.pack(side="left", padx=(0, 8))
        self.hot_stop_btn = ttk.Button(btnf, text="■  停止", style="Danger.TButton",
                                       command=lambda: self._stop_tab("hot"), state="disabled", width=10)
        self.hot_stop_btn.pack(side="left")

        # 日志
        self._make_log_area(f, "hot")

    # ── Tab: 🔍 关键词搜索 ──────────────────────────

    def _build_tab_keyword(self, nb):
        f = self._tab_frame(nb, "🔍 关键词搜索")
        cfg = self._card_frame(f, "搜索配置")

        # 产品线 + 关键词
        self.kw_product = tk.StringVar(value="")
        self.kw_checkboxes = {}  # keyword -> BooleanVar

        r1 = ttk.Frame(cfg, style="Card.TLabelframe")
        r1.pack(fill="x", pady=(4, 0))
        ttk.Label(r1, text="产品线:").pack(side="left", padx=(0, 8))
        self.kw_product_combo = ttk.Combobox(r1, textvariable=self.kw_product,
                                              state="readonly", width=14)
        self.kw_product_combo.pack(side="left", padx=(0, 8))
        self.kw_product_combo.bind("<<ComboboxSelected>>", self._on_product_change)

        # 关键词容器（动态生成 checkbox）
        self.kw_frame = ttk.Frame(cfg, style="Card.TLabelframe")
        self.kw_frame.pack(fill="x", pady=(6, 0))

        r_add = ttk.Frame(cfg, style="Card.TLabelframe")
        r_add.pack(fill="x", pady=(4, 0))
        ttk.Label(r_add, text="自定义关键词:").pack(side="left", padx=(0, 6))
        self.kw_custom_entry = ttk.Entry(r_add, width=20)
        self.kw_custom_entry.pack(side="left", padx=(0, 6))
        ttk.Button(r_add, text="+ 添加", style="Outline.TButton",
                   command=self._add_custom_keyword, width=8).pack(side="left")

        # 平台选择
        r2 = ttk.Frame(cfg, style="Card.TLabelframe")
        r2.pack(fill="x", pady=(6, 0))
        self.kw_weibo = tk.BooleanVar(value=True)
        ttk.Checkbutton(r2, text="微博", variable=self.kw_weibo).pack(side="left", padx=(0, 12))
        self.kw_xhs = tk.BooleanVar(value=True)
        ttk.Checkbutton(r2, text="小红书", variable=self.kw_xhs).pack(side="left", padx=(0, 24))
        self.kw_deep = tk.BooleanVar(value=False)
        ttk.Checkbutton(r2, text="深度采集（进入详情）", variable=self.kw_deep).pack(side="left", padx=(0, 24))
        ttk.Label(r2, text="每个关键词:").pack(side="left", padx=(0, 4))
        self.kw_per = tk.StringVar(value="5")
        ttk.Spinbox(r2, from_=1, to=20, textvariable=self.kw_per, width=5).pack(side="left", padx=(0, 4))
        ttk.Label(r2, text="条").pack(side="left")
        self.kw_visible = tk.BooleanVar(value=False)
        ttk.Checkbutton(r2, text="显示浏览器", variable=self.kw_visible).pack(side="left", padx=(12, 0))

        r3 = ttk.Frame(cfg, style="Card.TLabelframe")
        r3.pack(fill="x", pady=(6, 8))
        self.kw_fs = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="发送到飞书", variable=self.kw_fs).pack(side="left", padx=(0, 12))
        self.kw_agent = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="发送到 AI Agent", variable=self.kw_agent).pack(side="left")

        # 按钮
        btnf = ttk.Frame(f, style="TFrame")
        btnf.pack(fill="x", padx=8, pady=(4, 0))
        self.kw_run_btn = ttk.Button(btnf, text="▶  开始搜索", style="Accent.TButton",
                                     command=lambda: self._run_keyword(), width=14)
        self.kw_run_btn.pack(side="left", padx=(0, 8))
        self.kw_stop_btn = ttk.Button(btnf, text="■  停止", style="Danger.TButton",
                                      command=lambda: self._stop_tab("keyword"), state="disabled", width=10)
        self.kw_stop_btn.pack(side="left")

        # 日志
        self._make_log_area(f, "keyword")

        # 加载产品线
        self._load_keywords()

    def _load_keywords(self):
        """从 keywords.json 加载产品线。"""
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
        """产品线切换时刷新关键词 checkbox。"""
        for w in self.kw_frame.winfo_children():
            w.destroy()
        self.kw_checkboxes.clear()

        name = self.kw_product.get()
        pl = next((p for p in self._keywords_data if p["name"] == name), None)
        if not pl:
            return

        keywords = pl.get("keywords", [])
        # 两列排列
        col = 0
        for kw in keywords:
            var = tk.BooleanVar(value=True)
            cb = ttk.Checkbutton(self.kw_frame, text=kw, variable=var)
            cb.grid(row=col // 4, column=col % 4, sticky="w", padx=(4, 8), pady=2)
            self.kw_checkboxes[kw] = var
            col += 1

    def _add_custom_keyword(self):
        kw = self.kw_custom_entry.get().strip()
        if not kw or kw in self.kw_checkboxes:
            return
        var = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(self.kw_frame, text=kw, variable=var)
        cb.grid(row=len(self.kw_checkboxes) // 4, column=len(self.kw_checkboxes) % 4, sticky="w", padx=(4, 8), pady=2)
        self.kw_checkboxes[kw] = var
        self.kw_custom_entry.delete(0, tk.END)

    # ── Tab: 📊 账号监控 ────────────────────────────

    def _build_tab_account(self, nb):
        f = self._tab_frame(nb, "📊 账号监控")
        cfg = self._card_frame(f, "监控配置")

        # 采集方式
        r0 = ttk.Frame(cfg, style="Card.TLabelframe")
        r0.pack(fill="x", pady=(4, 0))
        self.acc_mode = tk.StringVar(value="url")
        ttk.Radiobutton(r0, text="从 URL 采集", variable=self.acc_mode,
                        value="url", command=self._on_acc_mode_change).pack(side="left", padx=(0, 16))
        ttk.Radiobutton(r0, text="从文件读取", variable=self.acc_mode,
                        value="file", command=self._on_acc_mode_change).pack(side="left")

        # URL 输入
        self.acc_url_frame = ttk.Frame(cfg, style="Card.TLabelframe")
        self.acc_url_frame.pack(fill="x", pady=(4, 0))
        ttk.Label(self.acc_url_frame, text="账号 URL:").pack(side="left", padx=(0, 6))
        self.acc_url_entry = ttk.Entry(self.acc_url_frame, width=45)
        self.acc_url_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(self.acc_url_frame, text="➕ 添加", style="Outline.TButton",
                   command=self._add_account_url, width=8).pack(side="left")

        # 已添加列表
        self.acc_list_frame = ttk.Frame(cfg, style="Card.TLabelframe")
        self.acc_list_frame.pack(fill="x", pady=(4, 0))
        self.acc_urls = []  # list of url strings

        # 文件选择
        self.acc_file_frame = ttk.Frame(cfg, style="Card.TLabelframe")
        ttk.Label(self.acc_file_frame, text="URL 文件:").pack(side="left", padx=(0, 6))
        self.acc_file_var = tk.StringVar(value=self.urls_file)
        ttk.Entry(self.acc_file_frame, textvariable=self.acc_file_var, width=50).pack(side="left", padx=(0, 6))
        ttk.Button(self.acc_file_frame, text="📂 浏览", style="Outline.TButton",
                   command=lambda: self._pick_file("acc_file_var")).pack(side="left")

        self._on_acc_mode_change()

        # 选项
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

        # 发送
        r4 = ttk.Frame(cfg, style="Card.TLabelframe")
        r4.pack(fill="x", pady=(6, 8))
        self.acc_fs = tk.BooleanVar(value=True)
        ttk.Checkbutton(r4, text="发送到飞书", variable=self.acc_fs).pack(side="left", padx=(0, 12))
        self.acc_agent = tk.BooleanVar(value=True)
        ttk.Checkbutton(r4, text="发送到 AI Agent", variable=self.acc_agent).pack(side="left")

        # 按钮
        btnf = ttk.Frame(f, style="TFrame")
        btnf.pack(fill="x", padx=8, pady=(4, 0))
        self.acc_run_btn = ttk.Button(btnf, text="▶  开始采集", style="Accent.TButton",
                                      command=lambda: self._run_account(), width=14)
        self.acc_run_btn.pack(side="left", padx=(0, 8))
        self.acc_stop_btn = ttk.Button(btnf, text="■  停止", style="Danger.TButton",
                                       command=lambda: self._stop_tab("account"), state="disabled", width=10)
        self.acc_stop_btn.pack(side="left")

        # 日志
        self._make_log_area(f, "account")

    def _on_acc_mode_change(self):
        if self.acc_mode.get() == "url":
            self.acc_file_frame.pack_forget()
            self.acc_url_frame.pack(fill="x", pady=(4, 0))
            self.acc_list_frame.pack(fill="x", pady=(4, 0))
        else:
            self.acc_url_frame.pack_forget()
            self.acc_list_frame.pack_forget()
            self.acc_file_frame.pack(fill="x", pady=(4, 0))

    def _add_account_url(self):
        url = self.acc_url_entry.get().strip()
        if not url:
            return
        if url not in self.acc_urls:
            self.acc_urls.append(url)
            self._refresh_acc_list()
        self.acc_url_entry.delete(0, tk.END)

    def _refresh_acc_list(self):
        for w in self.acc_list_frame.winfo_children():
            w.destroy()
        for url in self.acc_urls:
            icon = "📱" if "weibo" in url else "📕" if "xiaohongshu" in url else "🔗"
            rf = ttk.Frame(self.acc_list_frame, style="Card.TLabelframe")
            rf.pack(fill="x", pady=2)
            ttk.Label(rf, text=f"{icon} {url[:60]}...").pack(side="left", padx=(4, 8))
            ttk.Button(rf, text="✕", style="Outline.TButton",
                       command=lambda u=url: self._remove_acc_url(u), width=3).pack(side="right")

    def _remove_acc_url(self, url):
        if url in self.acc_urls:
            self.acc_urls.remove(url)
            self._refresh_acc_list()

    def _pick_file(self, var_name):
        p = filedialog.askopenfilename(title="选择 URL 文件",
                                       filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
                                       initialdir=self.script_dir)
        if p:
            getattr(self, var_name).set(p)

    # ── Tab: ⏰ 定时任务（预留） ──────────────────────

    def _build_tab_schedule(self, nb):
        f = self._tab_frame(nb, "⏰ 定时任务")
        ttk.Label(f, text="⏰ 定时任务功能即将推出", font=("Microsoft YaHei UI", 14),
                 foreground=TEXT_SECONDARY).pack(expand=True, pady=60)
        ttk.Label(f, text="在这里你可以设置每天定时执行采集任务并自动推送飞书",
                 font=FONT_SM, foreground=TEXT_SECONDARY).pack()

    # ── Tab 切换事件 ──────────────────────────────

    def _current_tab(self):
        sel = self.notebook.index(self.notebook.select())
        return ["hot", "keyword", "account", "schedule"][sel]

    def _on_tab_change(self, event=None):
        self.status_var.set(f"当前: {self.notebook.tab(self.notebook.select(), 'text')}")

    # ── 运行逻辑 ────────────────────────────────────

    def _stop_tab(self, tab_name):
        proc = self.tab_processes.get(tab_name)
        if proc and proc.poll() is None:
            proc.terminate()
            self._log(tab_name, "■ 已终止", "red")
        self._set_tab_buttons(tab_name, running=False)
        self.status_var.set("■ 已终止")

    def _set_tab_buttons(self, tab_name, running=True):
        """启用/禁用 Tab 的运行和停止按钮。"""
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
        """通用的脚本执行 + 通知发送逻辑。"""
        self._clear_log(tab_name)
        self._set_tab_buttons(tab_name, running=True)
        self.status_var.set("⏳ 运行中...")
        self._log(tab_name, f"▶ 开始执行: {' '.join(cmd)}", "cyan")

        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"

        tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json",
            delete=False, dir=self.script_dir, prefix="_gui_")
        tmp_path = tmp.name
        tmp.close()

        def work():
            try:
                # 执行采集
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

                # 发送到飞书
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

                # 发送到 Agent
                if send_agent:
                    self._log(tab_name, "  正在发送到 AI Agent...", "yellow")
                    acmd = [PYTHON, os.path.join(self.script_dir, "notify", "notify_agent.py"),
                            "-i", tmp_path]
                    ag_url = self.ag_url_var.get().strip()
                    ag_sender = self.ag_sender_var.get().strip()
                    ag_chat = self.ag_chat_var.get().strip()
                    if ag_url: acmd += ["--url", ag_url]
                    if ag_sender: acmd += ["--sender", ag_sender]
                    if ag_chat: acmd += ["--chat", ag_chat]
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
            "weibo": "weibo_hot_search",
            "douyin": "douyin_hot_search",
            "merged": "hot_search",
        }
        script = script_map.get(platform, "hot_search")
        cmd = [PYTHON, os.path.join(self.script_dir, "scripts", f"{script}.py"), "--limit", limit]

        if platform == "weibo":
            cmd += ["--top-posts", "3", "--top-comments", "5"]
        elif platform == "merged":
            cmd += ["--weibo-limit", limit, "--douyin-limit", limit,
                    "--weibo-posts", "3", "--weibo-comments", "5"]

        if visible:
            cmd.append("--visible")

        self._run_script_common("hot", cmd, self.hot_fs.get(), self.hot_agent.get())

    def _run_keyword(self):
        selected = [kw for kw, var in self.kw_checkboxes.items() if var.get()]
        if not selected:
            messagebox.showwarning("提示", "请至少选择一个关键词")
            return

        platforms = []
        if self.kw_weibo.get(): platforms.append("weibo")
        if self.kw_xhs.get(): platforms.append("xiaohongshu")
        if not platforms:
            messagebox.showwarning("提示", "请至少选择一个平台")
            return

        cmd = [PYTHON, os.path.join(self.script_dir, "scripts", "keyword_search.py"),
               "--keywords", ",".join(selected),
               "--platforms", "both" if len(platforms) == 2 else platforms[0],
               "--per-keyword", self.kw_per.get()]

        if self.kw_deep.get():
            cmd.append("--deep")

        if self.kw_visible.get():
            cmd.append("--visible")

        self._run_script_common("keyword", cmd, self.kw_fs.get(), self.kw_agent.get())

    def _run_account(self):
        if self.acc_mode.get() == "url":
            urls = self.acc_urls
            if not urls:
                messagebox.showwarning("提示", "请添加至少一个账号 URL")
                return
            cmd = [PYTHON, os.path.join(self.script_dir, "scripts", "competitor_monitor.py"),
                   "--urls"] + urls
        else:
            filepath = self.acc_file_var.get()
            if not os.path.isfile(filepath):
                messagebox.showwarning("提示", f"文件不存在: {filepath}")
                return
            cmd = [PYTHON, os.path.join(self.script_dir, "scripts", "competitor_monitor.py"),
                   "--file", filepath]

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
```

- [ ] **Step 2: 验证 GUI 启动**

```bash
cd "D:\Users\Desktop\网络热点搜集"
python social_monitor_gui.py
```

Expected: 窗口显示，4 个 Tab 正常切换，通知配置可折叠。

---

### Task 11: 更新 spec 文件 + 重建 exe

**Files:**
- Modify: `社交监控工具.spec`

- [ ] **Step 1: 更新 spec 文件确认正确**

```bash
cd "D:\Users\Desktop\网络热点搜集"
cat 社交监控工具.spec
```
确认 `a = Analysis(['social_monitor_gui.py'], ...)` 正确。

- [ ] **Step 2: 重建 exe**

```bash
cd "D:\Users\Desktop\网络热点搜集"
pyinstaller 社交监控工具.spec --noconfirm
```

Expected: Build completes. New exe at `dist/社交监控工具.exe`

- [ ] **Step 3: 复制到根目录**

```bash
cp "D:\Users\Desktop\网络热点搜集\dist\社交监控工具.exe" "D:\Users\Desktop\网络热点搜集\社交监控工具.exe"
```

---

### Task 12: 整体验证

- [ ] **Step 1: 验证所有 import**

```bash
cd "D:\Users\Desktop\网络热点搜集"
python -c "
from scripts.common import CommentItem, kill_edge, launch_browser, get_edge_user_data, write_output
from scripts.weibo_scraper import scrape_profile
from scripts.weibo_hot_search import scrape_hot_search
from scripts.douyin_hot_search import scrape_hot_search
from scripts.xiaohongshu_scraper import scrape_profile
from scripts.keyword_search import search_keywords
from notify.notify_feishu import detect_type, build_message
from notify.notify_agent import detect_type, build_summary
print('All imports OK')
"
```

- [ ] **Step 2: 启动 GUI 手动检查**
  - 4 个 Tab 正常显示
  - 通知配置可折叠/展开
  - 热搜 Tab：单选切换、数量设置
  - 关键词 Tab：产品线下拉、关键词 checkbox、自定义添加
  - 账号监控 Tab：URL 添加/删除、文件模式切换
