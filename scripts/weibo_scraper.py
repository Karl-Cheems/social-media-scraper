"""
微博账号内容运营数据采集脚本
使用 Playwright + Edge 浏览器，抓取指定账号发布的微博数据

用法：
    python weibo_scraper.py
    python weibo_scraper.py --limit 10
    python weibo_scraper.py --limit 5 --comments --output result.json
"""

import argparse
import asyncio
import json
import os
import sys

from pydantic import BaseModel, Field
from playwright.async_api import async_playwright


class CommentItem(BaseModel):
    """单条评论"""
    user: str = Field(description="评论用户")
    content: str = Field(description="评论内容")
    likes: int = Field(description="评论点赞数")


class WeiboEngagement(BaseModel):
    """单条微博的运营数据结构"""
    text: str = Field(description="微博正文")
    reposts: int = Field(description="转发数")
    comments: int = Field(description="评论数")
    likes: int = Field(description="点赞数")
    comments_list: list[CommentItem] = Field(default_factory=list, description="评论列表")
    url: str = Field(description="微博链接")


class ProfileResult(BaseModel):
    """账号内容汇总"""
    author: str = Field(description="账号名称")
    total_collected: int = Field(description="实际采集到的微博数量")
    weibos: list[WeiboEngagement] = Field(description="微博运营数据列表")


# 元气森林官方微博主页（锐意进去自动跳到自己的首页，还是加?feature=homepage）
DEFAULT_PROFILE_URL = "https://weibo.com/5822662089?refer_flag=1001030103_"


def _kill_edge():
    """关闭正在运行的 Edge 进程（User Data 被占用时 Playwright 无法启动）。"""
    import subprocess
    try:
        result = subprocess.run(
            ["tasklist", "/fi", "imagename eq msedge.exe", "/nh"],
            capture_output=True, text=True, timeout=10
        )
        if "msedge.exe" in result.stdout:
            print("检测到 Edge 正在运行，正在关闭...", file=sys.stderr)
            subprocess.run(["taskkill", "/f", "/im", "msedge.exe"],
                           capture_output=True, timeout=10)
            print("Edge 已关闭", file=sys.stderr)
    except Exception:
        pass


async def _launch_browser(p, headless: bool, user_data_dir: str, **kwargs):
    """安全启动 Edge，如遇 User Data 被占用则自动杀进程重试。

    Returns: (context, page) 或抛出异常。
    """
    import tempfile
    from playwright._impl._errors import TargetClosedError

    for attempt in range(2):
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                channel="msedge",
                headless=headless,
                args=["--disable-sync"],
                viewport={"width": 1920, "height": 1080},
                **kwargs,
            )
            page = await context.new_page()
            return context, page
        except TargetClosedError:
            print(f"  Edge 启动失败（attempt {attempt+1}），正在关闭已有 Edge 进程...", file=sys.stderr)
            _kill_edge()
            await asyncio.sleep(2)

    # 最后一次尝试：用临时目录启动（需要用户手动登录）
    print("  使用临时用户目录启动 Edge（将弹出登录窗口）...", file=sys.stderr)
    temp_dir = tempfile.mkdtemp(prefix="weibo_scraper_")
    try:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=temp_dir,
            channel="msedge",
            headless=False,  # 临时目录无登录态，必须非无头
            args=["--disable-sync"],
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()
        print("  请在浏览器窗口中扫码/密码登录微博账号", file=sys.stderr)
        return context, page
    except Exception:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


async def scrape_profile(
    profile_url: str = DEFAULT_PROFILE_URL,
    limit: int = 10,
    headless: bool = True,
    fetch_comments: bool = False,
    max_comments: int = 10,
) -> ProfileResult:
    """打开微博账号主页，采集该账号发布的微博数据。"""
    weibos = []
    author_name = ""
    edge_user_data = os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data"
    )

    async with async_playwright() as p:
        context, page = await _launch_browser(p, headless=headless, user_data_dir=edge_user_data)

        try:
            print(f"正在打开用户主页: {profile_url}", file=sys.stderr)
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(8000)

            # 检测是否登录
            current_url = page.url
            login_detected = (
                "login" in current_url or "passport" in current_url
                or "微博" not in await page.title()
            )
            if login_detected and headless:
                print("\n⚠️ 检测到未登录状态，将打开浏览器窗口供您登录...", file=sys.stderr)
                print("请在浏览器窗口中完成登录后，等待脚本自动继续\n", file=sys.stderr)
                await context.close()
                context, page = await _launch_browser(
                    p, headless=False, user_data_dir=edge_user_data
                )
                await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(12000)

            # 获取账号名称
            author_name = await page.evaluate(
                "() => {"
                "  var el = document.querySelector('[class*=name] span, [class*=nick] span, [class*=_name_]');"
                "  return el ? el.textContent.trim() : document.title.split('的个人主页')[0].replace('@','').trim();"
                "}"
            )
            print(f"账号名称: {author_name or '（未识别）'}", file=sys.stderr)

            # 微博用虚拟滚动（vue-recycle-scroller），DOM 始终 ~7 个 article
            # 策略：滚动 + 持续提取文本，累计到够为止
            weibo_data = []
            seen_texts = set()
            scroll_rounds = 0
            while len(weibo_data) < limit and scroll_rounds < 30:
                await page.evaluate("window.scrollBy(0, 1200)")
                await page.wait_for_timeout(2000)

                batch = await page.evaluate(
                    """() => {
                        var arts = document.querySelectorAll('article');
                        var r = [];
                        for (var i = 0; i < arts.length; i++) {
                            var a = arts[i];
                            var textEl = a.querySelector('[class*=_text_], [class*=_wbtext_], [class*=_ogText_]');
                            var text = textEl ? textEl.textContent.trim() : '';
                            if (!text) text = (a.textContent || '').trim();

                            var detailUrl = '';
                            var timeLink = a.querySelector('[class*=_time_]');
                            if (timeLink) {
                                var href = timeLink.getAttribute('href') || '';
                                if (href && !href.startsWith('http')) href = 'https:' + href;
                                if (href.includes('weibo.com')) detailUrl = href;
                            }

                            var footer = a.querySelector('footer');
                            var reposts = -1, comments = -1, likes = -1;
                            if (footer) {
                                var numEls = footer.querySelectorAll('[class*=_num_]');
                                for (var j = 0; j < numEls.length; j++) {
                                    var t = numEls[j].textContent.trim();
                                    if (!t) continue;
                                    if (t === '转发') { reposts = 0; continue; }
                                    if (t === '评论' || t === '赞') continue;
                                    var n = parseInt(t.replace(/,/g, ''), 10);
                                    if (isNaN(n) || n < 0) continue;
                                    if (j === 0) reposts = n;
                                    else if (j === 1) comments = n;
                                }
                                var likeEl = footer.querySelector('[class*=woo-like-count]');
                                if (likeEl) {
                                    var lt = likeEl.textContent.trim();
                                    if (lt) { var ln = parseInt(lt.replace(/,/g, ''), 10); if (!isNaN(ln)) likes = ln; }
                                }
                            }

                            if (text.length > 10) {
                                r.push({ text: text, reposts: reposts, comments: comments, likes: likes, url: detailUrl });
                            }
                        }
                        return r;
                    }"""
                )

                # 用正文前 100 字去重（虚拟滚动下内容会被替换）
                new_items = 0
                for item in batch:
                    key = (item.get("text") or "")[:100]
                    if key and key not in seen_texts:
                        seen_texts.add(key)
                        weibo_data.append(item)
                        new_items += 1

                if new_items == 0:
                    scroll_rounds += 1
                else:
                    scroll_rounds = 0

                print(f"  滚动中... 累计 {len(weibo_data)} 条微博", file=sys.stderr)

            # 取最新的 limit 条（保持 DOM 顺序，最上面最新）
            weibo_data = weibo_data[:limit]
            print(f"取前 {len(weibo_data)} 条最新微博", file=sys.stderr)

            # 第二阶段：进入详情页获取完整正文（详情页不被截断），如有需要同时取评论
            print(f"\n进入详情页获取完整正文...", file=sys.stderr)
            for idx, item in enumerate(weibo_data):
                text_short = (item.get("text", "") or "")[:30]
                reposts = item.get("reposts", -1)
                comment_count = item.get("comments", -1)
                likes = item.get("likes", -1)
                detail_url = item.get("url", "")

                full_text = ""
                comments_list = []

                if detail_url:
                    try:
                        await page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(4000)

                        # 从详情页提取完整正文
                        full_text = await page.evaluate("""
                            () => {
                                // 找所有包含正文文本的元素，选最长的那个（跳过短文本/导航按钮）
                                var candidates = document.querySelectorAll(
                                    '[class*=_ogText_], [class*=_text_], [class*=_wbtext_]'
                                );
                                var best = '';
                                for (var el of candidates) {
                                    var t = (el.textContent || '').trim();
                                    if (t.length > best.length) best = t;
                                }
                                return best.length > 20 ? best : '';
                            }
                        """)

                        # 多次滚动以触发评论加载
                        if fetch_comments:
                            for _ in range(3):
                                await page.evaluate("window.scrollBy(0, 1500)")
                                await page.wait_for_timeout(1500)

                            comments_list = await page.evaluate(
                                """(maxC) => {
                                    var text = document.body.innerText || '';
                                    var lines = text.split('\\n').filter(function(l){return l.trim()});

                                    var commentStart = -1;
                                    for (var i = 0; i < lines.length; i++) {
                                        if (lines[i] === '评论') { commentStart = i + 1; break; }
                                    }
                                    if (commentStart < 0) return [];

                                    var idx = commentStart;
                                    while (idx < lines.length && (lines[idx] === '按热度' || lines[idx] === '按时间')) idx++;

                                    idx += 4;

                                    var result = [];
                                    var pendingUser = '';
                                    var pendingContent = '';
                                    var inContent = false;
                                    for (var j = idx; j < lines.length; j++) {
                                        var l = lines[j];
                                        if (l === '已加载全部评论' || l === '分享这条博文') break;
                                        if (result.length >= maxC) break;

                                        if (l.indexOf(':') === 0) {
                                            pendingContent = l.substring(1).trim();
                                            inContent = true;
                                        } else if (/^\\d{1,2}-\\d{1,2}-\\d{1,2}/.test(l) || l.indexOf('发布于') >= 0 || l.indexOf('来自') >= 0) {
                                            if (inContent) {
                                                result.push({ user: pendingUser || '(未知)', content: pendingContent || '', likes: 0 });
                                                pendingUser = '';
                                                pendingContent = '';
                                                inContent = false;
                                            }
                                        } else if (/^\\d+$/.test(l)) {
                                        } else {
                                            if (inContent) {
                                                result.push({ user: pendingUser || '(未知)', content: pendingContent || '', likes: 0 });
                                                pendingUser = '';
                                                pendingContent = '';
                                            }
                                            pendingUser = l;
                                            pendingContent = '';
                                            inContent = false;
                                        }
                                    }
                                    if (pendingUser && inContent) {
                                        result.push({ user: pendingUser, content: pendingContent || '', likes: 0 });
                                    }
                                    return result;
                                }""",
                                max_comments
                            )
                    except Exception as e:
                        print(f"  [{idx+1}] 详情页异常: {e}", file=sys.stderr)

                # 如果没有取到详情页完整文本，回退到首页截断文本
                if not full_text:
                    full_text = (item.get("text", "") or "")[:300]

                weibo = WeiboEngagement(
                    text=full_text,
                    reposts=reposts,
                    comments=comment_count,
                    likes=likes,
                    url=detail_url,
                    comments_list=[CommentItem(**c) for c in comments_list],
                )
                weibos.append(weibo)
                rs = f"{reposts}" if reposts >= 0 else "?"
                cs = f"{comment_count}" if comment_count >= 0 else "?"
                ls = f"{likes}" if likes >= 0 else "?"
                label = f"  [{len(weibos)}] {full_text[:24]}... 转={rs} 评={cs} 赞={ls}"
                if fetch_comments and comments_list:
                    label += f" 评论{len(comments_list)}条"
                print(label, file=sys.stderr)

        finally:
            await context.close()

    return ProfileResult(
        author=author_name or "元气森林官方微博",
        total_collected=len(weibos),
        weibos=weibos,
    )


def main():
    parser = argparse.ArgumentParser(
        description="微博账号内容运营数据采集工具"
    )
    parser.add_argument("--limit", "-n", type=int, default=10, help="采集微博数量上限")
    parser.add_argument("--visible", action="store_true", help="显示浏览器窗口（默认无头模式）")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径")
    parser.add_argument("--comments", action="store_true", help="同时采集评论内容")
    parser.add_argument("--max-comments", type=int, default=10, help="每条微博最多采集评论数（默认 10）")
    parser.add_argument(
        "--url",
        default=DEFAULT_PROFILE_URL,
        help="用户主页 URL（默认：元气森林官方微博）",
    )

    args = parser.parse_args()

    result = asyncio.run(scrape_profile(
        profile_url=args.url,
        limit=args.limit,
        headless=not args.visible,
        fetch_comments=args.comments,
        max_comments=args.max_comments,
    ))

    output = result.model_dump(mode="json")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"结果已保存到: {args.output}")
    else:
        import tempfile
        tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False)
        json.dump(output, tmp, ensure_ascii=False, indent=2)
        tmp.close()
        with open(tmp.name, "r", encoding="utf-8") as f:
            sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace")
            print(f.read())
        os.unlink(tmp.name)


if __name__ == "__main__":
    main()
