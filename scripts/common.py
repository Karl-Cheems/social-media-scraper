"""
共享工具模块 — 浏览器启动、Edge 进程管理、数据输出
供 scripts/ 下各采集脚本复用。

核心功能：
  - CommentItem Pydantic 模型
  - kill_edge() — 强制关闭占用 User Data 的 Edge 进程
  - launch_browser() — 安全启动 Edge persistent context（重试 + 临时目录兜底）
  - get_edge_user_data() — 返回 Edge User Data 目录路径
  - write_output() — 将 Python 对象写入 JSON 文件或打印到 stdout
"""

import asyncio
import json
import os
import random
import re as _re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

from pydantic import BaseModel, Field
from playwright._impl._errors import TargetClosedError


class CommentItem(BaseModel):
    """单条评论"""

    user: str = Field(description="评论用户")
    content: str = Field(description="评论内容")
    likes: int = Field(description="评论点赞数")


# ---------- 随机延迟（风控规避） ----------


async def random_delay(min_sec: float = 4.0, max_sec: float = 8.0, label: str = ""):
    """随机等待 min_sec ~ max_sec 秒，模拟人类操作间隔。

    Args:
        min_sec: 最小等待秒数（默认 2s）
        max_sec: 最大等待秒数（默认 5s）
        label: 可选描述标签，用于调试日志
    """
    delay = random.uniform(min_sec, max_sec)
    if label:
        print(f"  ⏳ {label}（等待 {delay:.1f}s）", file=sys.stderr)
    await asyncio.sleep(delay)


# ---------- 时间归一化 ----------

def normalize_time(raw: str) -> str:
    """将相对时间（昨天、X小时前、X分钟前）转为实际日期 YYYY-MM-DD。"""
    if not raw:
        return ""
    raw = raw.strip()
    now = datetime.now()
    # 2026年06月09日 → YYYY-MM-DD
    m = _re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', raw)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # 昨天 HH:MM → 昨天日期
    m = _re.match(r'昨天\s*(\d{1,2}:\d{2})?', raw)
    if m:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    # 今天
    if '今天' in raw:
        return now.strftime("%Y-%m-%d")
    # N分钟前 / N小时前
    m = _re.match(r'(\d+)分钟前', raw)
    if m:
        return now.strftime("%Y-%m-%d")
    m = _re.match(r'(\d+)小时前', raw)
    if m:
        return now.strftime("%Y-%m-%d")
    # N天前
    m = _re.match(r'(\d+)天前', raw)
    if m:
        d = (now - timedelta(days=int(m.group(1))))
        return d.strftime("%Y-%m-%d")
    # 已经是 YYYY-MM-DD 格式
    if _re.match(r'^\d{4}-\d{2}-\d{2}', raw):
        return raw[:10]
    # MM-DD 格式 → 补充年份
    m = _re.match(r'^(\d{1,2})-(\d{1,2})', raw)
    if m:
        return f"{now.year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    # 返回原样
    return raw[:20]


# ---------- Edge 进程管理 ----------


def kill_edge():
    """关闭正在运行的 Edge 进程（User Data 被占用时 Playwright 无法启动）。"""
    try:
        result = subprocess.run(
            ["tasklist", "/fi", "imagename eq msedge.exe", "/nh"],
            capture_output=True, text=True, timeout=10,
        )
        if "msedge.exe" in result.stdout:
            print("检测到 Edge 正在运行，正在关闭...", file=sys.stderr)
            subprocess.run(
                ["taskkill", "/f", "/im", "msedge.exe"],
                capture_output=True, timeout=10,
            )
            print("Edge 已关闭", file=sys.stderr)
            import time as _t
            _t.sleep(3)  # 等待进程完全退出
    except Exception:
        pass


# ---------- 等待登录 ----------


async def wait_for_login(page, timeout: int = 300, check_interval: float = 1.5):
    """等待用户完成登录。

    每 1.5 秒检测一次页面内容，判断是否还在登录状态。
    支持小红书和微博的登录检测。
    超时时间默认 300 秒（5 分钟）。

    Args:
        page: Playwright page 对象
        timeout: 等待超时秒数（默认 300）
        check_interval: 检测间隔秒数（默认 1.5）
    """
    print("  ⏳ 请在浏览器窗口中完成登录（扫码/输入密码），脚本将自动继续...", file=sys.stderr)
    for _ in range(int(timeout / check_interval)):
        await asyncio.sleep(check_interval)
        try:
            # 检测页面是否还在登录状态（小红书/微博的登录弹窗）
            still_login = await page.evaluate("""() => {
                // 检查 URL 是否在登录页
                var url = location.href;
                if (url.indexOf('login') >= 0 || url.indexOf('passport') >= 0) return true;

                // 检查页面是否有登录弹窗/蒙层（小红书登录弹窗特征）
                var dialog = document.querySelector('.login-dialog, [class*=login], [class*=passport], .xhs-login, .weibo-login');
                if (dialog && dialog.offsetParent !== null) return true;

                // 检查有没有登录按钮（还没登录）
                var loginBtn = document.querySelector('[class*=login-btn], [class*=to-login]');
                if (loginBtn && loginBtn.offsetParent !== null) return true;

                // 检查是否能看到内容（说明已经登录了）
                var feeds = document.querySelector('.feeds-page, [class*=feed], [class*=note-item], [class*=home-container]');
                if (feeds) return false;

                return false; // 默认认为已登录
            }""")

            if not still_login:
                print("  ✅ 检测到登录成功，继续执行", file=sys.stderr)
                return True
        except Exception:
            # 页面可能在加载中，忽略
            pass

    print("  ⚠️ 等待登录超时（5分钟），请重启工具后重试", file=sys.stderr)
    return False


# ---------- 浏览器启动 ----------
def _find_edge_exe() -> str | None:
    """查找 Edge 可执行文件路径。"""
    # 1) where 命令
    try:
        result = subprocess.run(["where", "msedge"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0]
    except Exception:
        pass
    # 2) 常见安装路径
    for base in [
        os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
        os.environ.get("ProgramFiles", "C:\\Program Files"),
        os.environ.get("LOCALAPPDATA", ""),
    ]:
        p = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
        if os.path.isfile(p):
            return p
    return None


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

    # 生成随机调试端口，避免与其他程序冲突
    DEBUG_PORT = random.randint(10000, 60000)

    # 关闭旧 Edge 进程
    for _ in range(3):
        try:
            subprocess.run(["taskkill", "/f", "/t", "/im", "msedge.exe"],
                           capture_output=True, timeout=10)
        except Exception:
            pass
        await asyncio.sleep(1)
    print("  Edge 旧进程已清理", file=sys.stderr)

    # 创建独立 User Data 目录（Edge 要求必须是非默认目录才能开 CDP 调试端口）
    pw_data_dir = os.path.join(os.path.dirname(user_data_dir), "PlaywrightUserData")
    real_default = os.path.join(user_data_dir, "Default")

    if not os.path.exists(pw_data_dir):
        os.makedirs(pw_data_dir, exist_ok=True)
        if os.path.isdir(real_default):
            target_default = os.path.join(pw_data_dir, "Default")
            os.makedirs(target_default, exist_ok=True)
            for f in os.listdir(real_default):
                src = os.path.join(real_default, f)
                dst = os.path.join(target_default, f)
                if os.path.isfile(src):
                    try:
                        shutil.copy2(src, dst)
                    except Exception:
                        pass
        print("  Playwright 用户配置已初始化", file=sys.stderr)
    else:
        print(f"  使用已有 Playwright 配置", file=sys.stderr)

    # 清理锁文件
    for f in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        p2 = os.path.join(pw_data_dir, f)
        if os.path.exists(p2):
            try:
                os.remove(p2)
            except Exception:
                pass

    # 启动 Edge（用独立配置目录，这样才能开 CDP 端口）
    edge_process = subprocess.Popen(
        [
            edge_exe,
            f"--remote-debugging-port={DEBUG_PORT}",
            "--remote-allow-origins=*",
            f"--user-data-dir={pw_data_dir}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"  已启动 Edge (PID={edge_process.pid})", file=sys.stderr)

    # 等端口就绪
    import socket as _socket
    for i in range(15):
        await asyncio.sleep(1)
        try:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", DEBUG_PORT)) == 0:
                s.close()
                print(f"  Edge DevTools 就绪（+{i+1}s）", file=sys.stderr)
                break
            s.close()
        except Exception:
            pass
    else:
        print("  ⚠️ Edge 端口超时，尝试强行连接...", file=sys.stderr)

    # CDP 连接
    for i in range(5):
        try:
            browser = await p.chromium.connect_over_cdp(
                f"http://127.0.0.1:{DEBUG_PORT}"
            )
            print(f"  ✅ 已连接到你的 Edge", file=sys.stderr)
            break
        except Exception as e:
            if i < 4:
                await asyncio.sleep(2)
    else:
        print(f"  ❌ 连接 Edge 失败（5次重试后放弃）", file=sys.stderr)
        edge_process.kill()
        raise RuntimeError(f"无法连接 Edge DevTools 端口 {DEBUG_PORT}")

    # 取 context/page
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = context.pages[0] if context.pages else await context.new_page()

    return context, page, edge_process


# ---------- 小红书搜索（模拟点击）----------

async def xhs_search_by_input(page, keyword: str, label: str = ""):
    """在小红书搜索框输入关键词并搜索。
    模拟真实用户操作：点击搜索框 → 输入关键词 → 回车搜索。
    返回 True 如果成功导航到搜索结果页。
    """
    print(f"  🔍 搜索框输入: {keyword}", file=sys.stderr) if label else None
    try:
        # 1. 先回到 explore 页
        if "explore" not in page.url:
            await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

        # 2. 搜索框已直接可见（新版 XHS 无搜索区域遮罩层）
        search_input = page.locator("input#search-input.search-input").first
        await search_input.wait_for(state="visible", timeout=10000)
        await page.wait_for_timeout(random.randint(300, 800))
        await search_input.click()
        await page.wait_for_timeout(random.randint(500, 1000))

        # 3. 清空 → 逐字输入
        await search_input.fill("", timeout=5000)
        await page.wait_for_timeout(random.randint(200, 500))
        for ch in keyword:
            await page.keyboard.type(ch, delay=random.randint(50, 150))
        await page.wait_for_timeout(random.randint(800, 1500))

        # 4. 回车搜索
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(3000)

        # 5. 等待搜索结果加载
        try:
            await page.wait_for_url("**/search_result**/**", timeout=15000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
        return True
    except Exception as e:
        print(f"  ⚠️ 搜索框输入失败: {e}", file=sys.stderr)
        return False


def get_edge_user_data() -> str:
    """返回 Edge User Data 目录的完整路径。

    Returns:
        形如 C:\\Users\\<username>\\AppData\\Local\\Microsoft\\Edge\\User Data
    """
    return os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Microsoft",
        "Edge",
        "User Data",
    )


# ---------- 数据输出 ----------


def _auto_save(output, output_path: str | None = None) -> str | None:
    """每次运行自动保存到 data/ 子目录（时间戳命名），不影响原有的 output 行为。"""
    # 按脚本名分类到对应子目录
    caller = os.path.basename(sys.argv[0]).replace(".py", "")
    sub_dir = {
        "hot_search": "hot",
        "weibo_hot_search": "hot",
        "douyin_hot_search": "hot",
        "keyword_search": "keyword",
        "competitor_monitor": "account",
        "weibo_scraper": "account",
        "xiaohongshu_scraper": "account",
    }.get(caller, "")  # 未映射的保存在 data/ 根目录

    # 用 exe 所在目录或脚本所在目录定位 data 目录
    if getattr(sys, 'frozen', False):
        data_root = os.path.join(os.path.dirname(sys.executable), "data")
    else:
        data_root = os.path.join(os.path.dirname(__file__), "..", "data")
    data_dir = os.path.join(data_root, sub_dir) if sub_dir else data_root
    os.makedirs(data_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{caller}_{timestamp}.json"
    filepath = os.path.join(data_dir, filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"[自动保存] {filepath}", file=sys.stderr)
    except Exception as e:
        print(f"[自动保存失败] {e}", file=sys.stderr)
    return filepath


def write_output(output, output_path: str | None = None):
    """将 Python 对象写入 JSON 文件或打印到 stdout。

    行为：
      - 每次运行自动保存一份到 ../data/{脚本名}_{时间戳}.json
      - output_path 非 None → 写入文件
      - output_path 为 None → 写入临时文件 → 读取并打印到 stdout → 删除临时文件

    Args:
        output: 可被 json.dump 序列化的 Python 对象（通常为 dict）
        output_path: JSON 文件路径，为 None 时输出到 stdout
    """
    _auto_save(output, output_path)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"结果已保存到: {output_path}")
    else:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", delete=False
        )
        json.dump(output, tmp, ensure_ascii=False, indent=2)
        tmp.close()
        with open(tmp.name, "r", encoding="utf-8") as f:
            sys.stdout = open(
                sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace"
            )
            print(f.read())
        os.unlink(tmp.name)
