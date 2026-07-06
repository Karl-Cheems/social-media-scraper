# Playwright 浏览器自动化经验总结

## 一、核心原则

### 1.1 用 Playwright 原生 API，不要用 page.evaluate()
```python
# ❌ 不要：
await page.evaluate("document.querySelector('.btn').click()")

# ✅ 用：
await page.locator(".btn").click()

# ✅ 有遮挡时用 force:
await page.locator(".btn").click(force=True)

# ✅ 等待可见再操作：
await page.locator(".btn").wait_for(state="visible", timeout=10000)
```
`page.evaluate()` 执行 JS 绕过了 Playwright 的等待机制（visible、enabled、stable），经常被悬浮层拦截导致点击失效。

### 1.2 填输入框三步走
```python
await input.focus()
await page.keyboard.press("Control+a")  # 全选清空
await page.keyboard.press("Delete")
await page.keyboard.type("搜索内容", delay=60)  # 模拟真人逐字输入
```

### 1.3 延迟用 asyncio.sleep() 而不是 page.wait_for_timeout()
```python
await asyncio.sleep(2)  # 更直观
```

---

## 二、虚拟滚动处理（重要）

### 问题
页面（微博、小红书）使用虚拟滚动，滚动出视口的 DOM 元素会被**移出 DOM 树**释放内存。当你向下滚动加载更多后：
- 顶部（最新）的笔记已不在 DOM 中
- `querySelectorAll` 只能取到当前视口附近的内容
- 滚回顶部后，虚拟滚动可能不会重新渲染之前的内容

### 正确做法
**在滚动前就捕获需要的数据**，而不是滚动后再去 DOM 里取：

```python
# ✅ 先取数据，再滚动
card_data = await page.evaluate("提取全部可见卡片...")  # 先抓
await page.evaluate("window.scrollBy(0, 1500)")        # 再滚
# 数据已在 card_data 中，DOM 怎么变都不影响
```

**边滚动边增量收集：**
```python
all_seen = {}
for i in range(max_scroll):
    # 提取当前可见的卡片
    fresh = await page.evaluate("提取当前可见卡片...")
    for c in fresh:
        if c["url"] not in all_seen:
            all_seen[c["url"]] = c  # 按 URL 去重合并
    if len(all_seen) >= limit:
        break
    await page.evaluate("window.scrollBy(0, 1500)")  # 往下滚
```

---

## 三、导航方式

### 3.1 SPA 跳转（单页应用）
微博同域导航不要用 `page.goto()`（会被风控拦截），用 JS 改 `location`：
```python
# 先点卡片找到 href → 再跳
card_info = await page.evaluate("""
    () => {
        var link = document.querySelector('a[href*="/user/profile/"]');
        var r = link.getBoundingClientRect();
        return { href: link.href };
    }
""")
# 用 window.location.href 跳转（不触发跨域风控）
await page.evaluate(f"window.location.href = '{card_info['href']}'")
await page.wait_for_url("**/user/profile/**", timeout=15000)
await page.wait_for_timeout(2000)
```

### 3.2 直接导航到详情页
不要依赖 DOM 去点击卡片跳转（卡片可能被虚拟滚动移出 DOM），直接用 URL：
```python
await page.goto(url, wait_until="domcontentloaded", timeout=30000)
await page.wait_for_timeout(2000)
```

### 3.3 后退到搜索结果页
小红书：用浏览器后退（同一 tab 内操作）
```python
await page.go_back(wait_until="domcontentloaded", timeout=15000)
```
微博：用 goto 回到搜索页（同域允许）
```python
await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
```

---

## 四、登录处理

### 4.1 检测未登录并等待登录
```python
# 检测
if "login" in page.url or "passport" in page.url:
    if headless:
        # 关闭无头模式，打开浏览器窗口让用户登录
        await context.close()
        context = await p.chromium.launch_persistent_context(
            user_data_dir, headless=False, ...
        )
        page = await context.new_page()
        await page.goto(target_url)
    # 等待登录完成（轮询 URL 不再包含 login）
    for _ in range(int(300 / 1.5)):  # 超时 300秒
        await asyncio.sleep(1.5)
        if "login" not in page.url and "passport" not in page.url:
            break
```

---

## 五、风控规避

### 5.1 随机延迟
```python
import random
await asyncio.sleep(random.uniform(4, 8))  # 每次操作后随机等几秒
```

### 5.2 模拟真人操作
- 搜索框：逐字输入（`delay=50-100`），不要 `fill()` 一次填入
- 滚动：每次 800-1500px，不要一次滚到底
- 两个页面之间切换：间隔 5-10 秒

### 5.3 用 Edge 而非 Chromium
```python
context = await p.chromium.launch_persistent_context(
    user_data_dir,
    channel="msedge",  # 用 Edge（用户的已登录浏览器）
    headless=headless,
    args=["--disable-sync"],
    viewport={"width": 1920, "height": 1080},
)
```

---

## 六、小红书特殊经验

### 6.1 搜索不能直接用 URL
小红书反爬会拦截直接构造搜索 URL 的请求（`/search_result/xxx`），必须模拟真实操作：
1. 打开 explore 首页
2. 找到搜索框点击 → focus
3. 逐字输入 → 按回车

### 6.2 筛选面板
- 筛选按钮的 CSS 类名是 `.filter`，弹出面板是 `.filter-panel`
- 面板内的标签（tags）有**两套 DOM 元素**：一套可见的（`data-hp-bound`），一套做定位用的（绝对定位透明层）
- 点击时要用 `force=True` 强制点击可见的那套，否则会被透明层拦截
```python
await page.evaluate('document.querySelector(".filter").click()')
await asyncio.sleep(2)

# 点击"最多点赞"
panel = page.locator(".filter-panel")
tags = panel.locator(".tags[data-hp-bound]")  # 只点可见的
for i in range(await tags.count()):
    text = (await tags.nth(i).inner_text()).strip()
    if text == "最多点赞":
        await tags.nth(i).click(force=True)
        break

await asyncio.sleep(1)

# 点击"一周内"
for i in range(await tags.count()):
    text = (await tags.nth(i).inner_text()).strip()
    if text == "一周内":
        await tags.nth(i).click(force=True)
        break

await asyncio.sleep(1)
await page.evaluate('document.querySelector(".filter").click()')  # 关闭面板
```

---

## 七、调试技巧

### 7.1 截图排查
当 DOM 操作不生效时，先截图看页面实际长什么样：
```python
await page.screenshot(path="debug.png", full_page=True)
```

### 7.2 查看当前 URL
```python
print(f"当前URL: {page.url}")
```

### 7.3 无头模式下双击卡片失败 → 改为 visible 模式
如果无头模式下某些操作总是不生效，改成可见窗口跑一次，观察浏览器行为：
```python
# 把 headless=True 改为 False 就可以看到浏览器在做什么
```

### 7.4 查看页面完整文本
```python
text = await page.evaluate('document.body.innerText')
```

---

## 八、常见问题速查

| 问题 | 原因 | 解决 |
|------|------|------|
| 点了按钮但没生效 | 被透明层/悬浮层遮挡 | `locator.click(force=True)` |
| 滚动后取不到顶部数据 | 虚拟滚动移出 DOM | 滚动前先提取数据 |
| 页面导航跳转不正确 | SPA 的 `goto` 被拦截 | 用 `window.location.href` |
| 输入框填不进去 | 页面有覆盖层 | `input.focus()` + `force=True` |
| 筛选标签点不到 | 存在两套 DOM（可见+定位） | 用 `[data-hp-bound]` 选择器 |
| 搜索 URL 返回空 | 反爬拦截直接 URL 搜索 | 模拟真人输入搜索 |
| exe 打包后文件路径不对 | `__file__` 指向临时目录 | 判断 `sys.frozen`，用 `sys.executable` |
