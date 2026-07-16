# 社交媒体监控平台

基于 Playwright + Edge 浏览器的社交媒体内容自动采集 Web 服务，支持微博、小红书、抖音三大平台。

## 功能

- **🔑 多租户登录** — 每个实例独立注册/登录，独立的 Edge 浏览器和 Agent 配置
- **🔥 热搜监控** — 微博热搜榜/文娱榜、抖音热榜实时采集
- **🔍 关键词搜索** — 按产品线 + 关键词在小红书/微博搜索
- **🏢 账号监控** — 竞品品牌账号内容批量采集
- **📝 定向内容分析** — 单条微博/小红书内容详情 + 评论
- **🔐 账号管理** — 每个实例可绑定多个平台账号，各自扫码登录
- **🤖 AI Agent 推送** — 采集结果自动推送至 RPC Agent

## 目录结构

```
├── web_server.py              # Web 服务主入口
├── scripts/                   # 采集脚本（后端逻辑）
│   ├── browser_manager.py     # 浏览器实例管理器
│   ├── common.py              # 公共工具（浏览器启动、评论展开）
│   ├── keyword_search.py      # 关键词搜索
│   ├── weibo_hot_search.py    # 微博热搜
│   ├── douyin_hot_search.py   # 抖音热榜
│   ├── hot_search.py          # 微博+抖音合并
│   ├── competitor_monitor.py  # 竞品账号监控
│   ├── url_detail.py          # 内容详情采集
│   ├── weibo_scraper.py       # 微博爬虫核心
│   └── xiaohongshu_scraper.py # 小红书爬虫核心
├── web/templates/index.html   # Web 前端（单页应用）
├── notify/                    # 推送模块
│   └── notify_agent.py        # AI Agent 推送
├── config/                    # 配置文件
│   ├── keywords.json          # 产品线 + 关键词配置
│   ├── urls.txt               # 竞品账号 URL 列表
│   └── schedule_rules.json    # 定时轮询规则（当前为空）
├── data/                      # 采集输出数据（gitignored）
├── .env                       # 本地环境变量
├── requirements.txt           # Python 依赖
└── README.md                  # 本文件
```

## 快速开始

### 环境要求

- Python 3.12+
- Microsoft Edge 浏览器

### 安装

```bash
pip install -r requirements.txt
playwright install chromium
```

### 配置

编辑 `config/keywords.json` 配置搜索关键词。

编辑 `config/urls.txt` 配置竞品账号列表，格式：
```
# === 品牌名称 ===
小红书号（纯数字）或 weibo.com/xxx
```

### 启动

```bash
python web_server.py
```

服务启动后访问 http://localhost:5050，注册实例后即可使用。

### 启动选项

```bash
python web_server.py --port 5050          # 指定端口
python web_server.py --host 0.0.0.0       # 指定监听地址
python web_server.py --debug              # 调试模式
```

## 使用流程

1. **注册实例** — 设置实例名称、密码、RPC 地址、Sender ID
2. **添加平台账号** — 在实例配置中添加小红书/微博/抖音账号
3. **扫码登录** — 点击账号后的「扫码登录」，用手机 App 扫描二维码
4. **提交任务** — 在热搜/关键词/账号监控页面提交采集任务
5. **查看结果** — 任务完成后自动推送至 RPC Agent

## 架构说明

- 每个实例 = 一个独立的 Edge 浏览器进程 + CDP 端口 + User Data 目录
- 一个实例可以绑定多个平台账号（小红书/微博/抖音），各自扫码登录，cookies 保存在实例的 Edge profile 中
- 同实例的任务串行执行，不同实例的任务并行执行
- 任务提交前自动检查对应平台的登录状态，未登录则引导扫码

## 注意事项

- 各平台均需通过手机 App 扫码登录，没有密码登录入口
- 采集频率过高可能触发平台风控，脚本内置随机延迟
