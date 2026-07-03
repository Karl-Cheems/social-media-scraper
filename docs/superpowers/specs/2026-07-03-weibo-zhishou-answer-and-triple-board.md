# 微博智搜回答 + 三榜合并 设计文档

> **For agentic workers:** This is the design spec. After user approval, invoke `writing-plans` to create the implementation plan.

## 背景

当前 `weibo_hot_search.py` 采集微博热搜榜后，进入话题搜索页提取热门微博及评论。需求改为：

1. **去掉评论采集** — 不再进入微博详情页提取评论
2. **改为采集智搜回答** — 进入话题搜索页找到"智搜回答"的微博卡片，点击进入 `aisearch` 页面获取完整回答
3. **新增文娱榜** — 支持 `weibo.com/hot/entertainment`，结构同热搜榜
4. **三榜合并** — 微博热搜、微博文娱、抖音热榜可单独跑或合并跑

## 架构

### 数据模型

**删除：** `TopicPost`（含所有互动字段和 `comments_list`）、`CommentItem`

**改造：** `TopicDetail` 替换 `posts` 字段为 `zhishou_answer`：

```python
class ZhishouAnswer(BaseModel):
    """智搜回答"""
    text: str = Field(description="智搜回答正文")
    expanded: str = Field(default="", description="点击「查看更多」后展开的补充内容")
    source_url: str = Field(default="", description="aisearch 页面 URL")

class TopicDetail(BaseModel):
    """热搜/文娱话题"""
    rank: int
    title: str
    hot_value: str
    topic_url: str
    board: str = Field(description="hot | entertainment")
    zhishou_answer: ZhishouAnswer | None = Field(default=None, description="智搜回答，可能没有")
```

### 采集流程（weibo_hot_search.py）

```
进入热搜榜/文娱榜
  → 提取排名列表（与现逻辑一致，加 board 参数）
  → 对每条话题进搜索页（s.weibo.com/weibo?q=xxx&xsort=hot）
  → 在 card-wrap 列表中找到「智搜回答」的卡片
    → 若找到：点击/导航到 aisearch 页面 → 提取回答正文
      → 点击「查看更多」→ 提取展开内容
    → 若未找到：标记 zhishou_answer = null
```

### 智搜回答定位策略

在 s.weibo.com 搜索页的 `card-wrap` 列表中，查找满足以下条件的卡片：
- 卡片内的用户名（`name` 或 `username` 元素）包含"智搜"或"智搜回答"
- 或者卡片整体文本包含"智搜回答"

找到后，获取其详情链接（`from a` 标签的 href），导航到 `aisearch` 页面。

### 智搜回答内容提取

在 `aisearch` 页面（URL 格式 `https://s.weibo.com/aisearch?q=xxx`）：
1. 等待页面加载
2. 提取智搜回答的正文
3. 查找并点击"查看更多"按钮（如有）
4. 等待展开后，再提取完整内容

### 三榜入口

| 榜单 | URL | board 标识 |
|------|-----|-----------|
| 微博热搜榜 | `https://weibo.com/hot/search` | `hot` |
| 微博文娱榜 | `https://weibo.com/hot/entertainment` | `entertainment` |
| 抖音热榜 | 保持不变 | — |

### 合并输出格式

```json
{
  "collected_at": "2026-07-03 11:00:00",
  "keywords": ["微博热搜", "微博文娱", "抖音热榜"],
  "platforms": [
    {
      "platform": "weibo",
      "board": "hot",
      "total_topics": 10,
      "topics": [
        {
          "rank": 1,
          "title": "xxx",
          "hot_value": "爆",
          "topic_url": "...",
          "board": "hot",
          "zhishou_answer": {
            "text": "...",
            "expanded": "...",
            "source_url": "https://s.weibo.com/aisearch?q=..."
          }
        }
      ]
    },
    {
      "platform": "weibo",
      "board": "entertainment",
      "total_topics": 10,
      "topics": [...]
    },
    {
      "platform": "douyin",
      "total_topics": 10,
      "topics": [...]
    }
  ]
}
```

### CLI 设计

**weibo_hot_search.py**
```
python weibo_hot_search.py --limit 10 --board hot
python weibo_hot_search.py --limit 10 --board entertainment
python weibo_hot_search.py --board both             ← 两个榜都跑
```
删除 `--top-posts` 和 `--top-comments` 参数（不再采集微博和评论）。

**hot_search.py（合并模式）**
```
python hot_search.py --weibo-limit 10 --weibo-board both --douyin-limit 10
python hot_search.py --weibo-board both              ← 微博跑两个榜
```
删除 `--weibo-posts` 和 `--weibo-comments` 参数。

## 涉及文件改动

| 文件 | 改动 |
|------|------|
| `scripts/weibo_hot_search.py` | 删除 `TopicPost`、`CommentItem`、`_extract_comments`；新增 `ZhishouAnswer`；重构 `_fetch_topic_detail` 找智搜；加 `board` 参数；榜单提取支持多入口 |
| `scripts/hot_search.py` | 改为跑 2-3 个榜单，合并输出 |
| `scripts/douyin_hot_search.py` | 无需改动 |
| `notify/notify_feishu.py` | 更新 `_build_hot_search`、`_build_merged_hot`：展示智搜回答 |
| `notify/notify_agent.py` | 更新摘要：展示智搜回答 |
| `social_monitor_gui.py` | 热搜 tab 区分微博热搜/微博文娱/抖音/合并 |

## 不涉及的改动

- `scripts/douyin_hot_search.py` — 抖音热榜保持原样
- `scripts/common.py` — 无需改动
- `scripts/competitor_monitor.py` — 无关
- `scripts/xiaohongshu_scraper.py` — 无关
- 账号监控、关键词搜索等功能 — 无关

## 错误处理

1. **智搜回答不存在** — 某些话题没有智搜回答，`zhishou_answer` 置为 `null`，不影响其他话题
2. **aisearch 页面加载失败** — 重试 1 次，失败则跳过
3. **「查看更多」不存在** — 有些回答可能没有折叠，跳过展开步骤
4. **榜单页解析失败** — 与原逻辑一致，返回空列表
