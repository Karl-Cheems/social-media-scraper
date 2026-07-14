# 社交媒体监控工具

基于 Playwright + Edge 浏览器的社交媒体内容自动采集工具，支持微博、小红书、抖音三大平台。

## 功能

- **🔥 热搜监控** — 微博热搜榜/文娱榜、抖音热榜实时采集
- **🔍 关键词搜索** — 按产品线 + 关键词在小红书/微博批量搜索
- **🏠 自有账号监控** — 元气森林自有账号内容采集
- **🏢 竞品账号监控** — 从 URL 文件读取竞品账号列表，批量采集
- **📝 内容详情采集** — 单条微博/小红书内容详情 + 评论
- **⏰ 定时轮询** — 支持按规则定时自动执行采集任务
- **🤖 AI Agent 推送** — 采集结果自动推送至 AI Agent

## 目录结构

```
├── main.py                    # 程序入口
├── scripts/                   # 采集脚本（后端逻辑）
│   ├── common.py              # 公共工具（浏览器启动、输出、评论展开）
│   ├── keyword_search.py      # 关键词搜索
│   ├── weibo_hot_search.py    # 微博热搜
│   ├── douyin_hot_search.py   # 抖音热榜
│   ├── hot_search.py          # 微博+抖音合并
│   ├── competitor_monitor.py  # 竞品账号监控
│   ├── url_detail.py          # 内容详情采集
│   ├── weibo_scraper.py       # 微博爬虫核心
│   └── xiaohongshu_scraper.py # 小红书爬虫核心
├── notify/                    # 推送模块
│   ├── notify_feishu.py       # 飞书卡片推送
│   └── notify_agent.py        # AI Agent 推送
├── config/                    # 配置文件
│   ├── keywords.json          # 产品线 + 关键词配置
│   ├── urls.txt               # 竞品账号 URL 列表
│   └── schedule_rules.json    # 定时轮询规则
├── tests/                     # 测试脚本
├── docs/                      # 设计文档
│   └── superpowers/
├── data/                      # 采集输出数据（gitignored）
├── dist/                      # 打包产物（gitignored）
├── .env                       # 本地环境变量
├── .env.example               # 环境变量示例
├── 社交监控工具.spec           # PyInstaller 打包配置
└── 一键部署.bat               # 部署脚本
```

## 快速开始

### 环境要求

- Python 3.12+
- Microsoft Edge 浏览器
- 微博/小红书账号（用于登录）

### 安装

```bash
pip install -r requirements.txt
playwright install msedge
```

### 配置

1. 复制 `.env.example` 为 `.env`，配置飞书 Webhook、AI Agent 等信息
2. （可选）编辑 `config/urls.txt` 配置竞品账号列表
3. （可选）编辑 `config/keywords.json` 配置搜索关键词

### 运行

```bash
python main.py                # 启动图形界面
python main.py --lang en       # 指定语言
```

也可直接运行单个采集脚本：

```bash
python scripts/keyword_search.py --keywords "气泡水" --platforms xiaohongshu
python scripts/weibo_hot_search.py --limit 10
```

### 打包为单文件

```bash
py -3.12 -m PyInstaller 社交监控工具.spec
```

## 注意事项

- 首次使用时需要在弹出的浏览器窗口中登录微博/小红书
- Edge 浏览器用户数据目录默认在 `%LOCALAPPDATA%/Microsoft/Edge/User Data`
- 采集频率过高可能触发平台风控，脚本已内置随机延迟
