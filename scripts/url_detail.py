"""
单条 URL 详情采集脚本
输入小红书/微博内容 URL，抓取正文、互动量、评论（含子回复）并输出 JSON，
供 GUI 调用后发送到 Agent 做总结。

用法：
    python url_detail.py --url https://www.xiaohongshu.com/explore/xxx --max-comments 30
    python url_detail.py --url https://weibo.com/xxx/yyy --max-comments 60 -o result.json
"""
import argparse
import asyncio
import json
import os
import re
import sys
from urllib.parse import quote

_scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from playwright.async_api import async_playwright
from common import (
    kill_edge, launch_browser, get_edge_user_data, write_output,
    random_delay, wait_for_login, detect_xhs_ui_version, xhs_search_by_input,
    flatten_comments, xhs_expand_comments,
)


def detect_platform(url: str) -> str:
    if "xiaohongshu.com" in url:
        return "xiaohongshu"
    if "weibo.com" in url:
        return "weibo"
    return "unknown"


async def scrape_url_detail(url: str, max_comments: int = 30, headless: bool = False, account: str | None = None) -> dict:
    """抓取单条 URL 的内容详情（正文、互动量、评论）。"""
    platform = detect_platform(url)

    async with async_playwright() as p:
        context, page, _tmpdir = await launch_browser(p, headless=headless, label="url_detail", account=account)

        try:
            if platform == "xiaohongshu":
                return await _scrape_xhs_url(page, context, url, max_comments)
            elif platform == "weibo":
                return await _scrape_weibo_url(page, context, url, max_comments)
            else:
                return {"error": f"不支持的平台: {url}", "url": url}
        finally:
            await context.close()


async def _scrape_xhs_url(page, context, url: str, max_comments: int) -> dict:
    print("  平台: 小红书", file=sys.stderr)

    # 提取 note_id
    note_id = url.rstrip('/').split('/')[-1].split('?')[0]

    # 直接 goto 详情页
    xsec_match = re.search(r'xsec_token=([^&]+)', url)
    if xsec_match:
        goto_url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_match.group(1)}&xsec_source=pc_search"
    else:
        goto_url = f"https://www.xiaohongshu.com/explore/{note_id}"

    print(f"  打开详情页: {goto_url[:60]}...", file=sys.stderr)
    await page.goto(goto_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(5000)
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass

    # 检测反爬并重试（最多 3 次）
    xsec_token = re.search(r'xsec_token=([^&]+)', url)
    for retry in range(3):
        adblock = await page.evaluate(
            "document.body.innerText.indexOf('广告屏蔽插件') >= 0 || document.body.innerText.indexOf('您的浏览器似乎开') >= 0"
        )
        if not adblock:
            break
        print(f"  详情页被反爬拦截，重试 ({retry+1}/3)...", file=sys.stderr)
        xsec = f"?xsec_token={xsec_token.group(1)}&xsec_source=pc_search" if xsec_token else ""
        await page.goto(f"https://www.xiaohongshu.com/explore/{note_id}{xsec}", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
    else:
        print("  ❌ 重试后仍被反爬拦截", file=sys.stderr)
        return {"error": "被反爬拦截", "url": url, "platform": "xiaohongshu"}

    # 提取正文和互动量
    detail_data = await page.evaluate("""
    () => {
        var result = { title: '', note_text: '', likes: -1, collects: -1, comments: -1, author: '' };

        function parseCount(s) {
            if (!s) return -1;
            s = s.replace(',', '');
            if (s.includes('万')) return Math.round(parseFloat(s) * 10000);
            var n = parseInt(s, 10);
            return isNaN(n) ? -1 : n;
        }

        // 标题
        var titleEl = document.querySelector('#detail-title, [class*=_title_], h1');
        if (titleEl) result.title = titleEl.textContent.trim();

        // 正文
        var candidates = document.querySelectorAll('.note-text, [class*="content"] [class*="text"], [class*="desc"]');
        var best = '';
        for (var el of candidates) {
            var t = (el.textContent || '').trim();
            if (t.length > best.length) best = t;
        }
        result.note_text = best;

        // 互动
        var container = document.querySelector('.interact-container');
        if (container) {
            var likeEl = container.querySelector('.like-wrapper .count');
            if (likeEl) result.likes = parseCount(likeEl.textContent.trim());
            var collectEl = container.querySelector('.collect-wrapper .count');
            if (collectEl) result.collects = parseCount(collectEl.textContent.trim());
            var chatEl = container.querySelector('.chat-wrapper .count');
            if (chatEl) result.comments = parseCount(chatEl.textContent.trim());
        }
        if (container && result.comments < 0 && (result.likes >= 0 || result.collects >= 0)) {
            result.comments = 0;
        }

        // 作者
        var authorEl = document.querySelector('.username, [class*=username], [class*=_name_]');
        if (authorEl) result.author = authorEl.textContent.trim();

        return result;
    }
    """)

    print(f"  正文: {len(detail_data.get('note_text',''))} 字", file=sys.stderr)
    print(f"  互动: 赞={detail_data.get('likes',-1)} 收={detail_data.get('collects',-1)} 评={detail_data.get('comments',-1)}", file=sys.stderr)

    # 提取评论（滚动加载 + 展开子回复，公用函数）
    comments_list = []
    comment_images = 0
    if max_comments > 0 and detail_data.get("comments", 0) > 0:
        try:
            comments_list, comment_images = await xhs_expand_comments(page, max_comments)
        except Exception as e:
            print(f"    评论提取异常: {e}", file=sys.stderr)

    print(f"  评论: {len(comments_list)} 条, 图片: {comment_images} 张", file=sys.stderr)

    return {
        "platform": "xiaohongshu",
        "url": url,
        "title": detail_data.get("title", ""),
        "text": detail_data.get("note_text", ""),
        "author": detail_data.get("author", ""),
        "likes": detail_data.get("likes", -1),
        "collects": detail_data.get("collects", -1),
        "comments": detail_data.get("comments", -1),
        "comments_text": flatten_comments(comments_list),
        "comment_images": comment_images,
    }


async def _scrape_weibo_url(page, context, url: str, max_comments: int) -> dict:
    print("  平台: 微博", file=sys.stderr)

    # 在新 tab 中打开详情页（保持主 tab 干净）
    detail_page = await context.new_page()
    try:
        # 去掉 URL 中的 #repost/#comment 等 hash 片段，确保进入正常详情页
        clean_url = url.split('#')[0]
        await detail_page.goto(clean_url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(3000)

        # 检测登录
        if "login" in detail_page.url or "passport" in detail_page.url:
            print("\n⚠️ 检测到未登录，请在浏览器窗口中完成登录", file=sys.stderr)
            await wait_for_login(detail_page)

        # 提取正文和互动量（使用 weibo_scraper 验证过的选择器）
        detail = await detail_page.evaluate("""
        () => {
            var r = { text: '', reposts: -1, comments: -1, likes: -1, author: '' };

            // 正文
            var candidates = document.querySelectorAll(
                '[class*=_ogText_], [class*=_text_], [class*=_wbtext_]'
            );
            var best = '';
            for (var el of candidates) {
                var t = (el.textContent || '').trim();
                if (t.length > best.length) best = t;
            }
            r.text = best;

            // 作者
            var ael = document.querySelector('[class*=name] span, [class*=nick] span, [class*=_name_]');
            if (ael) r.author = ael.textContent.trim();

            // 互动（用 weibo_scraper 已验证的 footer 选择器 + innerText 回退）
            var footer = document.querySelector('footer');
            if (footer) {
                var numEls = footer.querySelectorAll('[class*=_num_]');
                var nums = [];
                for (var j = 0; j < numEls.length; j++) {
                    var t = numEls[j].textContent.trim();
                    if (!t || t === '转发' || t === '评论' || t === '赞') continue;
                    var n = parseInt(t.replace(/,/g, ''), 10);
                    if (isNaN(n) || n < 0) continue;
                    nums.push(n);
                }
                if (nums.length >= 1) r.reposts = nums[0];
                if (nums.length >= 2) r.comments = nums[1];
                var likeEl = footer.querySelector('[class*=woo-like-count]');
                if (likeEl) {
                    var lt = likeEl.textContent.trim();
                    if (lt) { var ln = parseInt(lt.replace(/,/g, ''), 10); if (!isNaN(ln)) r.likes = ln; }
                }
            }
            // innerText 回退
            if (r.reposts < 0 || r.comments < 0 || r.likes < 0) {
                var all = document.body.innerText || '';
                var m;
                if (r.reposts < 0) { m = all.match(/转发[\\s\\S]{0,3}([\\d,]*)/); if (m) r.reposts = parseInt(m[1].replace(/,/g,''), 10); }
                if (r.comments < 0) { m = all.match(/评论[\\s\\S]{0,3}([\\d,]*)/); if (m) r.comments = parseInt(m[1].replace(/,/g,''), 10); }
                if (r.likes < 0) { m = all.match(/赞[\\s\\S]{0,3}([\\d,]*)/); if (m) r.likes = parseInt(m[1].replace(/,/g,''), 10); }
            }

            return r;
        }
        """)

        print(f"  正文: {len(detail.get('text',''))} 字", file=sys.stderr)
        print(f"  互动: 转={detail.get('reposts',-1)} 评={detail.get('comments',-1)} 赞={detail.get('likes',-1)}", file=sys.stderr)

        # 评论 — 直接调微博 API，不依赖 DOM 虚拟滚动
        comments_list = []
        if max_comments > 0:
            await detail_page.wait_for_timeout(500)
            # 从 performance API 拿到 buildComments 请求的数字 id
            weibo_id = await detail_page.evaluate("""
                () => {
                    try {
                        var entries = performance.getEntriesByType('resource');
                        for (var i = entries.length - 1; i >= 0; i--) {
                            var url = entries[i].name;
                            var idx = url.indexOf('buildComments?id=');
                            if (idx >= 0) {
                                var after = url.substring(idx + 17);
                                var end = after.indexOf('&');
                                if (end > 0) return after.substring(0, end);
                            }
                            idx = url.indexOf('buildComments?');
                            if (idx >= 0) {
                                var qs = url.substring(idx + 14);
                                for (var part of qs.split('&')) {
                                    if (part.startsWith('id=')) return part.substring(3);
                                }
                            }
                        }
                    } catch(e) {}
                    // fallback: 从 URL 取
                    var m = location.href.match(/weibo\\.com\\/\\d+\\/([a-zA-Z0-9]+)/);
                    return m ? m[1] : null;
                }
            """)
            uid = await detail_page.evaluate("location.pathname.match(/\\/(\\d+)\\//)?.[1] || ''")
            print(f"    weibo_id={weibo_id}", file=sys.stderr) if weibo_id else None

            if weibo_id:
                all_comments = []
                seen = set()
                max_id = 0
                for _ in range(100):
                    if len(all_comments) >= max_comments:
                        break
                    params = f"is_reload=1&id={weibo_id}&is_show_bulletin=2&is_mix=0&count=20&fetch_level=0&locale=zh-CN"
                    if uid:
                        params += f"&uid={uid}"
                    if max_id:
                        params += f"&max_id={max_id}"

                    result = await detail_page.evaluate(f"""async () => {{
                        try {{
                            var r = await fetch('/ajax/statuses/buildComments?{params}');
                            return await r.json();
                        }} catch(e) {{ return {{}}; }}
                    }}""")
                    if not result.get('ok') or not result.get('data'):
                        break

                    import re
                    for c in (result.get('data', []) or []):
                        raw = (c.get('text_raw', '') or '').strip()
                        text = re.sub(r'\[[^\]]+\]', '', raw).strip()
                        if not text:
                            text = (c.get('text', '') or '').strip()
                            text = re.sub(r'<[^>]+>', '', text).strip()
                        if text:
                            key = text[:50]
                            if key not in seen:
                                seen.add(key)
                                user_name = c.get('user', {}).get('screen_name', '') if isinstance(c.get('user'), dict) else ''
                                all_comments.append({"user": user_name, "content": text, "likes": c.get('like_counts', 0)})

                    new_max_id = result.get('max_id', 0)
                    if not new_max_id or new_max_id == max_id:
                        break
                    max_id = new_max_id
                    if len(result.get('data', [])) < 20:
                        break

                comments_list = all_comments[:max_comments]
                print(f"  评论: {len(comments_list)} 条（API）", file=sys.stderr)
            else:
                print(f"  ⚠️ 无法获取 weibo_id，跳过评论", file=sys.stderr)

        return {
            "platform": "weibo",
            "url": url,
            "text": detail.get("text", ""),
            "author": detail.get("author", ""),
            "reposts": detail.get("reposts", -1),
            "comments": detail.get("comments", -1),
            "likes": detail.get("likes", -1),
            "comments_text": flatten_comments(comments_list),
        }
    finally:
        await detail_page.close()


def main():
    parser = argparse.ArgumentParser(description="单条 URL 详情采集")
    parser.add_argument("--account", default=None, help="使用的账号ID（BrowserManager 管理）")
    parser.add_argument("--url", required=True, help="小红书/微博内容 URL")
    parser.add_argument("--max-comments", type=int, default=30, help="最多采集评论数（默认 30）")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径")
    args = parser.parse_args()

    print(f"采集 URL: {args.url}", file=sys.stderr)
    print(f"最大评论: {args.max_comments}", file=sys.stderr)

    result = asyncio.run(scrape_url_detail(args.url, max_comments=args.max_comments, account=args.account))

    from datetime import datetime
    output = {
        "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "url_detail",
        "data": result,
    }

    write_output(output, args.output)


if __name__ == "__main__":
    main()
