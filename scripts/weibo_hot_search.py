"""
微博热搜监控脚本
使用 Playwright + Edge 浏览器，采集微博热搜榜及各话题下的热门微博和评论

用法：
    python weibo_hot_search.py
    python weibo_hot_search.py --limit 5
    python weibo_hot_search.py --limit 10 --top-comments 5 --output result.json
"""

import argparse
import asyncio
import json
import os
import re
import sys

from pydantic import BaseModel, Field
from playwright.async_api import async_playwright


class CommentItem(BaseModel):
    """单条评论"""
    user: str = Field(description="评论用户")
    content: str = Field(description="评论内容")
    likes: int = Field(description="评论点赞数")


class TopicPost(BaseModel):
    """热搜话题下的一条热门微博"""
    text: str = Field(description="微博正文")
    reposts: int = Field(description="转发数")
    comments: int = Field(description="评论数")
    likes: int = Field(description="点赞数")
    url: str = Field(default="", description="微博链接")
    comments_list: list[CommentItem] = Field(default_factory=list, description="热门评论")


class TopicDetail(BaseModel):
    """热搜话题详情"""
    rank: int = Field(description="排名")
    title: str = Field(description="热搜词")
    hot_value: str = Field(description="热度标识（热/爆/沸/新/荐等）")
    topic_url: str = Field(description="话题搜索链接")
    posts: list[TopicPost] = Field(description="该话题下的热门微博（含评论）")


HOT_SEARCH_URL = "https://weibo.com/hot/search"


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
            headless=False,
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


async def scrape_hot_search(
    limit: int = 10,
    top_posts: int = 3,
    top_comments: int = 5,
    headless: bool = True,
) -> list[TopicDetail]:
    """采集微博热搜榜及各话题下的热门微博和评论。"""
    results = []
    edge_user_data = os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data"
    )

    async with async_playwright() as p:
        context, page = await _launch_browser(p, headless=headless, user_data_dir=edge_user_data)

        try:
            # 第一阶段：获取热搜榜单
            print(f"正在打开热搜榜: {HOT_SEARCH_URL}", file=sys.stderr)
            await page.goto(HOT_SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(6000)

            # 检测是否登录
            current_url = page.url
            login_detected = (
                "login" in current_url or "passport" in current_url
                or "微博" not in await page.title()
            )
            if login_detected and headless:
                print("\n⚠️ 检测到未登录状态，将打开浏览器窗口供您登录...", file=sys.stderr)
                await context.close()
                context, page = await _launch_browser(
                    p, headless=False, user_data_dir=edge_user_data
                )
                await page.goto(HOT_SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(10000)

            # 提取热搜列表
            hot_list = await page.evaluate("""
                () => {
                    var items = document.querySelectorAll('[class*=_titout_]');
                    var results = [];

                    for (var i = 0; i < items.length; i++) {
                        var el = items[i];
                        var txt = (el.textContent || '').trim();
                        if (!txt) continue;

                        // 跳过广告
                        if (txt.indexOf('荐') >= 0 && txt.length < 20) continue;
                        if (ad(txt)) continue;

                        // 从独立的 rank 元素取排名（[class*=_rankimg_]）
                        var rankEl = el.querySelector('[class*=_rankimg_]');
                        var rankText = rankEl ? rankEl.textContent.trim() : '';
                        var rank = parseInt(rankText, 10);
                        if (isNaN(rank) || rank < 1 || rank > 100) {
                            // 备选：从文本开头提取数字
                            var m = txt.match(/^(\\d+)/);
                            if (!m) continue;
                            rank = parseInt(m[1], 10);
                            if (rank < 1 || rank > 100) continue;
                        }

                        // 提取标题：去掉排名数字前缀（用已知的 rank 精确截取）
                        var title = rankText ? txt.substring(rankText.length).trim() : txt.replace(/^\\d+/, '').trim();

                        // 提取热度标识（标题末尾的热/爆/沸/新/荐）
                        var hotBadge = '';
                        var badgeMatch = title.match(/[热爆沸新荐]$/);
                        if (badgeMatch) {
                            hotBadge = badgeMatch[0];
                            title = title.slice(0, -1).trim();
                        }

                        // 去掉标题末尾的纯数字串（热度数值）
                        title = title.replace(/\\d+$/, '').trim();

                        // 查找话题链接
                        var link = '';
                        var linkEl = el.querySelector('a[href*="weibo.com"], a[href*="s.weibo"]');
                        if (linkEl) {
                            link = linkEl.getAttribute('href') || '';
                            if (link && !link.startsWith('http')) link = 'https:' + link;
                        }

                        results.push({
                            rank: rank,
                            title: title,
                            hot: hotBadge,
                            url: link
                        });
                    }

                    function ad(t) {
                        return t.indexOf('广告') >= 0 || t.indexOf('推广') >= 0 || t.indexOf('官宣') >= 0
                            || t.indexOf('宝藏') >= 0 || t.indexOf('安利') >= 0 || t.indexOf('好玩的都在') >= 0
                            || t.indexOf('上美团') >= 0 || t.indexOf('解锁') >= 0 || t.indexOf('隐藏配方') >= 0
                            || t.indexOf('移动智能') >= 0 || t.indexOf('无界普惠') >= 0;
                    }

                    return results;
                }
            """)

            # 校验：排序并过滤掉重复/序号异常的
            hot_list.sort(key=lambda x: x.get("rank", 0))
            # 检查序号是否连续，剔除明显异常的（如标题以数字开头的误识别）
            filtered = []
            for item in hot_list:
                r = item.get("rank", 0)
                if filtered and r == filtered[-1].get("rank", 0):
                    continue  # 重复排名跳过
                if filtered and r < filtered[-1].get("rank", 0):
                    continue  # 序号回退跳过
                filtered.append(item)

            show_list = filtered[:limit]
            if not show_list:
                print("  未解析到热搜数据，请检查页面结构", file=sys.stderr)
                return []
            print(f"获取到 {len(show_list)} 条热搜（取前 {limit} 条）", file=sys.stderr)
            for item in show_list:
                print(f"  [#{item['rank']}] {item['title']} [{item['hot']}]", file=sys.stderr)

            # 第二阶段：进入每个热搜话题页面，提取热门微博和评论
            print(f"\n开始提取前 {limit} 条热搜的热门微博...", file=sys.stderr)
            for idx, item in enumerate(show_list):
                try:
                    topic = await _fetch_topic_detail(
                        page, item, top_posts, top_comments
                    )
                    if topic:
                        results.append(topic)
                    pc = len(topic.posts) if topic else 0
                    cc = sum(len(p.comments_list) for p in topic.posts) if topic else 0
                    if top_comments > 0:
                        print(f"  [{idx+1}/{limit}] #{item['rank']} {item['title']}: {pc} 条微博, {cc} 条评论", file=sys.stderr)
                    else:
                        print(f"  [{idx+1}/{limit}] #{item['rank']} {item['title']}: {pc} 条微博", file=sys.stderr)
                except Exception as e:
                    print(f"  [{idx+1}/{limit}] #{item['rank']} {item['title']}: 获取失败 - {e}", file=sys.stderr)

        finally:
            await context.close()

    return results


async def _fetch_topic_detail(
    page, item: dict, top_posts: int, top_comments: int,
) -> TopicDetail | None:
    """进入热搜话题页，获取热门微博和评论。"""
    title = item.get("title", "")
    rank = item.get("rank", 0)
    hot = item.get("hot", "")
    topic_url = item.get("url", "")

    # 统一导向热门排序的搜索页
    if topic_url and "xsort=hot" not in topic_url:
        # 从链接提取关键词，构造热门排序 URL
        import re
        q_match = re.search(r'[?&]q=([^&]+)', topic_url)
        if q_match:
            topic_url = f"https://s.weibo.com/weibo?q={q_match.group(1)}&xsort=hot"
        else:
            topic_url = f"https://s.weibo.com/weibo?q={title}&xsort=hot"
    elif not topic_url:
        topic_url = f"https://s.weibo.com/weibo?q={title}&xsort=hot"

    await page.goto(topic_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(5000)

    await page.goto(topic_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(5000)

    # 滚动一下让更多微博加载
    for _ in range(3):
        await page.evaluate("window.scrollBy(0, 1200)")
        await page.wait_for_timeout(1000)

    # 提取话题下热门微博（s.weibo.com 搜索页 DOM）
    posts_data = await page.evaluate(f"""
        (maxPosts) => {{
            var wraps = document.querySelectorAll('.card-wrap');
            var r = [];
            for (var i = 0; i < wraps.length && i < maxPosts; i++) {{
                var w = wraps[i];

                // 跳过广告
                if ((w.textContent || '').indexOf('广告') >= 0) continue;

                // 正文（取 .content .txt 元素的纯文本，不含工具栏/用户信息）
                var feedText = '';
                var txtEl = w.querySelector('.card-feed .content .txt');
                if (txtEl) {{
                    feedText = (txtEl.textContent || '').trim();
                }} else {{
                    // 备选
                    var contentEl = w.querySelector('.card-feed .content');
                    feedText = contentEl ? (contentEl.textContent || '').trim() : '';
                }}
                if (!feedText || feedText.length < 10) continue;

                // 详情页链接：时间戳位置的 a 标签
                var detailUrl = '';
                var timeLink = w.querySelector('.from a');
                if (timeLink) {{
                    var href = timeLink.getAttribute('href') || '';
                    if (href && href.startsWith('//')) href = 'https:' + href;
                    if (href.indexOf('weibo.com') >= 0) detailUrl = href;
                }}

                // 互动数据
                var actEl = w.querySelector('.card-act');
                var actText = actEl ? (actEl.textContent || '').trim() : '';
                var reposts = -1, comments = -1, likes = -1;
                if (actText) {{
                    var parts = actText.split(/\\s+/);
                    var nums = [];
                    for (var p of parts) {{
                        var n = parseInt(p.replace(/,/g, ''), 10);
                        if (!isNaN(n)) nums.push(n);
                    }}
                    if (nums.length > 0) reposts = nums[0];
                    if (nums.length > 1) comments = nums[1];
                    if (nums.length > 2) likes = nums[2];
                }}

                r.push({{ text: feedText, reposts: reposts, comments: comments, likes: likes, url: detailUrl, comments_list: [] }});
            }}
            return r;
        }}
    """, top_posts)

    topic_posts = []
    for post_data in posts_data:
        post = TopicPost(
            text=post_data.get("text", ""),
            reposts=post_data.get("reposts", -1),
            comments=post_data.get("comments", -1),
            likes=post_data.get("likes", -1),
            url=post_data.get("url", ""),
        )

        # 进入详情页获取完整正文（搜索页会被截断）
        detail_url = post_data.get("url", "")
        if detail_url:
            try:
                await page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(4000)

                # 提取完整正文
                full_text = await page.evaluate("""
                    () => {
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
                if full_text:
                    post.text = full_text

                # 提取评论
                if top_comments > 0:
                    for _ in range(3):
                        await page.evaluate("window.scrollBy(0, 1000)")
                        await page.wait_for_timeout(1000)

                    comments = await _extract_comments(page, top_comments)
                    post.comments_list = comments
            except Exception:
                pass

        topic_posts.append(post)

    return TopicDetail(
        rank=rank,
        title=title,
        hot_value=hot,
        topic_url=topic_url,
        posts=topic_posts,
    )


async def _extract_comments(page, max_comments: int) -> list[CommentItem]:
    """从当前详情页提取评论。"""
    comments_list = await page.evaluate(f"""
        (maxC) => {{
            var text = document.body.innerText || '';
            var lines = text.split('\\n').filter(function(l){{return l.trim()}});

            var commentStart = -1;
            for (var i = 0; i < lines.length; i++) {{
                if (lines[i] === '评论') {{ commentStart = i + 1; break; }}
            }}
            if (commentStart < 0) return [];

            var idx = commentStart;
            while (idx < lines.length && (lines[idx] === '按热度' || lines[idx] === '按时间')) idx++;

            // 跳过原帖信息（用户名、:内容、时间地点、点赞数）
            idx += 4;

            var result = [];
            var pendingUser = '';
            var pendingContent = '';
            var inContent = false;
            for (var j = idx; j < lines.length; j++) {{
                var l = lines[j];
                if (l === '已加载全部评论' || l === '分享这条博文') break;
                if (result.length >= maxC) break;

                if (l.indexOf(':') === 0) {{
                    pendingContent = l.substring(1).trim();
                    inContent = true;
                }} else if (/^\\d{{1,2}}-\\d{{1,2}}-\\d{{1,2}}/.test(l) || l.indexOf('发布于') >= 0 || l.indexOf('来自') >= 0) {{
                    if (inContent) {{
                        result.push({{ user: pendingUser || '(未知)', content: pendingContent || '', likes: 0 }});
                        pendingUser = '';
                        pendingContent = '';
                        inContent = false;
                    }}
                }} else if (/^\\d+$/.test(l)) {{
                    // 点赞数字行 - 忽略
                }} else {{
                    if (inContent) {{
                        result.push({{ user: pendingUser || '(未知)', content: pendingContent || '', likes: 0 }});
                        pendingUser = '';
                        pendingContent = '';
                    }}
                    pendingUser = l;
                    pendingContent = '';
                    inContent = false;
                }}
            }}
            if (pendingUser && inContent) {{
                result.push({{ user: pendingUser, content: pendingContent || '', likes: 0 }});
            }}
            return result;
        }}
    """, max_comments)

    return [CommentItem(**c) for c in comments_list]


def main():
    parser = argparse.ArgumentParser(
        description="微博热搜监控工具 - 采集热搜榜单及热门微博评论"
    )
    parser.add_argument("--limit", type=int, default=10, help="采集热搜数量上限（默认 10）")
    parser.add_argument("--top-posts", type=int, default=3, help="每条热搜提取前几条微博（默认 3）")
    parser.add_argument("--top-comments", type=int, default=0, help="每条微博提取前几条评论（默认 0，跳过评论避免耗时）")
    parser.add_argument("--visible", action="store_true", help="显示浏览器窗口（默认无头模式）")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径")

    args = parser.parse_args()

    results = asyncio.run(scrape_hot_search(
        limit=args.limit,
        top_posts=args.top_posts,
        top_comments=args.top_comments,
        headless=not args.visible,
    ))

    from datetime import datetime
    output = {
        "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_topics": len(results),
        "topics": [r.model_dump(mode="json") for r in results],
    }

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
