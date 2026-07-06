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
import re
import sys

from pydantic import BaseModel, Field
from playwright.async_api import async_playwright

from common import CommentItem, launch_browser, get_edge_user_data, write_output, random_delay, normalize_time, wait_for_login, xhs_search_by_input
from datetime import datetime as _dt


class NoteEngagement(BaseModel):
    """单条笔记的运营数据结构"""
    title: str = Field(description="笔记标题")
    content: str = Field(default="", description="笔记正文")
    likes: int = Field(description="点赞数")
    collects: int = Field(description="收藏数")
    comments: int = Field(description="评论数")
    published_at: str = Field(default="", description="发布时间（如 2小时前、06-28）")
    comments_list: list[CommentItem] = Field(default_factory=list, description="评论列表")
    url: str = Field(description="笔记链接")


class ProfileResult(BaseModel):
    """账号内容汇总"""
    author: str = Field(description="账号名称")
    total_collected: int = Field(description="实际采集到的笔记数量")
    notes: list[NoteEngagement] = Field(description="笔记运营数据列表")


def _parse_pubtime(t: str) -> str:
    """将发布时间转为可排序的 YYYY-MM-DD，无法解析的返回空。"""
    if not t:
        return ""
    t = normalize_time(t)
    n = _dt.now()
    if "小时" in t or "分钟" in t:
        return n.strftime("%Y-%m-%d")
    if "昨天" in t:
        return (n - timedelta(days=1)).strftime("%Y-%m-%d")
    m = __import__("re").match(r"^(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return m.group(0)
    return t


DEFAULT_PROFILE_URL = (
    "https://www.xiaohongshu.com/user/profile/5d499e66000000001000ce18"
)


async def scrape_profile(
    profile_url: str = DEFAULT_PROFILE_URL,
    limit: int = 10,
    headless: bool = True,
    fetch_comments: bool = True,
    max_comments: int = 10,
    no_content: bool = False,
) -> ProfileResult:
    """模拟真实用户操作：进 explore → 搜索用户 ID → 点用户卡片 → 进入主页 → 点笔记详情 → 后退"""
    notes = []
    author_name = ""
    edge_user_data = get_edge_user_data()
    user_id = profile_url.rstrip('/').split('/')[-1].split('?')[0]

    async with async_playwright() as p:
        context, page, _tmpdir = await launch_browser(p, headless=False, user_data_dir=edge_user_data, label="xiaohongshu")

        try:
            # ── 步骤 1：打开 explore ──────────────────────
            print(f"步骤1: 打开小红书首页", file=sys.stderr)
            await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1500)

            # 检测登录
            if "login" in page.url or "passport" in page.url:
                if headless:
                    print("\n⚠️ 检测到未登录状态，将打开浏览器窗口供您登录...", file=sys.stderr)
                    await context.close()
                    context, page, _tmpdir = await launch_browser(p, headless=False, user_data_dir=edge_user_data, label="xiaohongshu")
                    await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(2000)
                    await wait_for_login(page)
                else:
                    print("\n⚠️ 检测到未登录，请在浏览器窗口中完成登录", file=sys.stderr)
                    await wait_for_login(page)

            # ── 步骤 2：模拟点击搜索框输入用户 ID ──
            print(f"步骤2: 搜索用户 {user_id}", file=sys.stderr)
            ok = await xhs_search_by_input(page, user_id, "搜索用户")
            if not ok:
                print(f"  ⚠️ 搜索框输入失败，尝试回退直接URL", file=sys.stderr)
                search_url = f"https://www.xiaohongshu.com/search_result?keyword={user_id}&source=web_search_result_notes"
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)

            # ── 步骤 3：在搜索结果中找到对应的用户卡片 → 进入主页 ──
            print(f"步骤3: 在搜索结果中点击用户卡片", file=sys.stderr)
            found_user = False
            try:
                user_href = await page.evaluate("""
                    (targetId) => {
                        // 优先匹配 href 中包含用户 ID 的链接
                        var links = document.querySelectorAll('a[href*="/user/profile/"]');
                        for (var link of links) {
                            var href = link.getAttribute('href') || '';
                            if (href.indexOf(targetId) >= 0) {
                                return href.startsWith('http') ? href : 'https://www.xiaohongshu.com' + href;
                            }
                        }
                        // 回退：取文本中包含品牌名/ID 的用户链接
                        for (var link of links) {
                            var t = (link.textContent || '').trim();
                            if (t.length > 0 && t.indexOf('我') !== 0 && t.indexOf(targetId) >= 0) {
                                var href = link.getAttribute('href') || '';
                                return href.startsWith('http') ? href : 'https://www.xiaohongshu.com' + href;
                            }
                        }
                        // 再回退：取第一个非"我"、非空的用户链接
                        for (var link of links) {
                            var t = (link.textContent || '').trim();
                            if (t && t !== '我' && t.length > 2) {
                                var href = link.getAttribute('href') || '';
                                return href.startsWith('http') ? href : 'https://www.xiaohongshu.com' + href;
                            }
                        }
                        return null;
                    }
                """, user_id)

                if user_href:
                    print(f"  进入用户主页", file=sys.stderr)
                    # 去掉 xsec_token 参数避免过期
                    profile_url = user_href.split('?')[0]
                    await page.evaluate(f"window.location.href = '{profile_url}'")
                    try:
                        await page.wait_for_url("**/user/profile/**", timeout=15000)
                        await page.wait_for_timeout(2000)
                    except Exception:
                        print(f"  导航超时，当前URL: {page.url}", file=sys.stderr)

                    if "user/profile" not in page.url:
                        print(f"  ✗ 无法进入用户主页 {user_id}", file=sys.stderr)
                        raise RuntimeError(f"无法进入用户主页 {user_id}")
                    found_user = True
                else:
                    print(f"  未找到用户卡片", file=sys.stderr)
            except Exception as e:
                print(f"  用户卡片点击失败: {e}", file=sys.stderr)

            if not found_user:
                print(f"  ✗ 无法进入用户主页 {user_id}", file=sys.stderr)
                raise RuntimeError(f"无法进入用户主页 {user_id}")

            await page.wait_for_timeout(2000)

            # ── 获取账号名称 ─────────────────────────────
            await page.wait_for_timeout(2000)
            author_name = await page.evaluate("""
                () => {
                    const selectors = [
                        '[class*="username"]', '[class*="userName"]', '[class*="nickname"]',
                        '[class*="name"]', '[class*="user-name"]',
                        'h1', '.user-info .name', '.profile .name',
                        '.user-profile .name', '#userName', '[class*="userNameText"]'
                    ];
                    for (var sel of selectors) {
                        var el = document.querySelector(sel);
                        if (el) {
                            var t = el.textContent.trim();
                            if (t && t.length > 0 && t.length < 20) return t;
                        }
                    }
                    return '';
                }
            """)
            if not author_name:
                # 从页面标题取
                author_name = await page.title()
                author_name = author_name.replace(' - 小红书', '').strip()
            else:
                import re as _re
                author_name = _re.split(r'[0-9]|小时|天前|更新|粉丝|笔记|关注|小红书号', author_name)[0].strip()
            print(f"账号名称: {author_name or '（未识别）'}", file=sys.stderr)

            # ── 步骤 4：等待初始卡片加载，取最新非置顶 ──
            # 小红书主页严格按时间倒序排列，第一个非置顶就是最新的
            # 不滚动！滚动会导致虚拟滚动移出顶部最新笔记
            for i in range(30):
                current_count = await page.evaluate(
                    "document.querySelectorAll('section.note-item').length"
                )
                # 至少等 limit+3 张卡片加载，确保有足够非置顶
                if current_count >= limit + 3:
                    print(f"已加载 {current_count} 条笔记", file=sys.stderr)
                    break
                await asyncio.sleep(0.5)

            await page.wait_for_timeout(1000)

            # ── 提取 DOM 中卡片，按页面顺序取非置顶 ──
            card_data = await page.evaluate("""
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
                    const isPinned = (card.textContent || '').indexOf('置顶') >= 0;

                    let pubTime = '';
                    const footerEl = card.querySelector('.footer, [class*="footer"], [class*="date"], [class*="time"]');
                    if (footerEl) {
                        const ft = footerEl.textContent.trim();
                        const timeMatch = ft.match(/(\\d+[小时天日前分钟秒]|\\d{4}[-/]\\d{1,2}[-/]\\d{1,2}|\\d{1,2}[-/]\\d{1,2})/);
                        if (timeMatch) pubTime = timeMatch[0];
                    }

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
                            if (t.length > 4 && t.length < 100
                                && !span.closest('a[href*="/user/"]')
                                && !span.closest('[class*="count"], [class*="like"], [class*="num"]')) {
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
                            const found = (clone.textContent || '').match(/\\d+/g);
                            if (found) {
                                for (const n of found) nums.push(parseInt(n, 10));
                            }
                        }
                    }

                    results.push({
                        title, url, pinned: isPinned, pubTime,
                        likes: nums.length > 0 ? nums[0] : -1,
                        collects: nums.length > 1 ? nums[1] : -1,
                        comments: nums.length > 2 ? nums[2] : -1,
                    });
                }
                return results;
            }
            """)

            # 取非置顶的前 limit 条（页面已是时间倒序）
            unpinned = [c for c in card_data if not c.get("pinned")][:limit]

            if len(card_data) > len(unpinned):
                print(f"跳过 {len(card_data) - len(unpinned)} 条置顶笔记", file=sys.stderr)
            print(f"共采集 {len(unpinned)} 条笔记", file=sys.stderr)
            for idx, c in enumerate(unpinned):
                print(f"  [{idx+1}] {c.get('title','')[:30]}... [{c.get('pubTime','')}]", file=sys.stderr)

            # ── 转笔记详情页 ─────────────────────────────
            seen_urls = set()
            for idx, item in enumerate(unpinned):
                if notes and idx < len(unpinned):
                    await random_delay(1, 3, "笔记详情页间隔")
                url = item.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                title = (item.get("title", "") or "")[:120]
                likes = item.get("likes", -1)
                collects = item.get("collects", -1)

                # ── 步骤 5：导航到详情页 ──
                note_url = item.get("url", "")
                # 移除可能带 profile 路径的 URL，转成标准 explore 页
                if "/user/profile/" in note_url:
                    note_id_match = re.search(r'/([a-f0-9]{24})', note_url)
                    if note_id_match:
                        note_id = note_id_match.group(1)
                        note_url = f"https://www.xiaohongshu.com/explore/{note_id}"

                try:
                    await page.goto(note_url, wait_until="domcontentloaded", timeout=30000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(1500)

                    # ── 提取详情页数据 ────────────────────
                    detail_data = await page.evaluate("""
                    () => {
                        var result = { likes: -1, collects: -1, comments: -1, note_text: '', published_at: '' };

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
                        if (result.likes < 0 || result.collects < 0 || result.comments < 0) {
                            var all = document.body.innerText || '';
                            var m;
                            if (result.likes < 0) { m = all.match(/赞[\\s\\S]{0,3}([\\d,]*)/); if (m) result.likes = parseCount(m[1]); }
                            if (result.collects < 0) { m = all.match(/收藏[\\s\\S]{0,3}([\\d,]*)/); if (m) result.collects = parseCount(m[1]); }
                            if (result.comments < 0) { m = all.match(/评论[\\s\\S]{0,3}([\\d,]*)/); if (m) result.comments = parseCount(m[1]); }
                        }

                        // 提取发布时间
                        var dateEl = document.querySelector('time, [datetime], [class*="date"], [class*="time"]');
                        if (dateEl) {
                            result.published_at = dateEl.getAttribute('datetime') || dateEl.textContent.trim();
                        }
                        if (!result.published_at) {
                            var all = document.body.innerText || '';
                            var dm = all.match(/(\\d{4}年\\d{1,2}月\\d{1,2}日)/);
                            if (dm) result.published_at = dm[1];
                        }

                        var candidates = document.querySelectorAll(
                            '.note-text, [class*="content"] [class*="text"], [class*="desc"]'
                        );
                        var best = '';
                        for (var el of candidates) {
                            var t = (el.textContent || '').trim();
                            if (t.length > best.length) best = t;
                        }
                        result.note_text = best;

                        return result;
                    }
                    """)

                    # ── 提取评论（热门前 3-10 条）──────────
                    comments_list = []
                    if fetch_comments:
                        await page.wait_for_timeout(1000)
                        comments_list = await page.evaluate("""
                        (maxComments) => {
                            var items = document.querySelectorAll('.comments-container .parent-comment');
                            var result = [];
                            var max = Math.min(items.length, maxComments);
                            for (var i = 0; i < max; i++) {
                                var c = items[i];

                                var nameEl = c.querySelector('.author .name');
                                var userName = nameEl ? nameEl.textContent.trim() : '';

                                var noteText = c.querySelector('.content .note-text');
                                var content = noteText ? noteText.textContent.trim() : '';

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

                    print(f"  详情页: 赞={detail_data.get('likes',-1)} 收={detail_data.get('collects',-1)} 评={detail_data.get('comments',-1)} 评论{len(comments_list)}条", file=sys.stderr)

                    note = NoteEngagement(
                        title=title,
                        content=detail_data.get("note_text", "") if not no_content else "",
                        likes=detail_data.get("likes", -1) if detail_data.get("likes", -1) > 0 else likes,
                        collects=detail_data.get("collects", -1) if detail_data.get("collects", -1) > 0 else collects,
                        comments=detail_data.get("comments", -1),
                        published_at=normalize_time(detail_data.get("published_at", "") or ""),
                        comments_list=comments_list,
                        url=url,
                    )
                    if idx < len(unpinned) - 1:
                        back_ok = False
                        for _ in range(3):
                            try:
                                await page.go_back(wait_until="domcontentloaded", timeout=15000)
                                await page.wait_for_timeout(1500)
                                if "user/profile" in page.url:
                                    back_ok = True
                                    break
                            except Exception:
                                continue
                        if not back_ok:
                            print(f"  返回主页失败，尝试直接导航", file=sys.stderr)
                            try:
                                await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
                                await page.wait_for_timeout(1500)
                            except Exception as e:
                                print(f"  导航回主页失败: {e}", file=sys.stderr)

                except Exception as e:
                    print(f"  详情页处理异常: {e}", file=sys.stderr)
                    note = NoteEngagement(
                        title=title, likes=likes,
                        collects=collects, comments=-1, url=url,
                        published_at=normalize_time(item.get("pubTime", "") or ""),
                    )

                notes.append(note)
                ls = f"{note.likes}" if note.likes >= 0 else "?"
                cs = f"{note.collects}" if note.collects >= 0 else "?"
                cm = f"{note.comments}" if note.comments >= 0 else "?"
                cc = f"({len(note.comments_list)}条评论)" if note.comments_list else ""
                label = f"  [{len(notes)}] {'📌' if item.get('pinned') else ''} {title[:24]}... 赞={ls} 收={cs} 评={cm}{cc}"
                print(label, file=sys.stderr)

        finally:
            await context.close()

    # 笔记已在页面按发布时间从新到旧排列，保持原始顺序
    # notes.sort(key=lambda n: n.published_at, reverse=True)

    return ProfileResult(
        author=author_name or "",
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
    parser.add_argument("--no-content", action="store_true", help="不获取笔记正文（默认获取）")
    parser.add_argument("--no-comments", action="store_true", help="不获取评论（默认获取）")
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
        fetch_comments=not args.no_comments,
        max_comments=args.max_comments,
        no_content=args.no_content,
    ))

    output = result.model_dump(mode="json")

    write_output(output, args.output)


if __name__ == "__main__":
    main()
