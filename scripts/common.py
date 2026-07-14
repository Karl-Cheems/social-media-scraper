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
import socket as _socket
import subprocess
import sys
import tempfile
import time as _time
from datetime import datetime, timedelta
from urllib.parse import quote

from pydantic import BaseModel, Field
from playwright._impl._errors import TargetClosedError


class ReplyItem(BaseModel):
    """子回复（评论的评论）"""
    user: str = Field(description="回复用户")
    content: str = Field(description="回复内容")
    likes: int = Field(description="回复点赞数")
    reply_to: str = Field(default="", description="回复对象用户名")


class CommentItem(BaseModel):
    """单条评论"""

    user: str = Field(description="评论用户")
    content: str = Field(description="评论内容")
    likes: int = Field(description="评论点赞数")
    replies: list[ReplyItem] = Field(default_factory=list, description="子回复列表")


# ── 小红书评论区展开 + 提取（公用函数）─────────────────────────────

_XHS_EXPAND_JS = """
() => {
    var btns = document.querySelectorAll('.comments-container .show-more, .comments-container [class*=expand]');
    var vh = window.innerHeight;
    var count = 0;
    for (var btn of btns) {
        var t = (btn.textContent || '').trim();
        var r = btn.getBoundingClientRect();
        if (r.top < vh + 200 && r.bottom > -200 &&
            t.indexOf('条回复') >= 0 && t.indexOf('展开更多') < 0 &&
            btn.dataset._ex_done !== '1') {
            btn.dataset._ex_done = '1';
            btn.scrollIntoView({block: 'center'});
            btn.click();
            count++;
        }
    }
    return count;
}
"""

_XHS_EXTRACT_COMMENTS_JS = """
(maxComments) => {
    function pc(s) { if (!s) return 0; s = s.replace(',',''); if (s.includes('万')) return Math.round(parseFloat(s)*10000); var n = parseInt(s,10); return isNaN(n)?0:n; }
    function countContentImgs(el) {
        var imgs = el.querySelectorAll('img');
        var count = 0;
        for (var i = 0; i < imgs.length; i++) {
            var img = imgs[i];
            if (img.classList.contains('avatar-item')) continue;
            var rect = img.getBoundingClientRect();
            if (rect.width < 40 || rect.height < 40) continue;
            count++;
        }
        return count;
    }
    var items = document.querySelectorAll('.comments-container .parent-comment');
    var result = [];
    var totalImgs = 0;
    var max = Math.min(items.length, maxComments);
    for (var i = 0; i < max; i++) {
        var c = items[i];
        var pi = c.querySelector(':scope > .comment-item');
        if (!pi) continue;
        var nameEl = pi.querySelector('.author .name');
        var userName = nameEl ? nameEl.textContent.trim() : '';
        var noteText = pi.querySelector('.content .note-text');
        var content = noteText ? noteText.textContent.trim() : '';
        var likeNum = pi.querySelector('.like-wrapper .count');
        var likeText = likeNum ? likeNum.textContent.trim() : '';
        var likes = 0;
        if (likeText && likeText !== '赞') likes = pc(likeText);
        if (!userName || !content) continue;
        var imgCount = countContentImgs(c);
        totalImgs += imgCount;
        var replies = [];
        var subItems = c.querySelectorAll('.reply-container .comment-item-sub');
        for (var j = 0; j < subItems.length; j++) {
            var s = subItems[j];
            var sName = s.querySelector('.author .name');
            var sText = s.querySelector('.content .note-text');
            var sLike = s.querySelector('.like-wrapper .count');
            var sUserName = sName ? sName.textContent.trim() : '';
            var sContent = sText ? sText.textContent.trim() : '';
            var sLikes = 0;
            if (sLike) { var st = sLike.textContent.trim(); if (st && st !== '赞') sLikes = pc(st); }
            var replyTo = '';
            var atEl = s.querySelector('.at-text, [class*=_at_]');
            if (atEl) replyTo = atEl.textContent.trim().replace('@','');
            if (sUserName && sContent) replies.push({ user: sUserName, content: sContent, likes: sLikes, reply_to: replyTo, images: countContentImgs(s) });
        }
        result.push({ user: userName, content: content, likes: likes, replies: replies, images: imgCount });
    }
    return { comments: result, total_comment_images: totalImgs };
}
"""


async def xhs_expand_comments(page, max_comments: int, max_rounds: int = 80, container_scroll: bool = False):
    """在小红书详情页面滚动加载评论并依次点击子回复展开按钮。

    策略：每轮先扫当前视口的展开按钮 → btn.click() 点掉 → 检查计数 → 滚动。
    滚动步长 600px。

    Args:
        container_scroll: True=滚动 .comments-container 容器（SPA弹窗详情页），
                          False=滚动 window（独立页面详情页）
    Returns:
        (comments_list, total_comment_images) 评论列表和评论区图片总数
    """
    container = page.locator(".comments-container").first
    if not await container.is_visible(timeout=3000):
        return [], 0
    await container.hover()
    await page.wait_for_timeout(300)

    prev_cnt = 0
    stale_rounds = 0  # 连续几轮评论数没变化
    scroll_step = 600

    for _ in range(max_rounds):
        # 第一步：点展开
        clicked = await page.evaluate(_XHS_EXPAND_JS)
        if clicked:
            await page.wait_for_timeout(500)

        # 第二步：检查计数
        current_cnt = await page.evaluate(
            "document.querySelectorAll('.comments-container .parent-comment').length"
        )
        if current_cnt >= max_comments:
            break

        # 第三步：检测是否卡住了
        if current_cnt == prev_cnt:
            if not clicked:
                stale_rounds += 1
                if stale_rounds >= 5:
                    break
        else:
            stale_rounds = 0
        prev_cnt = current_cnt

        # 第四步：滚动
        if container_scroll:
            # SPA 弹窗详情页（keyword_search/xiaohongshu_scraper模式）
            # 注意：.comments-container 是 overflow-y: visible，对它 scrollBy 无效
            # 真正的可滚动容器是 .note-scroller (overflow-y: scroll)
            # 先把最后一条 parent-comment 滚到视口底部，再微调触发懒加载
            await page.evaluate(f"""
                (() => {{
                    var items = document.querySelectorAll('.note-scroller .parent-comment');
                    if (items.length > 0) {{
                        items[items.length - 1].scrollIntoView({{block: 'end'}});
                    }}
                    var ns = document.querySelector('.note-scroller');
                    if (ns) ns.scrollBy(0, {scroll_step});
                    // fallback: 尝试 mouse wheel 模拟
                    if (!ns) window.scrollBy(0, {scroll_step});
                }})()
            """)
        else:
            # 独立详情页（url_detail 模式）：直接滚动 window
            await page.evaluate(f"window.scrollBy(0, {scroll_step})")
        await page.wait_for_timeout(800)

    await page.wait_for_timeout(1500)
    result = await page.evaluate(_XHS_EXTRACT_COMMENTS_JS, max_comments)
    return result.get("comments", []), result.get("total_comment_images", 0)


def xhs_extract_comments(page, max_comments: int):
    """仅提取已经加载好的评论数据，不滚动不展开。

    供已自行处理了展开的场景使用。

    Returns:
        (comments_list, total_comment_images) 评论列表和评论区图片总数
    """
    result = page.evaluate(_XHS_EXTRACT_COMMENTS_JS, max_comments)
    return result.get("comments", []), result.get("total_comment_images", 0)


def flatten_comments(comments_list: list) -> str:
    """将评论列表扁平化为纯文本，只保留内容。

    输入: [{"user":"A","content":"好","likes":5,"replies":[{"user":"B","content":"+1","likes":2}]}]
    输出: "好\n  回复: +1\n---"
    """
    lines = []
    for c in comments_list:
        text = (c.get("content", "") or "").strip()
        if not text:
            text = (c.get("text", "") or "").strip()
        if text:
            lines.append(text)
        for r in c.get("replies", []):
            rt = (r.get("content", "") or "").strip()
            if rt:
                lines.append(f"  回复: {rt}")
        lines.append("---")
    return "\n".join(lines)


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


# ---------- 共享 Edge 锁 ----------
# 多个脚本进程共享同一个 Edge 实例，避免互相 kill
_EDGE_LOCK = os.path.join(tempfile.gettempdir(), "social_monitor_edge_port.txt")


def _edge_lock_read() -> int | None:
    """读取锁文件，获取正在运行的 Edge CDP 端口。"""
    try:
        if os.path.isfile(_EDGE_LOCK):
            with open(_EDGE_LOCK) as f:
                data = json.load(f)
            # 检查锁是否过期（进程是否还活着）
            pid = data.get("pid", 0)
            if pid:
                r = subprocess.run(
                    ["tasklist", "/fi", f"PID eq {pid}", "/nh"],
                    capture_output=True, text=True, timeout=5,
                )
                if "msedge.exe" in r.stdout:
                    return data["port"]
            # 进程已死，清理锁
            os.remove(_EDGE_LOCK)
    except Exception:
        pass
    return None


def _edge_lock_write(port: int, pid: int):
    """写入锁文件。"""
    try:
        with open(_EDGE_LOCK, "w") as f:
            json.dump({"port": port, "pid": pid})
    except Exception:
        pass


def _edge_lock_clear():
    """清除锁文件。"""
    try:
        if os.path.isfile(_EDGE_LOCK):
            os.remove(_EDGE_LOCK)
    except Exception:
        pass


async def launch_browser(
    p,
    headless: bool,
    user_data_dir: str,
    label: str = "app",
) -> tuple:
    """用 CDP 连接 Edge 浏览器。多进程共享同一个 Edge 实例。

    核心逻辑：
      1. 检查锁文件 → 已有 Edge 在运行 → 直接 CDP 连接，不杀进程
      2. 没有锁 → 启动新 Edge → 写入锁文件

    Returns:
        (context, page, edge_process) 元组
    """
    edge_exe = _find_edge_exe()
    if not edge_exe:
        raise FileNotFoundError("找不到 Edge 浏览器，请确认已安装 Microsoft Edge")

    # ── 尝试连接已有 Edge 实例 ──
    existing_port = _edge_lock_read()
    if existing_port:
        print(f"  🔗 检测到已有的 Edge（端口 {existing_port}），直接连接...", file=sys.stderr)
        for i in range(5):
            try:
                browser = await p.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{existing_port}"
                )
                print(f"  ✅ 已连接到已有的 Edge", file=sys.stderr)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                # 清理旧页签：保留第一个 page，关闭其余所有
                pages = context.pages
                if pages:
                    first_page = pages[0]
                    # 关闭多余的页签
                    for cp in pages[1:]:
                        try:
                            await cp.close()
                        except Exception:
                            pass
                    # 清空第一个页签（导航到 about:blank）
                    try:
                        await first_page.goto("about:blank", wait_until="commit", timeout=10000)
                    except Exception:
                        pass
                    page = first_page
                else:
                    page = await context.new_page()
                return context, page, None  # None = 非本进程启动的 Edge
            except Exception as e:
                if i < 4:
                    await asyncio.sleep(2)
        print(f"  ⚠️ 连接已有 Edge 失败，将重新启动", file=sys.stderr)
        _edge_lock_clear()

    # ── 启动新 Edge ──
    # 生成随机调试端口
    DEBUG_PORT = random.randint(10000, 60000)

    # 关闭旧 Edge 进程（仅当没有锁时）
    for _ in range(3):
        try:
            subprocess.run(["taskkill", "/f", "/t", "/im", "msedge.exe"],
                           capture_output=True, timeout=10)
        except Exception:
            pass
        await asyncio.sleep(1)
    print("  Edge 旧进程已清理", file=sys.stderr)

    # 创建独立 User Data 目录
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

    # 启动 Edge
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

    # 写入锁文件
    _edge_lock_write(DEBUG_PORT, edge_process.pid)

    # 取 context/page
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = context.pages[0] if context.pages else await context.new_page()

    return context, page, edge_process


# ---------- 小红书搜索（模拟点击）----------

async def detect_xhs_ui_version(page) -> str:
    """检测当前小红书是旧版UI、新版AI布局、还是其他变体。
    等待页面加载稳定后再检测（至少等网络空闲或主要内容出现）。
    Returns: 'classic' 或 'ai-layout'
    """
    # 等页面 main 内容渲染完成（SPA 需要时间）
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    await page.wait_for_timeout(1000)
    return await page.evaluate("""() => {
        // 1. 看 body class
        var cls = document.body.className || '';
        if (cls.includes('ai-layout-active')) return 'ai-layout';

        // 2. 看搜索框类型 — ai-layout 用 textarea，classic 用 input
        var textareaInput = document.querySelector('textarea#search-input');
        var classicInput = document.querySelector('input#search-input.search-input');
        if (textareaInput) return 'ai-layout';
        if (classicInput) return 'classic';

        // 3. 看是否存在 ai 相关的 DOM 特征
        var hasAiChat = document.querySelector('.ai-chat-filter, [class*=ai-header], [class*=ai_search]');
        if (hasAiChat) return 'ai-layout';

        // 4. 默认通过 url 判断
        var url = location.href || '';
        if (url.includes('search_result')) return 'ai-layout';

        return 'classic';
    }""")


async def _xhs_search_ai_layout(page, keyword: str) -> bool:
    """新版小红书 AI 布局的搜索逻辑。
    尝试从搜索结果页或 explore 页搜索。
    """
    # 判断是否已在搜索结果页
    if "search_result" in page.url:
        # 已在搜索结果页，直接操作 header 中的 textarea#search-input
        try:
            search_input = page.locator("textarea#search-input").first
            await search_input.wait_for(state="visible", timeout=5000)
            await search_input.click(force=True)
            await page.wait_for_timeout(500)
            # 全选清空
            await page.keyboard.press("Control+a")
            await page.wait_for_timeout(200)
            await page.keyboard.type(keyword, delay=random.randint(40, 80))
            await page.wait_for_timeout(500)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(3000)
            # 等待 URL 变化到搜索页（不求完美匹配，只等页面导航完成）
            for _ in range(15):
                if "search_result" in page.url:
                    break
                await page.wait_for_timeout(500)
            await page.wait_for_timeout(1000)
            return True
        except Exception:
            pass  # 回退到 explore 方式

    # 从 explore 页搜索
    # 先确保在 explore 首页（小红书可能自动跳转到 search_result）
    for _ in range(3):
        await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        if "explore" in page.url and "search_result" not in page.url:
            break
        print(f"    页面自动跳转走，重试 explore...", file=sys.stderr)

    # 尝试多种选择器找搜索框
    selectors = [
        ".search-area.search-area-opacity",
        "textarea#search-input",
        "input#search-input",
        "[class*=search] input",
        "[class*=search] textarea",
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.click(force=True)
                await page.wait_for_timeout(500)
                break
        except Exception:
            continue
    else:
        print(f"    无法定位搜索框", file=sys.stderr)
        return False

    # 直接 keyboard.type 到 activeElement
    await page.keyboard.type(keyword, delay=random.randint(40, 80))
    await page.wait_for_timeout(500)

    # Enter 提交
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(2000)
    for _ in range(15):
        if "search_result" in page.url:
            break
        await page.wait_for_timeout(500)
    await page.wait_for_timeout(1000)
    return True


async def xhs_search_by_input(page, keyword: str, label: str = ""):
    """在小红书搜索框输入关键词并搜索。
    自动适配：
    - 旧版UI (classic): 从 explore 页搜索
    - 新版UI (ai-layout): 直接在搜索页替换关键词或从 explore 搜索
    返回 True 如果成功导航到搜索结果页。
    """
    print(f"  🔍 搜索框输入: {keyword}", file=sys.stderr) if label else None
    try:
        # 0. 先关闭可能残留的详情遮罩层
        try:
            mask_close = page.locator(".note-detail-mask .close, [class*=mask] .close, .xgplayer-replay, .note-detail-mask")
            if await mask_close.first.is_visible(timeout=1000):
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(500)
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(500)
        except Exception:
            pass

        # 1. 标准化：如果当前在详情页（explore/xxx），先回到 explore 首页
        #    否则 UI 版本检测会因详情页缺少搜索框 DOM 而误判为 classic
        if "/explore/" in page.url:
            await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
            # 等小红书 VUE SPA 真正渲染完成——任一搜索框出现就代表页面就绪
            try:
                await page.locator("textarea#search-input, input#search-input.search-input").first.wait_for(state="visible", timeout=15000)
            except Exception:
                # 超时也继续，后面检测会判断
                pass

        # 2. 检测UI版本
        ui_version = await detect_xhs_ui_version(page)
        if label:
            print(f"  UI版本: {ui_version}", file=sys.stderr)

        if ui_version == "ai-layout":
            # ── 新版UI (ai-layout) ──
            ok = await _xhs_search_ai_layout(page, keyword)
            if ok:
                return True
            # ai 方式失败，fallback 到 goto 搜索页
            print(f"    新版UI搜索失败，回退到直连搜索页", file=sys.stderr)
            await page.goto(f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}&source=web_search_result_notes", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            return True
        else:
            # ── 旧版UI (classic) ──
            # 先回到 explore 页
            if "explore" not in page.url:
                await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)

            search_input = page.locator("input#search-input.search-input").first
            try:
                await search_input.wait_for(state="visible", timeout=5000)
                await page.wait_for_timeout(random.randint(300, 800))
                await search_input.click()
                await page.wait_for_timeout(random.randint(500, 1000))
                await search_input.fill("", timeout=5000)
                await page.wait_for_timeout(random.randint(200, 500))

                # 逐字输入
                for ch in keyword:
                    await page.keyboard.type(ch, delay=random.randint(50, 150))
                await page.wait_for_timeout(random.randint(800, 1500))

                # 回车搜索
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(2000)

                # 等待搜索结果加载
                for _ in range(15):
                    if "search_result" in page.url:
                        break
                    await page.wait_for_timeout(500)
                await page.wait_for_timeout(1000)
                return True
            except Exception as e:
                print(f"    经典UI搜索框不存在（可能实际是AI新UI），切换到AI方式: {e}", file=sys.stderr)
                # fallback: 用 ai-layout 方式
                ok = await _xhs_search_ai_layout(page, keyword)
                if ok:
                    return True
                # 终极 fallback：直接 goto
                await page.goto(f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}&source=web_search_result_notes", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)
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


def write_output(output, output_path: str | None = None):
    """将 Python 对象写入 JSON 文件或打印到 stdout。

    数据保存由 notify_agent.py 统一管理，此函数不再单独保存。

    Args:
        output: 可被 json.dump 序列化的 Python 对象（通常为 dict）
        output_path: JSON 文件路径，为 None 时输出到 stdout
    """
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
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
