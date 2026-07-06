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
    except Exception:
        pass


# ---------- 等待登录 ----------


async def wait_for_login(page, timeout: int = 300, check_interval: float = 1.5):
    """等待用户完成登录（检测 URL 不再包含 login/passport 关键词）。

    在非无头模式下使用，检测到未登录后打开浏览器窗口，等待用户手动登录。
    每 1.5 秒检测一次 URL，超时时间默认 300 秒（5 分钟）。

    Args:
        page: Playwright page 对象
        timeout: 等待超时秒数（默认 300）
        check_interval: 检测间隔秒数（默认 1.5）
    """
    print("  请在浏览器窗口中完成登录，脚本将自动继续...", file=sys.stderr)
    for _ in range(int(timeout / check_interval)):
        await asyncio.sleep(check_interval)
        current_url = page.url
        if "login" not in current_url and "passport" not in current_url and "sso" not in current_url:
            print("  检测到登录成功，继续执行", file=sys.stderr)
            return True
    print("  ⚠️ 等待登录超时，请重启工具后重试", file=sys.stderr)
    return False


# ---------- 浏览器启动 ----------


async def launch_browser(
    p,
    headless: bool,
    user_data_dir: str,
    label: str = "app",
) -> tuple:
    """安全启动 Edge persistent context。

    策略：
      1. 尝试 2 次用指定 user_data_dir 启动
      2. 遇到 TargetClosedError → kill_edge() → 重试
      3. 最终 fallback：临时目录 + headless=False（需要手动登录）

    Returns:
        (context, page) 元组
    """
    for attempt in range(2):
        try:
            # headless 下检测到未登录时已经在外部处理了，这里直接启动
            # 首次启动如果 headless=True 但 Edge User Data 被占用，先 kill
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                channel="msedge",
                headless=headless,
                args=["--disable-sync"],
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()
            return context, page
        except Exception:  # 捕获 TargetClosedError 或权限错误
            print(
                f"  Edge 启动失败（attempt {attempt + 1}），正在关闭已有 Edge 进程...",
                file=sys.stderr,
            )
            kill_edge()
            await asyncio.sleep(2)

    # 最后一次尝试：用临时目录启动（需要用户手动登录）
    print(f"  使用临时用户目录启动 Edge（将弹出登录窗口）...", file=sys.stderr)
    temp_dir = tempfile.mkdtemp(prefix=f"{label}_scraper_")
    try:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=temp_dir,
            channel="msedge",
            headless=False,  # 临时目录无登录态，必须非无头
            args=["--disable-sync"],
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()
        print("  请在浏览器窗口中完成登录", file=sys.stderr)
        return context, page
    except Exception:
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


# ---------- Edge User Data 目录 ----------


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
