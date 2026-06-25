"""
小红书账号内容运营数据采集脚本
使用 Playwright + Edge 浏览器，抓取指定账号发布的笔记数据

用法：
    python xiaohongshu_scraper.py
    python xiaohongshu_scraper.py --limit 10
    python xiaohongshu_scraper.py --limit 1 --comments --output result.json
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


class NoteEngagement(BaseModel):
    """单条笔记的运营数据结构"""
    title: str = Field(description="笔记标题")
    likes: int = Field(description="点赞数")
    collects: int = Field(description="收藏数")
    comments: int = Field(description="评论数")
    comments_list: list[CommentItem] = Field(default_factory=list, description="评论列表")
    url: str = Field(description="笔记链接")


class ProfileResult(BaseModel):
    """账号内容汇总"""
    author: str = Field(description="账号名称")
    total_collected: int = Field(description="实际采集到的笔记数量")
    notes: list[NoteEngagement] = Field(description="笔记运营数据列表")


# 元气森林官方小红书主页
DEFAULT_PROFILE_URL = (
    "https://www.xiaohongshu.com/user/profile/5d499e66000000001000ce18"
    "?xsec_token=ABRadU0ZG1pzbLsWlbRDRXY4XBynvVmA-VO_flHYFTkz8%3D"
    "&xsec_source=pc_search"
)


async def scrape_profile(
    profile_url: str = DEFAULT_PROFILE_URL,
    limit: int = 10,
    headless: bool = True,
    fetch_comments: bool = False,
    max_comments: int = 10,
) -> ProfileResult:
    """打开小红书账号主页，采集该账号发布的笔记数据。"""
    notes = []
    author_name = ""
    edge_user_data = os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data"
    )

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=edge_user_data,
            channel="msedge",
            headless=headless,
            args=["--disable-sync"],
            viewport={"width": 1920, "height": 1080},
        )

        page = await context.new_page()

        try:
            print(f"正在打开用户主页: {profile_url}", file=sys.stderr)
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(5000)

            # 检测是否已登录：检查页面是否被重定向到登录页或无法展示内容
            current_url = page.url
            login_detected = (
                "login" in current_url
                or "passport" in current_url
                or await page.evaluate(
                    "() => document.querySelector('[class*=\"login\"], [class*=\"passport\"]') !== null"
                )
            )

            if login_detected and headless:
                print("\n⚠️ 检测到未登录状态，将打开浏览器窗口供您登录...", file=sys.stderr)
                print("请在浏览器窗口中完成登录后，等待脚本自动继续\n", file=sys.stderr)
                await context.close()
                # 重新以非 headless 模式启动
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=edge_user_data,
                    channel="msedge",
                    headless=False,
                    args=["--disable-sync"],
                    viewport={"width": 1920, "height": 1080},
                )
                page = await context.new_page()
                await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(8000)

            # 获取账号名称
            author_name = await page.evaluate("""
                () => {
                    const el = document.querySelector('[class*="username"], [class*="userName"], [class*="nickname"], h1, h2');
                    return el ? el.textContent.trim() : '';
                }
            """)
            print(f"账号名称: {author_name or '（未识别）'}", file=sys.stderr)

            # 动态滚动加载，直到卡片数 >= limit + 10（预留置顶干扰空间）
            max_scroll = 50
            last_count = 0
            stale_rounds = 0
            scroll_target = limit + 10
            for i in range(max_scroll):
                await page.evaluate("window.scrollBy(0, 1200)")
                await page.wait_for_timeout(1500)
                current_count = await page.evaluate(
                    "document.querySelectorAll('section.note-item').length"
                )
                if current_count >= scroll_target:
                    print(f"已加载 {current_count} 条笔记，满足需求", file=sys.stderr)
                    break
                if current_count == last_count:
                    stale_rounds += 1
                    if stale_rounds >= 3:
                        print(f"滚动 {i+1} 次后无更多笔记加载（共 {current_count} 条）", file=sys.stderr)
                        break
                else:
                    stale_rounds = 0
                    last_count = current_count
                print(f"  滚动加载中... {current_count} 条", file=sys.stderr)

            await page.wait_for_timeout(2000)

            # 从账号主页提取笔记卡片数据
            extract_script = """
            () => {
                function parseCount(s) {
                    s = s.replace(',', '');
                    if (s.includes('万')) return Math.round(parseFloat(s) * 10000);
                    const n = parseInt(s, 10);
                    return isNaN(n) ? -1 : n;
                }

                const cards = document.querySelectorAll('section.note-item');
                const results = [];
                for (const card of cards) {
                    const coverLink = card.querySelector('a.cover');
                    if (!coverLink) continue;
                    const href = coverLink.getAttribute('href') || '';
                    const url = href.startsWith('http') ? href : 'https://www.xiaohongshu.com' + href;

                    // 检查是否为置顶笔记
                    const isPinned = (card.textContent || '').indexOf('置顶') >= 0;

                    const titleEl = card.querySelector('.title span, .footer .title');
                    let title = '';
                    if (titleEl) {
                        const t = (titleEl.textContent || '').trim();
                        if (t.length > 2) title = t;
                    }
                    if (!title) {
                        const spans = card.querySelectorAll('span');
                        for (const span of spans) {
                            const t = (span.textContent || '').trim();
                            if (t.length > 4 && t.length < 100 && !span.closest('a[href*="/user/"]') && !span.closest('[class*="count"], [class*="like"], [class*="num"]')) {
                                if (t.length > title.length) title = t;
                            }
                        }
                    }

                    const nums = [];
                    const likeEl = card.querySelector('.like-wrapper .count');
                    if (likeEl) {
                        const n = parseCount((likeEl.textContent || '').trim());
                        if (n >= 0) nums.push(n);
                    }

                    if (nums.length === 0) {
                        const bottom = card.querySelector('.card-bottom-wrapper');
                        if (bottom) {
                            const clone = bottom.cloneNode(true);
                            const authorA = clone.querySelector('a[href*="/user/"]');
                            if (authorA) authorA.remove();
                            const text = clone.textContent || '';
                            const found = text.match(/\\d+/g);
                            if (found) {
                                for (const n of found) nums.push(parseInt(n, 10));
                            }
                        }
                    }

                    results.push({
                        title: title,
                        likes: nums.length > 0 ? nums[0] : -1,
                        collects: nums.length > 1 ? nums[1] : -1,
                        comments: nums.length > 2 ? nums[2] : -1,
                        url: url,
                        pinned: isPinned,
                    });
                }
                return results;
            }
            """

            card_data = await page.evaluate(extract_script)
            # 过滤掉置顶笔记，取最新的 limit 条
            pinned_count = sum(1 for c in card_data if c.get("pinned"))
            card_data = [c for c in card_data if not c.get("pinned")][:limit]
            if pinned_count:
                print(f"跳过 {pinned_count} 条置顶，取前 {len(card_data)} 条最新笔记", file=sys.stderr)
            else:
                print(f"取前 {len(card_data)} 条最新笔记", file=sys.stderr)

            seen_urls = set()
            for item in card_data:
                if len(notes) >= limit:
                    break
                url = item.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                title = (item.get("title", "") or "")[:120]
                likes = item.get("likes", -1)
                collects = item.get("collects", -1)

                # 用点击 cover 链接的方式进入详情页（保留 xsec_token）
                try:
                    clicked = await page.evaluate("""
                    (targetUrl) => {
                        var cards = document.querySelectorAll('section.note-item');
                        for (var c of cards) {
                            var cover = c.querySelector('a.cover');
                            if (!cover) continue;
                            var href = cover.getAttribute('href') || '';
                            var fullUrl = href.startsWith('http') ? href : 'https://www.xiaohongshu.com' + href;
                            if (fullUrl === targetUrl || href === targetUrl.replace('https://www.xiaohongshu.com', '')) {
                                var evt = new MouseEvent('click', { bubbles: true, cancelable: true, view: window });
                                cover.dispatchEvent(evt);
                                return true;
                            }
                        }
                        return false;
                    }
                    """, url)

                    if not clicked:
                        print(f"  未找到可点击的卡片: {url}", file=sys.stderr)
                        continue

                    # 等待页面导航完成
                    try:
                        await page.wait_for_url("**/explore/**", timeout=10000)
                        await page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        print(f"  页面导航超时，当前 URL: {page.url}", file=sys.stderr)
                    await page.wait_for_timeout(3000)

                    # 从详情页提取互动数据
                    detail_data = await page.evaluate("""
                    () => {
                        var result = { likes: -1, collects: -1, comments: -1 };

                        function parseCount(s) {
                            if (!s) return -1;
                            s = s.replace(',', '');
                            if (s.includes('万')) return Math.round(parseFloat(s) * 10000);
                            var n = parseInt(s, 10);
                            return isNaN(n) ? -1 : n;
                        }

                        var container = document.querySelector('.interact-container');
                        if (container) {
                            var likeEl = container.querySelector('.like-wrapper .count');
                            if (likeEl) result.likes = parseCount(likeEl.textContent.trim());

                            var collectEl = container.querySelector('.collect-wrapper .count');
                            if (collectEl) result.collects = parseCount(collectEl.textContent.trim());

                            var chatEl = container.querySelector('.chat-wrapper .count');
                            if (chatEl) result.comments = parseCount(chatEl.textContent.trim());
                        }

                        return result;
                    }
                    """)

                    # 提取评论内容
                    comments_list = []
                    if fetch_comments:
                        await page.wait_for_timeout(2000)
                        comments_list = await page.evaluate("""
                        (maxComments) => {
                            var items = document.querySelectorAll('.comments-container .parent-comment');
                            var result = [];
                            var max = Math.min(items.length, maxComments);
                            for (var i = 0; i < max; i++) {
                                var c = items[i];

                                // 用户名
                                var nameEl = c.querySelector('.author .name');
                                var userName = nameEl ? nameEl.textContent.trim() : '';

                                // 评论内容
                                var noteText = c.querySelector('.content .note-text');
                                var content = noteText ? noteText.textContent.trim() : '';

                                // 评论点赞
                                var likeNum = c.querySelector('.like-wrapper .count');
                                var likeText = likeNum ? likeNum.textContent.trim() : '';
                                var likes = 0;
                                if (likeText && likeText !== '赞') {
                                    likes = parseInt(likeText, 10) || 0;
                                }

                                if (userName && content) {
                                    result.push({ user: userName, content: content, likes: likes });
                                }
                            }
                            return result;
                        }
                        """, max_comments)

                    print(f"  详情页: 赞={detail_data.get('likes',-1)} 收={detail_data.get('collects',-1)} 评={detail_data.get('comments',-1)}", file=sys.stderr)

                    note = NoteEngagement(
                        title=title,
                        likes=detail_data.get("likes", -1) if detail_data.get("likes", -1) > 0 else likes,
                        collects=detail_data.get("collects", -1) if detail_data.get("collects", -1) > 0 else collects,
                        comments=detail_data.get("comments", -1),
                        comments_list=comments_list,
                        url=url,
                    )

                    # 返回账号主页
                    back_ok = False
                    for _ in range(3):
                        try:
                            await page.go_back(wait_until="domcontentloaded", timeout=15000)
                            await page.wait_for_timeout(3000)
                            if "user/profile" in page.url:
                                back_ok = True
                                break
                        except Exception:
                            continue
                    if not back_ok:
                        print(f"  返回主页失败，当前 URL: {page.url}，尝试直接导航", file=sys.stderr)
                        try:
                            await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
                            await page.wait_for_timeout(3000)
                        except Exception as e:
                            print(f"  导航回主页失败: {e}", file=sys.stderr)

                except Exception as e:
                    print(f"  详情页处理异常: {e}", file=sys.stderr)
                    note = NoteEngagement(
                        title=title, likes=likes,
                        collects=collects, comments=-1, url=url,
                    )

                notes.append(note)
                ls = f"{note.likes}" if note.likes >= 0 else "?"
                cs = f"{note.collects}" if note.collects >= 0 else "?"
                cm = f"{note.comments}" if note.comments >= 0 else "?"
                cc = f"({len(note.comments_list)}条评论)" if note.comments_list else ""
                print(f"  [{len(notes)}] {title[:24]}... 赞={ls} 收={cs} 评={cm}{cc}", file=sys.stderr)

        finally:
            await context.close()

    return ProfileResult(
        author=author_name or "元气森林",
        total_collected=len(notes),
        notes=notes,
    )


def main():
    parser = argparse.ArgumentParser(
        description="小红书账号内容运营数据采集工具"
    )
    parser.add_argument("--limit", "-n", type=int, default=10, help="采集笔记数量上限")
    parser.add_argument("--visible", action="store_true", help="显示浏览器窗口（默认无头模式）")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径")
    parser.add_argument("--comments", action="store_true", help="同时采集评论内容")
    parser.add_argument("--max-comments", type=int, default=10, help="每条笔记最多采集评论数（默认 10）")
    parser.add_argument(
        "--url",
        default=DEFAULT_PROFILE_URL,
        help="用户主页 URL（默认：元气森林官方账号）",
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
