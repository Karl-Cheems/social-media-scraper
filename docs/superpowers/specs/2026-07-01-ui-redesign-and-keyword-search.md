# 社交监控工具 UI 重构 + 关键词搜索 设计文档

## 1. 目标

1. GUI 从单页面下拉框改为多 Tab 布局，每个功能有独立的配置区和日志区
2. 新增关键词搜索功能，按产品线在微博+小红书搜索内容
3. 抽取公共代码减少重复

## 2. 架构总览

```
社交监控工具.exe
├── scripts/
│   ├── common.py              ← NEW: 公共函数（浏览器启动/Edge管理/输出）
│   ├── hot_search.py          ← 已有：合并热搜
│   ├── weibo_hot_search.py    ← 已有
│   ├── douyin_hot_search.py   ← 已有
│   ├── keyword_search.py      ← NEW: 关键词搜索
│   ├── competitor_monitor.py  ← 已有
│   ├── weibo_scraper.py       ← 已有
│   └── xiaohongshu_scraper.py ← 已有
├── notify/
│   ├── notify_feishu.py       ← 已有，加 keyword_search 卡片
│   └── notify_agent.py        ← 已有，加 keyword_search 摘要
├── keywords.json              ← NEW: 产品线+关键词配置
├── social_monitor_gui.py      ← 重写：Tab 布局
└── 社交监控工具.spec
```

## 3. GUI Tab 布局

### 3.1 全局通知配置（顶部可折叠）

所有 Tab 共享飞书 Webhook、Agent 配置，折叠在应用顶部。

### 3.2 Tab 1: 🔥 热搜

| 控件 | 说明 |
|------|------|
| 采集平台 | 单选按钮组：微博热搜 / 抖音热榜 / 合并 |
| 采集数量 | Spinbox（1-50），默认 15 |
| 显示浏览器 | Checkbox |
| 发送到 | Checkbox：飞书、AI Agent |
| 开始/停止按钮 | 绿色/红色 |

日志输出当前 Tab 采集过程。切换 Tab 不丢失日志。

### 3.3 Tab 2: 🔍 关键词搜索

| 控件 | 说明 |
|------|------|
| 产品线下拉框 | 从 `keywords.json` 读取 |
| 关键词列表 | Checkbox 组，从配置文件按产品线加载 |
| 自定义关键词输入 | Entry + [添加] 按钮 |
| 平台 | Checkbox：微博、小红书 |
| 深度采集 | Checkbox（进入详情页取完整正文和评论） |
| 每个关键词取 N 条 | Spinbox（1-20），默认 5 |
| 显示浏览器 | Checkbox |
| 发送到 | Checkbox：飞书、AI Agent |

### 3.4 Tab 3: 📊 账号监控

| 控件 | 说明 |
|------|------|
| 采集方式 | 单选：从 URL 采集 / 从文件读取 |
| 账号 URL 输入 | Entry + 添加按钮 |
| 已添加账号列表 | 自动识别平台显示图标，可删除 |
| 采集数量 | Spinbox（1-50），默认 10 |
| 获取正文 | Checkbox |
| 获取评论 + 数量 | Checkbox + Spinbox |
| 显示浏览器 | Checkbox |

### 3.5 Tab 4: ⏰ 定时任务（预留）

后期添加定时执行功能的入口。

## 4. 关键词搜索脚本

### 4.1 `scripts/common.py`（NEW）

抽取公共能力：
- `CommentItem` Pydantic 模型
- `kill_edge(wait=True)` — 关闭 Edge 进程
- `launch_browser(p, headless, user_data_dir)` — 统一浏览器启动
- `get_edge_user_data()` — 获取 Edge User Data 路径
- `write_output(output, path)` — 统一 JSON 输出（含 tempfile 兜底）

### 4.2 `scripts/keyword_search.py`（NEW）

**功能：** 接收关键词列表 + 平台参数，分别在微博和小红书搜索，提取互动数据。

**参数：**
- `--keywords` — 关键词列表（逗号分隔）
- `--platforms` — 平台：weibo, xiaohongshu, both
- `--per-keyword` — 每个关键词取多少条（默认 5）
- `--deep` — 进入详情页取完整正文+评论
- `--max-comments` — 每条内容最多评论数（默认 3）
- `--visible` — 显示浏览器
- `--output` — 输出路径

**搜索策略：**
- 微博：搜 `s.weibo.com/weibo?q={keyword}`
- 小红书：搜 `https://www.xiaohongshu.com/search_result?keyword={keyword}`
- 每个平台搜到列表页后，提取：标题/正文片段、互动数（赞/评/收/转）、链接、发布时间
- 如果 `--deep` 开启，进入每条内容的详情页提取完整正文和评论列表
- 尝试按发布时间过滤近10天内容

**输出格式：**
```json
{
  "collected_at": "2026-07-01 12:00:00",
  "keywords": ["职场整活", "蓝V"],
  "platforms": [
    {
      "platform": "weibo",
      "keyword": "关键词",
      "total_items": 5,
      "items": [
        {
          "title": "",
          "text": "正文内容...",
          "author": "发布者",
          "likes": 1234,
          "comments": 56,
          "collects": 0,
          "reposts": 78,
          "url": "https://...",
          "time": "2026-06-28",
          "comments_list": [{"user": "xxx", "content": "评论内容", "likes": 10}]
        }
      ]
    }
  ]
}
```

### 4.3 `keywords.json`（NEW）

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

### 4.4 notify 适配

- `notify_feishu.py`：新增 `keyword_search` 类型检测 + `_build_keyword_search()` 卡片，按产品线→平台→关键词三级展示
- `notify_agent.py`：新增 `keyword_search` 摘要分支

## 5. 代码复用优化

### `scripts/common.py` 内容：

```python
from pydantic import BaseModel, Field

class CommentItem(BaseModel):
    user: str
    content: str
    likes: int

def kill_edge(wait=True):
    """关闭所有运行的 Edge 进程"""
    ...

async def launch_browser(p, headless, user_data_dir, channel="msedge"):
    """统一启动 Edge，带重试和临时目录兜底"""
    ...

def get_edge_user_data():
    """获取 Edge 用户数据目录路径"""
    ...

def write_output(output, output_path=None):
    """统一 JSON 输出，支持指定路径或 stdout"""
    ...
```

改造范围：
- `weibo_scraper.py`、`weibo_hot_search.py`、`douyin_hot_search.py`：删除重复的 `_kill_edge()`、`_launch_browser()`，改用 `common` 模块
- `xiaohongshu_scraper.py`：加入 Edge 杀进程+重试逻辑（目前没有）
- 所有脚本的 `main()` 输出改为用 `common.write_output()`

## 6. 文件改动清单

| 操作 | 文件 | 说明 |
|------|------|------|
| NEW | `scripts/common.py` | 公共模块 |
| NEW | `scripts/keyword_search.py` | 关键词搜索脚本 |
| NEW | `keywords.json` | 产品线关键词配置 |
| EDIT | `social_monitor_gui.py` | 重写为 Tab 布局 |
| EDIT | `notify/notify_feishu.py` | 加 keyword_search 卡片 |
| EDIT | `notify/notify_agent.py` | 加 keyword_search 摘要 |
| EDIT | `scripts/weibo_scraper.py` | 改用 common 模块 |
| EDIT | `scripts/weibo_hot_search.py` | 改用 common 模块 |
| EDIT | `scripts/douyin_hot_search.py` | 改用 common 模块 |
| EDIT | `scripts/xiaohongshu_scraper.py` | 改用 common + 加重启逻辑 |
| REBUILD | `社交监控工具.spec` + exe | |
