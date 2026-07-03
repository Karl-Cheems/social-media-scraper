# XHS 详情页进入方式改进：模拟点击替代 page.goto

## 问题

小红书详情页用 `page.goto(explore_url)` 进入时，XHS 检测到自动化特征，
在 `note-text` DOM 元素中动态替换正文为"您的浏览器似乎开启了广告屏蔽插件"提示语。

**表现特征：**
- 赞/收/评数字正常（`.interact-container` 不受影响）
- 评论列表正常
- 浏览器画面看起来正常，但代码提取的 `note_text` 已经被替换
- 这发生在 `page.goto()` 冷加载的 SPA 启动阶段

## 方案：模拟真人点击 + 浏览器后退

将详情页进入方式从 `page.goto` 改为 `locator().click()`，
返回方式从 `_do_xiaohongshu_search` 改为 `page.go_back()`。

### 为什么 click 能绕过反爬

`page.goto` → 完整的新页面冷加载 → SPA 初始化时执行反爬 JS → 检测 `navigator.webdriver` 等特征 → 替换正文

`locator().click()` → 真实鼠标事件链（mousedown/mouseup/click）→ SPA 内部路由导航 → 不触发冷启动反爬检查 → 正文正常加载

### 改动文件

仅一处：`scripts/keyword_search.py`

### 改动点

#### 1. `_fetch_xiaohongshu_detail()` — 顶部导航逻辑

**之前：**
```python
explore_url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={token}&xsec_source=pc_search"
await page.goto(explore_url, wait_until="domcontentloaded", timeout=20000)
```

**之后：**
```python
# 在搜索结果页点击对应卡片（SPA 内部导航，绕过反爬）
selector = f'a.cover[href*="{note_id}"]'
card = page.locator(selector).first
await card.wait_for(state="visible", timeout=10000)
await card.scroll_into_view_if_needed()
await page.wait_for_timeout(500)
await card.click(force=True, timeout=10000)
# 等待 SPA 导航到详情页
try:
    await page.wait_for_url("**/explore/**", timeout=15000)
except Exception:
    print("    详情页 SPA 导航可能未完成，继续尝试提取...", file=sys.stderr)
```

#### 2. `_fetch_xiaohongshu_detail()` — 返回搜索结果页

**之前：**
```python
# 这个方法在 _fetch_xiaohongshu_detail 外部（search_xiaohongshu 的循环体中）调用
await _do_xiaohongshu_search(page, keyword)
```

**之后：**
```python
# 在 _fetch_xiaohongshu_detail 返回前执行浏览器后退
try:
    await page.go_back(wait_until="domcontentloaded", timeout=15000)
    await page.wait_for_timeout(3000)
except Exception:
    print("    后退失败，尝试重新搜索", file=sys.stderr)
    # fallback: 重新搜索
    return result  # 返回已提取的数据，不阻塞
```

#### 3. `search_xiaohongshu()` — 移除返回搜索页逻辑

`go_back()` 已经在 `_fetch_xiaohongshu_detail` 内部处理，`search_xiaohongshu()` 的循环体不需要再调 `_do_xiaohongshu_search`。

**之前：**
```python
if idx < len(items) - 1:
    try:
        await _do_xiaohongshu_search(page, keyword)
    except Exception:
        pass
```

**之后：**
```python
# 后退逻辑已移到 _fetch_xiaohongshu_detail 内部
# 这里的间距控制由 random_delay 单独负责
if idx < len(items) - 1:
    await random_delay(3, 7, "XHS 详情页间后退间隔")
```

### 边界情况和错误处理

1. **卡片不在可视区** — `scroll_into_view_if_needed()` 确保能看到
2. **SPA 导航未完成** — `wait_for_url` 超时后不抛错，继续尝试提取（可能 go_back 之前没数据，但总比 crash 好）
3. **`go_back` 失败** — 如果后退失败，跳到 about:blank 或尝试重新搜索作为 fallback
4. **多个卡片匹配** — `.first` 取第一个，note_id 足够定位唯一卡片

### 验证方式

1. 跑 XHS 单测：`python keyword_search.py -k 热梗 -p xiaohongshu -n 2 -c 3 --visible -o test_xhs_click.json`
2. 检查 JSON 中每个 item 的 `text` 是否含警告语 → 含则失败
3. 检查所有数字 > -1
4. 跑合并测试：`python keyword_search.py -k 热梗 -p both -n 2 -c 3 --visible -o test_click_combined.json`
5. 微博部分不应该受影响
