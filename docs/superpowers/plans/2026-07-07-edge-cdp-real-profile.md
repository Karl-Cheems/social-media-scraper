# Edge CDP 默认配置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `launch_browser()` 使用用户 Edge 的默认用户配置（Default 配置），继承所有登录态和 Cookie

**Architecture:** 去掉 `--user-data-dir=PlaywrightUserData` 自定义目录，让 Edge 使用系统默认的 User Data。继续用 CDP 协议连接真实浏览器。

**Tech Stack:** Python, Playwright, Edge CDP, subprocess

---

### Task 1: 修改 `launch_browser()` — 去掉自定义 User Data 目录

**Files:**
- Modify: `D:\Users\Desktop\网络热点搜集\scripts\common.py` (整个 `launch_browser` 函数从 164-246 行重写)

- [ ] **Step 1: 重写 `launch_browser()` 函数，去掉自定义 User Data 目录和锁文件清理**

```python
async def launch_browser(
    p,
    headless: bool,
    user_data_dir: str,
    label: str = "app",
) -> tuple:
    """用 CDP 连接你真实的 Edge 浏览器。

    启动 Edge 并开启调试端口，使用系统默认的 Default 用户配置，
    Playwright 通过 CDP 协议连接。登录态、Cookie 全部继承。

    Returns:
        (context, page, edge_process) 元组
    """
    edge_exe = _find_edge_exe()
    if not edge_exe:
        raise FileNotFoundError("找不到 Edge 浏览器，请确认已安装 Microsoft Edge")

    DEBUG_PORT = 9222

    # 2. 彻底杀掉所有旧 Edge 进程，释放调试端口
    for _ in range(3):
        try:
            subprocess.run(["taskkill", "/f", "/t", "/im", "msedge.exe"],
                           capture_output=True, timeout=10)
        except Exception:
            pass
        await asyncio.sleep(1)
    print("  Edge 旧进程已清理", file=sys.stderr)

    # 3. 启动 Edge，不带 --user-data-dir（使用系统默认的 Default 配置）
    edge_process = subprocess.Popen(
        [
            edge_exe,
            f"--remote-debugging-port={DEBUG_PORT}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"  已启动 Edge (端口 {DEBUG_PORT})", file=sys.stderr)

    # 4. 等几秒让浏览器启动 + DevTools 端口就绪
    await asyncio.sleep(5)

    # 5. 通过 CDP 连接（带 5 次重试）
    for i in range(5):
        try:
            browser = await p.chromium.connect_over_cdp(
                f"http://127.0.0.1:{DEBUG_PORT}"
            )
            print(f"  ✅ 已连接到你的 Edge", file=sys.stderr)
            break
        except Exception as e:
            if i < 4:
                print(f"  连接尝试 {i+1}/5 失败，2秒后重试...", file=sys.stderr)
                await asyncio.sleep(2)
    else:
        print(f"  ❌ 连接 Edge 失败（5次重试后放弃）", file=sys.stderr)
        edge_process.kill()
        raise RuntimeError(f"无法连接 Edge DevTools 端口 {DEBUG_PORT}")

    # 6. 取默认 context/page
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = context.pages[0] if context.pages else await context.new_page()

    return context, page, edge_process
```

- [ ] **Step 2: 验证改动**

手动检查改后的代码：
- `pw_data_dir` 相关代码已全部移除
- `--user-data-dir` 参数不再传入
- 锁文件清理代码已移除
- `--no-first-run` 参数已移除（用默认配置不需要这个）
- 返回值签名不变 `(context, page, edge_process)`
- `_find_edge_exe()` 辅助函数保持不动

### Task 2: 重建 exe + 复制到目标目录

- [ ] **Step 1: 用 PyInstaller 重建 exe**

```bash
cd "D:/Users/Desktop/网络热点搜集" && pyinstaller --clean --onefile --noconsole --name 社交监控工具 --add-data "D:/Users/Desktop/网络热点搜集/scripts;scripts" --add-data "D:/Users/Desktop/网络热点搜集/notify;notify" --add-data "D:/Users/Desktop/网络热点搜集/.env;." --hidden-import pydantic --hidden-import pydantic._internal --hidden-import regex --hidden-import httpx --hidden-import httpx._client --hidden-import certifi --distpath "dist/temp_dist" --workpath "temp_build" --specpath "temp_spec" social_monitor_gui.py 2>&1 | tail -3
```
Expected: UI final size line + "Build complete"

- [ ] **Step 2: 复制 exe + 清理临时文件**

```bash
cp "D:/Users/Desktop/网络热点搜集/dist/temp_dist/社交监控工具.exe" "D:/Users/Desktop/网络热点搜集/社交监控工具.exe" && rm -rf "D:/Users/Desktop/网络热点搜集/temp_build" "D:/Users/Desktop/网络热点搜集/temp_spec" "D:/Users/Desktop/网络热点搜集/dist/temp_dist" && echo "done"
```
Expected: "done"

### Task 3: 用户验证

- [ ] **Step 1: 用户关闭旧 exe，双击新版 exe**
  - 观察弹出的 Edge 窗口是否带默认配置（已登录的小红书/微博/抖音）
  - 观察 CDP 连接是否成功（日志显示 "✅ 已连接到你的 Edge"）
  - 观察日志是否不再乱码
