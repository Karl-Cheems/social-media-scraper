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
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=edge_user_data, channel="msedge",
                    headless=False, args=["--disable-sync"],
                    viewport={"width": 1920, "height": 1080},
                )
                page = await context.new_page()
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

            # 提取微博数据（初始加载的 article 就是最新的，不做滚动避免 DOM 重排）
            weibo_data = await page.evaluate(
                """() => {
                    var arts = document.querySelectorAll('article');
                    var r = [];
                    for (var i = 0; i < arts.length; i++) {
                        var a = arts[i];
                        var textEl = a.querySelector('[class*=_text_], [class*=_wbtext_], [class*=_ogText_]');
                        var text = textEl ? textEl.textContent.trim() : '';
                        if (!text) text = (a.textContent || '').trim();

                        // 详情页链接：时间标签上的 href
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

            print(f"加载到 {len(weibo_data)} 条微博", file=sys.stderr)

            # 如果初始不够 limit，再滚动加载更多
            scroll_rounds = 0
            while len(weibo_data) < limit and scroll_rounds < 20:
                await page.evaluate("window.scrollBy(0, 1200)")
                await page.wait_for_timeout(2000)
                more = await page.evaluate(
                    """() => {
                        var arts = document.querySelectorAll('article');
                        var urls = [];
                        for (var a of arts) {
                            var timeLink = a.querySelector('[class*=_time_]');
                            if (timeLink) {
                                var href = timeLink.getAttribute('href') || '';
                                if (href && !href.startsWith('http')) href = 'https:' + href;
                                if (href.includes('weibo.com')) urls.push(href);
                            }
                        }
                        return urls;
                    }"""
                )
                # 只取新出现的 URL
                existing_urls = {w.get("url", "") for w in weibo_data}
                new_count = sum(1 for u in more if u not in existing_urls)
                if new_count == 0:
                    scroll_rounds += 1
                else:
                    scroll_rounds = 0

                # 重新提取全部（去重）
                all_data = await page.evaluate(
                    """() => {
                        var arts = document.querySelectorAll('article');
                        var r = [];
                        var seen = {};
                        for (var i = 0; i < arts.length; i++) {
                            var a = arts[i];
                            var timeLink = a.querySelector('[class*=_time_]');
                            var detailUrl = '';
                            if (timeLink) {
                                var href = timeLink.getAttribute('href') || '';
                                if (href && !href.startsWith('http')) href = 'https:' + href;
                                if (href.includes('weibo.com')) detailUrl = href;
                            }
                            if (seen[detailUrl]) continue;
                            seen[detailUrl] = true;

                            var textEl = a.querySelector('[class*=_text_], [class*=_wbtext_], [class*=_ogText_]');
                            var text = textEl ? textEl.textContent.trim() : '';
                            if (!text) text = (a.textContent || '').trim();

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
                # 去重保持初始顺序
                seen = set()
                weibo_data = []
                for item in all_data:
                    u = item.get("url", "")
                    if u and u not in seen:
                        seen.add(u)
                        weibo_data.append(item)
                print(f"  滚动后共 {len(weibo_data)} 条", file=sys.stderr)

            # 取最新的 limit 条（保持 DOM 顺序，最上面最新）
            weibo_data = weibo_data[:limit]
            print(f"取前 {len(weibo_data)} 条最新微博", file=sys.stderr)

            # 先提取所有微博数据（不含评论）
            for item in weibo_data:
                text = (item.get("text", "") or "")[:300]
                reposts = item.get("reposts", -1)
                comments = item.get("comments", -1)
                likes = item.get("likes", -1)
                detail_url = item.get("url", "")

                weibo = WeiboEngagement(
                    text=text,
                    reposts=reposts,
                    comments=comments,
                    likes=likes,
                    url=detail_url,
                )
                weibos.append(weibo)
                rs = f"{reposts}" if reposts >= 0 else "?"
                cs = f"{comments}" if comments >= 0 else "?"
                ls = f"{likes}" if likes >= 0 else "?"
                print(f"  [{len(weibos)}] {text[:24]}... 转={rs} 评={cs} 赞={ls}", file=sys.stderr)

            # 第二阶段：如有需要，单独遍历详情页提取评论（直接用 goto，不用 go_back）
            if fetch_comments:
                print(f"\n开始提取评论（{len(weibos)} 条微博）...", file=sys.stderr)
                for idx, weibo in enumerate(weibos):
                    detail_url = weibo.url
                    if not detail_url:
                        continue
                    try:
                        await page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(5000)

                        # 多次滚动以触发评论加载（视频类尤其需要）
                        for _ in range(3):
                            await page.evaluate("window.scrollBy(0, 1500)")
                            await page.wait_for_timeout(1500)

                        # 从详情页提取评论
                        comments_list = await page.evaluate(
                            """(maxC) => {
                                var text = document.body.innerText || '';
                                var lines = text.split('\\n').filter(function(l){return l.trim()});

                                // 找 "评论" 之后的部分
                                var commentStart = -1;
                                for (var i = 0; i < lines.length; i++) {
                                    if (lines[i] === '评论') { commentStart = i + 1; break; }
                                }
                                if (commentStart < 0) return [];

                                // 跳过 "按热度 / 按时间" 头
                                var idx = commentStart;
                                while (idx < lines.length && (lines[idx] === '按热度' || lines[idx] === '按时间')) idx++;

                                // 跳过原帖作者信息（第一组：用户名、:内容、时间地点、点赞数）
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
                                        // 点赞数字行 - 忽略
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

                        weibo.comments_list = [CommentItem(**c) for c in comments_list]
                        print(f"  [{idx+1}] 评论 {len(comments_list)} 条", file=sys.stderr)

                    except Exception as e:
                        print(f"  [{idx+1}] 评论提取异常: {e}", file=sys.stderr)

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
