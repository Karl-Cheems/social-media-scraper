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


async def scrape_url_detail(url: str, max_comments: int = 30, headless: bool = False) -> dict:
    """抓取单条 URL 的内容详情（正文、互动量、评论）。"""
    platform = detect_platform(url)
    edge_user_data = get_edge_user_data()

    async with async_playwright() as p:
        context, page, _tmpdir = await launch_browser(p, headless=headless, user_data_dir=edge_user_data, label="url_detail")

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

    # 检测反爬并重试
    for _ in range(2):
        adblock = await page.evaluate(
            "document.body.innerText.indexOf('广告屏蔽插件') >= 0 || document.body.innerText.indexOf('您的浏览器似乎开') >= 0"
        )
        if adblock:
            print("  详情页被反爬拦截，重试...", file=sys.stderr)
            # goto 重新打开
            xsec_match2 = re.search(r'xsec_token=([^&]+)', url)
            goto_url2 = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_match2.group(1)}&xsec_source=pc_search" if xsec_match2 else f"https://www.xiaohongshu.com/explore/{note_id}"
            await page.goto(goto_url2, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(5000)
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
        else:
            break
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

        # 评论
        comments_list = []
        if max_comments > 0:
            scroll_rounds = min(30, max(5, max_comments // 4))
            for _ in range(scroll_rounds):
                await detail_page.evaluate("window.scrollBy(0, 1500)")
                await detail_page.wait_for_timeout(800)

            comments_list = await detail_page.evaluate("""
            (maxC) => {
                var text = document.body.innerText || '';
                var lines = text.split('\\n').filter(function(l){return l.trim()});

                var commentStart = -1;
                for (var i = 0; i < lines.length; i++) {
                    if (lines[i] === '评论') { commentStart = i + 1; break; }
                }
                if (commentStart < 0) {
                    // 没找到"评论"标记，改用 DOM 方式：找"按热度"或"按时间"
                    for (var i = 0; i < lines.length; i++) {
                        if (lines[i] === '按热度' || lines[i] === '按时间') { commentStart = i; break; }
                    }
                    if (commentStart < 0) return [];
                }

                var idx = commentStart;
                // 跳过排序标签
                while (idx < lines.length && (lines[idx] === '按热度' || lines[idx] === '按时间')) idx++;
                // 跳过空行找到第一个用户名（非数字、非日期、非空的行）
                while (idx < lines.length) {
                    var l = lines[idx];
                    if (/^\\d{1,2}-\\d{1,2}/.test(l) || /^\\d{1,2}月/.test(l) || l.indexOf('发布于') >= 0 || l.indexOf('来自') >= 0 || /^\\d+$/.test(l)) {
                        idx++;
                    } else { break; }
                }

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
            }
            """, max_comments)

        print(f"  评论: {len(comments_list)} 条", file=sys.stderr)

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
    parser.add_argument("--url", required=True, help="小红书/微博内容 URL")
    parser.add_argument("--max-comments", type=int, default=30, help="最多采集评论数（默认 30）")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径")
    args = parser.parse_args()

    print(f"采集 URL: {args.url}", file=sys.stderr)
    print(f"最大评论: {args.max_comments}", file=sys.stderr)

    result = asyncio.run(scrape_url_detail(args.url, max_comments=args.max_comments))

    from datetime import datetime
    output = {
        "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "url_detail",
        "data": result,
    }

    write_output(output, args.output)


if __name__ == "__main__":
    main()
