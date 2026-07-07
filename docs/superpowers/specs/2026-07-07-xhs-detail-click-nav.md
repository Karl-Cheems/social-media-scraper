# XHS 详情页风控修复方案

## 问题

进入小红书笔记详情页时触发扫码验证，但**用户自己从搜索页点击卡片进去**不会触发。

## 根因

`page.goto(note_url)` 直接导航到详情页 URL。小红书的风控检测到：用户没有通过页面内点击导航进来（来源异常），于是弹出扫码验证。

关键差异：
| 方式 | Referer | 用户行为链 | 风控结果 |
|------|---------|-----------|---------|
| 手动点击卡片 | ✅ 搜索页 → 详情页 | ✅ 完整 | ✅ 通过 |
| `page.goto()` | ❌ 无/空白 | ❌ 无 | ❌ 扫码拦截 |
| `go_back()` 后再次 `goto()` | ❌ 关联性弱 | ❌ 不自然 | ❌ 大概率拦截 |

## 方案

**改为模拟鼠标点击卡片进入详情页**，而不是 URL 导航。

具体改动点：

### 1. `xiaohongshu_scraper.py` — 笔记详情页导航

当前代码（310行）：
```python
await page.goto(note_url, wait_until="domcontentloaded", timeout=30000)
```

改为：
```python
# 在当前页面（用户主页）找到对应笔记卡片，点击进入详情
note_id = note_url.rstrip('/').split('/')[-1].split('?')[0]
card = page.locator(f'section.note-item a.cover[href*="{note_id}"]').first
await card.scroll_into_view_if_needed()
await page.wait_for_timeout(500)
await card.click()
await page.wait_for_url(f"**/explore/{note_id}**", timeout=20000)
```

### 2. `keyword_search.py` — 搜索结果的详情页导航

当前代码（584行）已经是 `card.click(force=True)` 方式，但无法识别卡片时用了 `page.goto()`。需要加强 **卡片识别**，确保不需要回退到 goto。

### 3. 解决 go_back 后的问题

当前 `go_back()` 后页面状态不稳定，导致下一张卡片可能定位不到。改为 **直接用搜索结果 URL 重新加载主页**，而不是 `go_back()`。

## 不动的地方

- `page.evaluate()` 提取数据 — 不影响风控
- `page.goto()` 用于初始页面加载 — 没登录时是 OK 的
- 搜索框输入方式 — 不受影响
