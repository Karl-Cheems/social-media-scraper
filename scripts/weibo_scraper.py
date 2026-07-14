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
# ── 路径修补 ──
_scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from pydantic import BaseModel, Field
from playwright.async_api import async_playwright

from common import CommentItem, flatten_comments, kill_edge, launch_browser, get_edge_user_data, write_output, random_delay, normalize_time, wait_for_login


class WeiboEngagement(BaseModel):
    """单条微博的运营数据结构"""
    text: str = Field(description="微博正文")
    reposts: int = Field(description="转发数")
    comments: int = Field(description="评论数")
    likes: int = Field(description="点赞数")
    published_at: str = Field(default="", description="发布时间（如 2小时前、06-28）")
    comments_list: list[CommentItem] = Field(default_factory=list, description="评论列表")
    url: str = Field(description="微博链接")


class ProfileResult(BaseModel):
    """账号内容汇总"""
    author: str = Field(description="账号名称")
    total_collected: int = Field(description="实际采集到的微博数量")
    weibos: list[WeiboEngagement] = Field(description="微博运营数据列表")


# 元气森林官方微博主页（锐意进去自动跳到自己的首页，还是加?feature=homepage）
DEFAULT_PROFILE_URL = "https://weibo.com/5822662089?refer_flag=1001030103_"


async def scrape_profile(
    profile_url: str = DEFAULT_PROFILE_URL,
    limit: int = 10,
    headless: bool = False,
    fetch_comments: bool = False,
    max_comments: int = 10,
) -> ProfileResult:
    """打开微博账号主页，采集该账号发布的微博数据。"""
    weibos = []
    author_name = ""
    edge_user_data = get_edge_user_data()

    async with async_playwright() as p:
        context, page, _tmpdir = await launch_browser(p, headless=headless, user_data_dir=edge_user_data, label="weibo_scraper")

        try:
            print(f"正在打开用户主页: {profile_url}", file=sys.stderr)
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            # 检测是否登录
            current_url = page.url
            login_detected = (
                "login" in current_url or "passport" in current_url
                or "微博" not in await page.title()
            )
            if login_detected:
                print("\n⚠️ 检测到未登录，请在浏览器窗口中完成登录", file=sys.stderr)
                await wait_for_login(page)

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
                await page.wait_for_timeout(1000)

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

                            var isPinned = (a.textContent || '').indexOf('置顶') >= 0;

                            var pubTime = '';
                            if (timeLink) {
                                pubTime = (timeLink.textContent || '').trim();
                            }
                            if (!pubTime) {
                                var timeEl = a.querySelector('time, [datetime], [class*=_time_]');
                                if (timeEl) pubTime = (timeEl.textContent || timeEl.getAttribute('datetime') || '').trim();
                            }

                            var footer = a.querySelector('footer');
                            var reposts = -1, comments = -1, likes = -1;
                            (function() {
                                if (footer) {
                                    var numEls = footer.querySelectorAll('[class*=_num_]');
                                    for (var j = 0; j < numEls.length; j++) {
                                        var t = numEls[j].textContent.trim();
                                        if (!t) continue;
                                        if (t === '转发') { reposts = 0; continue; }
                                        if (t === '评论' || t === '赞') continue;
                                        var n = parseInt(t.replace(/,/g, ''), 10);
                                        if (isNaN(n) || n < 0) continue;
                                        if (reposts < 0) reposts = n;
                                        else if (comments < 0) comments = n;
                                    }
                                    var likeEl = footer.querySelector('[class*=woo-like-count]');
                                    if (likeEl) {
                                        var lt = likeEl.textContent.trim();
                                        if (lt) { var ln = parseInt(lt.replace(/,/g, ''), 10); if (!isNaN(ln)) likes = ln; }
                                    }
                                }
                                if (reposts < 0 || comments < 0 || likes < 0) {
                                    var all = a.textContent;
                                    var m;
                                if (reposts < 0) { m = all.match(/转发[\\s\\S]{0,3}([\\d,]*)/); if (m) reposts = parseInt(m[1].replace(/,/g,''), 10); }
                                    if (comments < 0) { m = all.match(/评论[\\s\\S]{0,3}([\\d,]*)/); if (m) comments = parseInt(m[1].replace(/,/g,''), 10); }
                                    if (likes < 0) { m = all.match(/赞[\\s\\S]{0,3}([\\d,]*)/); if (m) likes = parseInt(m[1].replace(/,/g,''), 10); }
                                }
                            })();

                            if (text.length > 10) {
                                r.push({ text: text, reposts: reposts, comments: comments, likes: likes, url: detailUrl, pinned: isPinned, pubTime: pubTime });
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

            # 过滤置顶，取最新的 limit 条
            pinned_count = sum(1 for w in weibo_data if w.get("pinned"))
            weibo_data = [w for w in weibo_data if not w.get("pinned")][:limit]
            if pinned_count:
                print(f"跳过 {pinned_count} 条置顶，取前 {len(weibo_data)} 条最新微博", file=sys.stderr)
            else:
                print(f"取前 {len(weibo_data)} 条最新微博", file=sys.stderr)

            # 第二阶段：用点击方式进入详情页获取完整正文和评论
            print(f"\n进入详情页获取完整正文...", file=sys.stderr)
            for idx, item in enumerate(weibo_data):
                if idx > 0:
                    await random_delay(1, 3, "微博详情页间隔")
                text_short = (item.get("text", "") or "")[:30]
                reposts = item.get("reposts", -1)
                comment_count = item.get("comments", -1)
                likes = item.get("likes", -1)
                detail_url = item.get("url", "")

                full_text = ""
                comments_list = []

                if detail_url:
                    # 在新 tab 中打开详情页，提取完自动关闭
                    detail_page = await context.new_page()
                    try:
                        await detail_page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
                        await detail_page.wait_for_timeout(3000)

                        # 从详情页提取完整正文
                        full_text = await detail_page.evaluate("""
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

                        # 在详情页重新提取互动数据（比列表页更准确）
                        detail_nums = await detail_page.evaluate("""
                            () => {
                                var all = document.body.innerText || '';
                                var r = { reposts: -1, comments: -1, likes: -1 };
                                var m;
                                m = all.match(/转发[\\s\\S]{0,3}([\\d,]*)/); if (m) r.reposts = parseInt(m[1].replace(/,/g,''), 10);
                                m = all.match(/评论[\\s\\S]{0,3}([\\d,]*)/); if (m) r.comments = parseInt(m[1].replace(/,/g,''), 10);
                                m = all.match(/赞[\\s\\S]{0,3}([\\d,]*)/); if (m) r.likes = parseInt(m[1].replace(/,/g,''), 10);
                                return r;
                            }
                        """)
                        if detail_nums.get("reposts", -1) >= 0:
                            reposts = detail_nums["reposts"]
                        if detail_nums.get("comments", -1) >= 0:
                            comment_count = detail_nums["comments"]
                        if detail_nums.get("likes", -1) >= 0:
                            likes = detail_nums["likes"]

                        # 多次滚动以触发评论加载（微博需鼠标定位评论区 + wheel 事件）
                        if fetch_comments:
                            # 先定位到"评论"元素，鼠标移到评论区上方
                            comment_pos = await detail_page.evaluate("""
                                (() => {
                                    var els = document.querySelectorAll('*');
                                    for (var el of els) {
                                        if (el.children.length === 0 && (el.textContent || '').trim() === '评论') {
                                            el.scrollIntoView({block: 'start'});
                                            var r = el.getBoundingClientRect();
                                            return {top: r.top, left: r.left, bottom: r.bottom};
                                        }
                                    }
                                    return null;
                                })()
                            """)
                            await detail_page.wait_for_timeout(500)
                            max_rounds = min(20, max(5, max_comments // 5))
                            # 鼠标移到评论区域再 wheel（微博评论懒加载依赖 wheel 事件，window.scrollBy 无效）
                            if comment_pos and comment_pos['top'] > 0:
                                await detail_page.mouse.move(comment_pos['left'] + 50, comment_pos['top'] + 10, steps=3)
                            prev_cols = 0
                            stale = 0
                            for _ in range(max_rounds):
                                await detail_page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                                await detail_page.wait_for_timeout(300)
                                await detail_page.mouse.wheel(0, 200)
                                await detail_page.wait_for_timeout(500)
                                # 动态检测评论行数，不增长就提前结束
                                cur = await detail_page.evaluate(
                                    "() => document.body.innerText.split(String.fromCharCode(10)).filter(function(l){return l.indexOf(':')===0 && l.length > 2}).length"
                                )
                                if cur > prev_cols:
                                    stale = 0
                                    prev_cols = cur
                                else:
                                    stale += 1
                                    if stale >= 3:
                                        break

                            comments_list = await detail_page.evaluate(
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
                                }""",
                                max_comments
                            )

                        if detail_url:
                            pub_time = await detail_page.evaluate("""
                                () => {
                                    var el = document.querySelector('time, [datetime], [class*=_time_]');
                                    return el ? (el.textContent || el.getAttribute('datetime') || '').trim() : '';
                                }
                            """)
                    except Exception as e:
                        print(f"  [{idx+1}] 详情页异常: {e}", file=sys.stderr)
                    finally:
                        await detail_page.close()

                # 如果没有取到详情页完整文本，回退到首页截断文本
                if not full_text:
                    full_text = (item.get("text", "") or "")[:300]

                pub_time = item.get("pubTime", "") or ""
                pub_time = normalize_time(pub_time)

                weibo = WeiboEngagement(
                    text=full_text,
                    reposts=reposts,
                    comments=comment_count,
                    likes=likes,
                    published_at=pub_time,
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
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径")
    parser.add_argument("--comments", action="store_true", help="同时采集评论内容")
    parser.add_argument("--max-comments", type=int, default=60, help="每条微博最多采集评论数（默认 60）")
    parser.add_argument(
        "--url",
        default=DEFAULT_PROFILE_URL,
        help="用户主页 URL（默认：元气森林官方微博）",
    )

    args = parser.parse_args()

    result = asyncio.run(scrape_profile(
        profile_url=args.url,
        limit=args.limit,
        headless=False,
        fetch_comments=args.comments,
        max_comments=args.max_comments,
    ))

    output = result.model_dump(mode="json")
    # 压平评论为纯文本
    for w in output.get("weibos", []):
        if "comments_list" in w:
            w["comments_text"] = flatten_comments(w["comments_list"])
            del w["comments_list"]

    write_output(output, args.output)


if __name__ == "__main__":
    main()
