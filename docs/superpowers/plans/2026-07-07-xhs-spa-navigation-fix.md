# XHS SPA 导航修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复小红书 SPA 导航退化，全部改用模拟用户操作（点击卡片/Esc 关闭弹窗），不用 `goto`/`go_back`/`window.location.href`

**Architecture:** 两种操作替代全部非模拟导航：(1) 点击用户卡片/笔记卡片进详情；(2) `Escape` 关闭 SPA 浮层弹窗退回前一页

**Tech Stack:** Python, Playwright, Edge CDP

---

### Task 1: `xiaohongshu_scraper.py` — 用户卡片点击代替 `window.location.href`

**Files:**
- Modify: `xiaohongshu_scraper.py:134-148`

**现状（134-148行）：**
```python
if user_href:
    print(f"  进入用户主页", file=sys.stderr)
    profile_url = user_href.split('?')[0]
    await page.evaluate(f"window.location.href = '{profile_url}'")
    try:
        await page.wait_for_url("**/user/profile/**", timeout=15000)
        await page.wait_for_timeout(2000)
    except Exception:
        print(f"  导航超时，当前URL: {page.url}", file=sys.stderr)
    if "user/profile" not in page.url:
        print(f"  ✗ 无法进入用户主页 {user_id}", file=sys.stderr)
        raise RuntimeError(f"无法进入用户主页 {user_id}")
    found_user = True
```

- [ ] **Step 1: 将 `window.location.href` 替换为 `card.click()`**

```python
if user_href:
    print(f"  点击用户卡片进入主页", file=sys.stderr)
    card = page.locator(f'a[href*="/user/profile/{user_id}"]').first
    await card.scroll_into_view_if_needed()
    await page.wait_for_timeout(500)
    await card.click(timeout=10000)
    try:
        await page.wait_for_url("**/user/profile/**", timeout=15000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)
    if "user/profile" not in page.url:
        print(f"  ✗ 无法进入用户主页 {user_id}", file=sys.stderr)
        raise RuntimeError(f"无法进入用户主页 {user_id}")
    found_user = True
```

---

### Task 2: `xiaohongshu_scraper.py` — Esc 关闭详情弹窗代替 `goto`

**Files:**
- Modify: `xiaohongshu_scraper.py:436-443`

**现状（436-443行）：**
```python
if idx < len(unpinned) - 1:
    await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(1500)
    if "user/profile" not in page.url:
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1500)
```

- [ ] **Step 1: 将 `page.goto()` 替换为 `page.keyboard.press("Escape")`**

```python
if idx < len(unpinned) - 1:
    # 按 Escape 关闭详情页 SPA 浮层弹窗
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(2000)
```

---

### Task 3: `keyword_search.py` — 搜索失败不再回退 `goto`

**Files:**
- Modify: `keyword_search.py:378-382`

**现状（378-382行）：**
```python
if not ok:
    print(f"    ⚠️ 搜索框输入失败，回退直接URL", file=sys.stderr)
    search_url = f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}&source=web_search_result_notes"
    await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(5000)
```

- [ ] **Step 1: 去掉 `goto` 回退，返回 False**

```python
if not ok:
    print(f"    ⚠️ 搜索框输入失败，放弃搜索", file=sys.stderr)
    return False
```

- [ ] **Step 2: 检查 _do_xiaohongshu_search 返回 False 后 _search_xiaohongshu 的处理是否兼容**

_search_xiaohongshu 中已有处理（409-410行）：
```python
if not ok:
    return []
```
兼容，不需要额外改动。

---

### Task 4: `keyword_search.py` — Esc 关闭详情弹窗代替 `go_back`

**Files:**
- Modify: `keyword_search.py:725-731`

**现状（725-731行）：**
```python
if idx < len(items) - 1:
    try:
        await page.go_back(wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)
    except Exception:
        pass
```

- [ ] **Step 1: 将 `page.go_back()` 替换为 `page.keyboard.press("Escape")`**

```python
if idx < len(items) - 1:
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(2000)
```

---

### Task 5: 验证改动

- [ ] **Step 1: 代码检查**

确认文件语法正确：
```
cd D:\Users\Desktop\网络热点搜集 && python -c "import scripts.xiaohongshu_scraper; import scripts.keyword_search; print('OK')"
```

- [ ] **Step 2: 重建 exe**

```
cd D:\Users\Desktop\网络热点搜集 && pyinstaller --clean --onefile --noconsole --name 社交监控工具 --add-data "scripts;scripts" --add-data "notify;notify" --add-data ".env;." --hidden-import pydantic --hidden-import pydantic._internal --hidden-import regex --hidden-import httpx --hidden-import httpx._client --hidden-import certifi --distpath "dist/temp_dist" --workpath "temp_build" --specpath "temp_spec" social_monitor_gui.py 2>&1 | tail -3
```

```
cp "D:/Users/Desktop/网络热点搜集/dist/temp_dist/社交监控工具.exe" "D:/Users/Desktop/网络热点搜集/社交监控工具.exe" && rm -rf "D:/Users/Desktop/网络热点搜集/temp_build" "D:/Users/Desktop/网络热点搜集/temp_spec" "D:/Users/Desktop/网络热点搜集/dist/temp_dist"
```
