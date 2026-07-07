# XHS SPA 导航修复 — 统一模拟用户操作

## 问题

两个问题：

1. **部分操作退化成了直接 URL 导航**（非模拟用户点击）。包括：进入用户主页用了 `window.location.href`、详情页退回主页用了 `page.goto()`、退回搜索结果用了 `page.go_back()`。这些操作会被风控识别为机器行为。

2. **详情页是 SPA 浮层弹窗**，当前代码用整页重载（`goto`/`go_back`）来退回，而不是用 `Escape` 关闭弹窗，导致页面状态丢失、卡片位置重置。

## 方案

统一两条规则：
- **所有页面切换必须通过模拟用户交互**（点击/键盘），不允许 `page.goto()` / `page.evaluate("window.location.href")` / `page.go_back()` 用于小红书 SPA 内导航
- **详情页浮层用 `Escape` 关闭**，不重新加载页面

### 改动汇总

| 文件 | 行号 | 当前行为 | 改为 |
|------|------|---------|------|
| `xiaohongshu_scraper.py` | 138 | `window.location.href` JS跳转 | `card.click()` 点击用户卡片 |
| `xiaohongshu_scraper.py` | 438 | `page.goto(profile_url)` 重载主页 | `page.keyboard.press("Escape")` 关闭弹窗 |
| `keyword_search.py` | 380 | `goto(search_url)` 回退 | 失败时直接返回空，不做 URL 导航 |
| `keyword_search.py` | 728 | `page.go_back()` | `page.keyboard.press("Escape")` 关闭弹窗 |

### 不动的地方

- 微博详情页导航 — 整页跳转非浮层，`goto` 没问题
- `xhs_search_by_input()` — 已经正确使用模拟点击输入
- 详情页数据提取（`page.evaluate()`）— 只是读取 DOM，不涉及导航

### 使用前检查点

- 搜索结果页是否有关闭的遮罩层
- Enter 是否不会触发额外事件
