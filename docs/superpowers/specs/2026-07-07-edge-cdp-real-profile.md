# Edge 浏览器 CDP 连接方案 — 使用系统默认用户配置

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 `launch_browser()` 打开全新空 Edge 的问题，让 Playwright 通过 CDP 连接时使用用户真实的 Edge 配置（登录态、Cookie、书签全部继承）

**Architecture:** `launch_browser()` 不再使用独立的 `PlaywrightUserData` 目录，改为使用系统默认的 Edge User Data 路径。杀掉旧 Edge 进程后启动新实例，通过 `--remote-debugging-port` 让 Playwright 通过 CDP 连接真实浏览器。

**Tech Stack:** Python, Playwright, Edge CDP, subprocess

---

## 问题分析

当前 `launch_browser()` 的问题：

| 代码位置 | 问题 |
|----------|------|
| `--user-data-dir=PlaywrightUserData` | 指向一个全新的空配置目录 |
| `taskkill /f /t /im msedge.exe` | 杀掉用户正在用的 Edge |
| `--no-first-run` | 指示这是一个新安装，跳过首次体验，进一步确认是新配置 |

结果：打开的 Edge 像刚安装的一样，要重新登录所有网站。

## 解决方案

**去掉自定义 `--user-data-dir` 参数，让 Edge 使用系统默认的用户配置。**

Edge 默认用户数据路径（用户确认过）：
```
C:\Users\YQSL\AppData\Local\Microsoft\Edge\User Data
```

### 改动

只改 `scripts/common.py` 中的 `launch_browser()` 函数：

1. **不再创建 `pw_data_dir`** — 去掉 `PlaywrightUserData` 目录的创建和锁文件清理
2. **去掉 `--user-data-dir=PlaywrightUserData`** 参数 — 让 Edge 用默认配置
3. **杀掉旧进程后直接启动** — 不带任何自定义数据目录标志
4. **简化流程** — 杀 → 启动带调试端口 → 等待就绪 → CDP 连接

### 不动的部分

- 所有调用 `launch_browser()` 的地方不改（返回值签名不变）
- 所有其他脚本不改
- 断点续传、`random_delay`、`wait_for_login` 等辅助函数不改

### 预期效果

- 打开的 Edge 窗口有完整的用户配置（已登录的小红书、微博、抖音）
- 不再需要反检测注入脚本（千真万确是真浏览器）
- 启动快（不需要初始化新配置文件）
- 登录态永久保存（就是 Edge 的默认配置）

## 实现步骤

### 步骤 1：修改 `scripts/common.py` — 重写 `launch_browser()`

```python
async def launch_browser(p, headless, user_data_dir, label="app"):
    # 1. 查找 Edge 可执行文件
    edge_exe = _find_edge_exe()

    # 2. 杀掉所有 Edge 进程（释放 9222 端口和 User Data 锁）
    DEBUG_PORT = 9222
    for _ in range(3):
        subprocess.run(["taskkill", "/f", "/t", "/im", "msedge.exe"], ...)
        await asyncio.sleep(1)

    # 3. 启动 Edge，不带 --user-data-dir（使用系统默认的 Default 配置）
    edge_process = subprocess.Popen([
        edge_exe,
        f"--remote-debugging-port={DEBUG_PORT}",
    ], ...)

    # 4. 等 5 秒让 DevTools 就绪
    await asyncio.sleep(5)

    # 5. CDP 连接（带 5 次重试）
    for i in range(5):
        try:
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{DEBUG_PORT}")
            break
        except Exception as e:
            await asyncio.sleep(2)

    # 6. 取已有的 context/page
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else await context.new_page()
    return context, page, edge_process
```

### 步骤 2：验证

1. 运行 `python -c "from common import launch_browser; ..."` 测试 CDP 连接
2. 打开后检查浏览器是否显示已登录的小红书/微博/抖音
3. 重建 exe + 全功能回归测试（热搜、关键词搜索、竞品监控）

### 不涉及

- 反检测脚本（不需要了，是真浏览器）
- `kill_edge()` 函数（保留不动，但不再被主流程调用）
- notify/ 目录
- GUI 代码
