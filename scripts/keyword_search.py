"""
关键词采集脚本 — 微博 & 小红书
使用 Playwright + Edge 浏览器，根据关键词在站内搜索并采集相关内容。
用法：
    python scripts/keyword_search.py --keywords 元气森林,气泡水 --platforms both --per-keyword 5
    python scripts/keyword_search.py --keywords 元气森林 --platforms weibo --per-keyword 10 --max-comments 5 --visible --output result.json
"""

import argparse
import asyncio
import json
import os
import random
import re
import sys

from datetime import datetime
from urllib.parse import quote

from playwright.async_api import async_playwright

from common import CommentItem, flatten_comments, kill_edge, launch_browser, get_edge_user_data, write_output, random_delay, wait_for_login, xhs_search_by_input, detect_xhs_ui_version, xhs_expand_comments


# ---------- 微博搜索 ----------

async def _search_weibo(page, keyword: str, per_keyword: int) -> list[dict]:
    """在微博搜索关键词，返回搜索结果列表（不进入详情页）。
    每个 item dict 结构：{title, text, author, reposts, comments, likes, collects, url, time}
    """
    search_url = f"https://s.weibo.com/weibo?q={quote(keyword)}&xsort=hot"
    print(f"  微博搜索: {keyword}", file=sys.stderr)

    await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(5000)

    # 检测是否被重定向到登录页
    if "passport" in page.url or "login" in page.url:
        print("  ⚠️ 微博未登录，尝试继续", file=sys.stderr)

    # 滚动加载更多结果
    seen_texts = set()
    results = []
    stale_rounds = 0
    while len(results) < per_keyword and stale_rounds < 5:
        await page.evaluate("window.scrollBy(0, 1200)")
        await page.wait_for_timeout(2000)

        batch = await page.evaluate(
            """() => {
                const cards = document.querySelectorAll('.card-wrap');
                const items = [];
                for (const card of cards) {
                    // 提取正文
                    const textEl = card.querySelector('.txt, .card-txt, p.txt, [class*="txt_"]');
                    let text = textEl ? textEl.textContent.trim() : '';
                    if (!text) {
                        const node = card.querySelector('[node-type="text"], .WB_text');
                        if (node) text = node.textContent.trim();
                    }

                    // 提取标题（取正文前 80 字）
                    const title = text.length > 80 ? text.slice(0, 80) + '...' : text;

                    // 提取作者
                    let author = '';
                    const nameEl = card.querySelector('.name, .W_f14, a[name="username"], [class*="name_"]');
                    if (nameEl) author = nameEl.textContent.trim();
                    if (!author) {
                        const sub = card.querySelector('.sub, .info .name');
                        if (sub) author = sub.textContent.trim();
                    }

                    // 提取互动数据 — 直接用.card-act 文本按空白切分取数字
                    let reposts = -1, comments = -1, likes = -1;
                    (function() {
                        const actEl = card.querySelector('.card-act, .action, .media_action');
                        if (actEl) {
                            const parts = (actEl.textContent || '').trim().split(/\\s+/);
                            const nums = [];
                            for (let p of parts) {
                                if (p === '转发' || p === '评论' || p === '赞') continue;
                                let n = parseInt(p.replace(/,/g, ''), 10);
                                if (isNaN(n)) {
                                    if (p.includes('万')) {
                                        n = Math.round(parseFloat(p) * 10000);
                                    } else { continue; }
                                }
                                nums.push(n);
                            }
                            if (nums.length > 0) reposts = nums[0];
                            if (nums.length > 1) comments = nums[1];
                            if (nums.length > 2) likes = nums[2];
                        }
                    })();

                    // 提取链接 — s.weibo.com 搜索结果页的链接可能是相对路径或短片 ID
                    let url = '';
                    // 优先：.from a 时间戳链接（通常带详情页地址）
                    const timeLink = card.querySelector('.from a');
                    if (timeLink) {
                        let href = timeLink.getAttribute('href') || '';
                        if (href) {
                            if (href.startsWith('//')) href = 'https:' + href;
                            else if (href.startsWith('/')) href = 'https://weibo.com' + href;
                            url = href;
                        }
                    }
                    if (!url) {
                        // 回退：找任意包含 weibo.com 或 weibo.cn 的链接
                        const anyLink = card.querySelector('a[href*="weibo.com"], a[href*="weibo.cn"], a[href*="s.weibo.com"]');
                        if (anyLink) {
                            let href = anyLink.getAttribute('href') || '';
                            if (href.startsWith('//')) href = 'https:' + href;
                            url = href;
                        }
                    }
                    if (!url) {
                        // 最后回退：找 card 中任意 non-empty href
                        const allLinks = card.querySelectorAll('a[href]');
                        for (const a of allLinks) {
                            let href = a.getAttribute('href') || '';
                            if (href && !href.startsWith('#') && !href.startsWith('javascript:')) {
                                if (href.startsWith('//')) href = 'https:' + href;
                                else if (href.startsWith('/')) href = 'https://weibo.com' + href;
                                url = href;
                                break;
                            }
                        }
                    }

                    // 提取时间
                    let time = '';
                    const timeEl = card.querySelector('.time, .from a, [class*="time_"]');
                    if (timeEl) time = timeEl.textContent.trim();

                    if (text && text.length > 5) {
                        items.push({
                            title: title,
                            text: text,
                            author: author,
                            reposts: reposts,
                            comments: comments,
                            likes: likes,
                            collects: 0,
                            url: url,
                            time: time,
                        });
                    }
                }
                return items;
            }"""
        )

        new_count = 0
        for item in batch:
            key = (item.get("text") or "")[:80]
            if key and key not in seen_texts:
                seen_texts.add(key)
                results.append(item)
                new_count += 1

        if new_count == 0:
            stale_rounds += 1
        else:
            stale_rounds = 0

        print(f"    滚动中.. 累计 {len(results)} 条", file=sys.stderr)

    results = results[:per_keyword]
    return results


async def _fetch_weibo_detail(page, item: dict, max_comments: int) -> dict:
    """进入微博详情页，提取完整正文和评论列表。
    复用当前 tab，提取完后退回到搜索结果页。
    返回与 item 相同结构的 dict，但 text 为完整正文，
    并附加 comments_list。
    """
    detail_url = item.get("url", "")
    if not detail_url:
        return {**item, "text": item.get("text", "")[:300], "comments_list": []}

    try:
        await page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)

        # 获取完整正文
        full_text = await page.evaluate("""
            () => {
                var candidates = document.querySelectorAll(
                    '[class*=_ogText_], [class*=_text_], [class*=_wbtext_], .WB_text, [node-type="text"]'
                );
                var best = '';
                for (var el of candidates) {
                    var t = (el.textContent || '').trim();
                    if (t.length > best.length) best = t;
                }
                return best.length > 20 ? best : '';
            }
        """)
        if not full_text:
            full_text = (item.get("text", "") or "")[:300]

        # 在详情页重新提取互动数据（比列表页更准确）
        detail_nums = await page.evaluate("""
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
        reposts = detail_nums.get("reposts", -1) if detail_nums.get("reposts", -1) >= 0 else item.get("reposts", -1)
        comments = detail_nums.get("comments", -1) if detail_nums.get("comments", -1) >= 0 else item.get("comments", -1)
        likes = detail_nums.get("likes", -1) if detail_nums.get("likes", -1) >= 0 else item.get("likes", -1)

        # 提取评论
        comments_list = []
        if max_comments > 0:
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
                        if (l === '已加载全部评论' || l === '分享这条微博') break;
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
                max_comments,
            )

        return {
            **item,
            "text": full_text,
            "reposts": reposts,
            "comments": comments,
            "likes": likes,
            "comments_list": comments_list,
        }
    except Exception as e:
        print(f"    微博详情页异常: {e}", file=sys.stderr)
        return {**item, "text": item.get("text", "")[:300], "comments_list": []}


async def search_weibo(page, keyword: str, per_keyword: int, max_comments: int) -> list[dict]:
    """在微博搜索关键词，先尝试智搜回答，若没有则走普通搜索结果。"""
    search_url = f"https://s.weibo.com/weibo?q={quote(keyword)}&xsort=hot"

    # 先试智搜
    try:
        zhishou_url = f"https://s.weibo.com/aisearch?q={quote(keyword)}&Refer=weibo_aisearch"
        await page.goto(zhishou_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # 提取智搜回答
        zhishou_text = await page.evaluate("""
            () => {
                var all = document.body.innerText || '';
                var lines = all.split(String.fromCharCode(10));
                var skip = new Set(['NEW', '综合', '用户', '实时', '视频', '图片', '关注', '超话',
                    '高级搜索', '搜索结果', '更多', '刷新', '我的', '微博热搜', '热搜榜', '文娱榜',
                    '首页', '推荐', '话题', '智搜']);
                var clean = [];
                var inAnswer = false;
                for (var i = 0; i < lines.length; i++) {
                    var l = lines[i].trim();
                    if (!l) continue;
                    if (l === '回答' || l === '深度思考') { inAnswer = true; continue; }
                    if (l.indexOf('信源追溯') >= 0 || l.indexOf('风险提示') >= 0) break;
                    if (skip.has(l)) continue;
                    if (inAnswer && l.length > 3) clean.push(l);
                }
                return clean.join(String.fromCharCode(10));
            }
        """)

        if zhishou_text and len(zhishou_text) > 50:
            print(f"    ✅ 使用智搜回答（{len(zhishou_text)} 字符）", file=sys.stderr)
            return [{
                "title": f"智搜 · {keyword}",
                "text": zhishou_text,
                "author": "智搜回答",
                "url": zhishou_url,
            }]
        else:
            print(f"    智搜回答为空，走普通搜索", file=sys.stderr)
    except Exception as e:
        print(f"    智搜失败（{e}），走普通搜索", file=sys.stderr)

    # 走普通搜索
    items = await _search_weibo(page, keyword, per_keyword)

    print(f"    进入详情页获取完整正文和评论...", file=sys.stderr)
    for idx, item in enumerate(items):
        if idx > 0:
            await random_delay(3, 6, "微博详情页间隔")
        enriched = await _fetch_weibo_detail(page, item, max_comments)
        items[idx] = enriched
        t = (enriched.get("text") or "")[:24]
        r = enriched.get("reposts", "?")
        c = enriched.get("comments", "?")
        l = enriched.get("likes", "?")
        cc = f"({len(enriched.get('comments_list', []))}条评论)" if enriched.get("comments_list") else ""
        print(f"      [{idx+1}] {t}... 转{r} 评{c} 赞{l}{cc}", file=sys.stderr)

    return items


# ---------- 小红书搜索 ----------


async def _do_xiaohongshu_search(page, keyword: str) -> bool:
    """模拟真人操作：打开 explore → 点击搜索框 → 逐字输入 → 回车搜索。"""
    print(f"  小红书搜索: {keyword}", file=sys.stderr)

    try:
        ok = await xhs_search_by_input(page, keyword, f"搜索「{keyword}」")
        if not ok:
            print(f"    ⚠️ 搜索框输入失败，放弃搜索", file=sys.stderr)
            return False

        # 验证搜索结果
        has_cards = await page.evaluate("document.querySelectorAll('section.note-item').length > 0")
        if not has_cards:
            print(f"    搜索结果未加载，等待再试...", file=sys.stderr)
            await page.wait_for_timeout(8000)
            has_cards = await page.evaluate("document.querySelectorAll('section.note-item').length > 0")
            if not has_cards:
                print(f"    ⚠️ 搜索结果未加载（可能被风控拦截）", file=sys.stderr)
                return False
        return True
    except Exception as e:
        print(f"    小红书搜索异常: {e}", file=sys.stderr)
        return False


async def _search_xiaohongshu(page, keyword: str, per_keyword: int, sort_by: str = "likes", content_type: str = "all") -> list[dict]:
    """在小红书搜索关键词，返回搜索结果列表（不进入详情页）。
    模拟真人操作：打开 explore → 点击搜索框 → 逐字输入 → 点击搜索。
    不使用 page.goto() 直接构造搜索结果 URL（这是最明显的机器特征）。
    每个 item dict 结构：{title, text, author, reposts, comments, likes, collects, url, time}
    """
    print(f"  小红书搜索: {keyword}", file=sys.stderr)

    try:
        ok = await _do_xiaohongshu_search(page, keyword)
        if not ok:
            return []
    except Exception as e:
        print(f"    小红书搜索异常: {e}", file=sys.stderr)
        return []

    # 打开筛选面板
    try:
        ui_version = await detect_xhs_ui_version(page)
        print(f"    UI: {ui_version}", file=sys.stderr)

        # 用 JS dispatchEvent 触发筛选按钮（Vue 只响应 isTrusted 的真实事件）
        await page.evaluate("""() => {
            var btn = document.querySelector('.filter, .ai-chat-filter');
            if (btn) btn.dispatchEvent(new MouseEvent('click', { bubbles: true, view: window }));
        }""")
        print(f"    筛选按钮已点击", file=sys.stderr)

        # 轮询检测面板，最多 2s
        has_panel = False
        for _ in range(10):
            await page.wait_for_timeout(200)
            if await page.evaluate("document.querySelector('.filter-panel') ? true : false"):
                has_panel = True
                break

        if has_panel:
            print(f"    筛选面板已展开", file=sys.stderr)
            sort_tag = "最多点赞" if sort_by == "likes" else "最多评论"
            need_tags = [sort_tag, '一周内']
            if content_type == "image_text":
                need_tags.append('图文')
            for tag_text in need_tags:
                try:
                    coords = await page.evaluate(f"""(text) => {{
                        var panel = document.querySelector('.filter-panel');
                        if (!panel) return null;
                        var els = panel.querySelectorAll('div');
                        for (var d of els) {{
                            var r = d.getBoundingClientRect();
                            if (r.width < 20 || r.height < 20) continue;
                            if ((d.textContent || '').trim() === text) {{
                                return {{ x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2) }};
                            }}
                            var spans = d.querySelectorAll('span');
                            for (var s of spans) {{
                                if ((s.textContent || '').trim() === text) {{
                                    var sr = s.getBoundingClientRect();
                                    if (sr.width >= 20 && sr.height >= 20) {{
                                        return {{ x: Math.round(sr.left + sr.width/2), y: Math.round(sr.top + sr.height/2) }};
                                    }}
                                }}
                            }}
                        }}
                        return null;
                    }}""", tag_text)
                    if coords:
                        await page.mouse.click(coords['x'], coords['y'])
                        print(f"    点击: {tag_text} ✓", file=sys.stderr)
                except Exception as e:
                    print(f"    点击「{tag_text}」失败: {e}", file=sys.stderr)
                await page.wait_for_timeout(2000)
        else:
            print(f"    筛选面板未显示", file=sys.stderr)

        # 关面板
        try: await filter_btn.click(force=True)
        except: pass

        print(f"    筛选完成", file=sys.stderr)
    except Exception as e:
        print(f"    筛选设置失败: {e}", file=sys.stderr)

    # 滚动加载
    max_scroll = 50
    last_count = 0
    stale_rounds = 0
    scroll_target = per_keyword + 5
    for i in range(max_scroll):
        current_count = await page.evaluate(
            "document.querySelectorAll('section.note-item').length"
        )
        if current_count >= scroll_target:
            break
        if current_count == last_count:
            stale_rounds += 1
            if stale_rounds >= 3:
                break
        else:
            stale_rounds = 0
            last_count = current_count
        await page.evaluate("window.scrollBy(0, 1200)")
        await page.wait_for_timeout(1500)

    await page.wait_for_timeout(2000)

    # 提取卡片数据
    card_data = await page.evaluate(
        """() => {
            function parseCount(s) {
                if (!s) return -1;
                s = s.replace(',', '');
                if (s.includes('万')) return Math.round(parseFloat(s) * 10000);
                var n = parseInt(s, 10);
                return isNaN(n) ? -1 : n;
            }

            var cards = document.querySelectorAll('section.note-item');
            var results = [];
            for (var card of cards) {
                var coverLink = card.querySelector('a.cover');
                if (!coverLink) continue;
                var href = coverLink.getAttribute('href') || '';
                var fullUrl = href.startsWith('http') ? href : 'https://www.xiaohongshu.com' + href;
                var noteUrl = fullUrl;

                var titleEl = card.querySelector('.title span, .footer .title');
                var title = '';
                if (titleEl) {
                    var t = (titleEl.textContent || '').trim();
                    if (t.length > 2) title = t;
                }
                if (!title) {
                    var spans = card.querySelectorAll('span');
                    for (var span of spans) {
                        var t = (span.textContent || '').trim();
                        if (t.length > 4 && t.length < 100 && !span.closest('a[href*="/user/"]') && !span.closest('[class*="count"], [class*="like"], [class*="num"]')) {
                            if (t.length > title.length) title = t;
                        }
                    }
                }

                var nums = [];
                var likeEl = card.querySelector('.like-wrapper .count');
                if (likeEl) {
                    var n = parseCount((likeEl.textContent || '').trim());
                    if (n >= 0) nums.push(n);
                }
                if (nums.length === 0) {
                    var bottom = card.querySelector('.card-bottom-wrapper');
                    if (bottom) {
                        var clone = bottom.cloneNode(true);
                        var authorA = clone.querySelector('a[href*="/user/"]');
                        if (authorA) authorA.remove();
                        var text = clone.textContent || '';
                        var found = text.match(/\\d+/g);
                        if (found) {
                            for (var n of found) nums.push(parseInt(n, 10));
                        }
                    }
                }

                results.push({
                    title: title || '',
                    text: title || '',
                    author: '',
                    likes: nums.length > 0 ? nums[0] : -1,
                    collects: nums.length > 1 ? nums[1] : -1,
                    comments: nums.length > 2 ? nums[2] : -1,
                    reposts: 0,
                    url: fullUrl,
                    time: '',
                });
            }
            return results;
        }"""
    )

    # 去重
    seen_urls = set()
    results = []
    for item in card_data:
        u = item.get("url", "")
        if u and u not in seen_urls:
            seen_urls.add(u)
            results.append(item)
        if len(results) >= per_keyword:
            break

    return results


async def _fetch_xiaohongshu_detail(page, item: dict, max_comments: int) -> dict:
    """进入小红书笔记详情页，提取完整正文和评论列表。"""
    url = item.get("url", "")
    if not url:
        return {**item, "text": item.get("title", ""), "comments_list": []}

    try:
        # 在搜索结果页点击对应卡片，触发 SPA 内部导航
        note_id = url.rstrip('/').split('/')[-1].split('?')[0]
        selector = f'a.cover[href*="{note_id}"]'

        for attempt in range(3):  # 最多尝试 3 次（首次 + 2 次重试）
            try:
                # 点击卡片进入详情
                card = page.locator(selector).first
                await card.wait_for(state="visible", timeout=10000)
                await card.scroll_into_view_if_needed()
                await page.wait_for_timeout(500)
                await card.click(force=True, timeout=10000)
                try:
                    await page.wait_for_url("**/explore/**", timeout=15000)
                except Exception:
                    print("    详情页 SPA 导航可能未完成", file=sys.stderr)
            except Exception as e:
                print(f"    点击卡片进入详情失败，回退到 goto: {e}", file=sys.stderr)
                xsec_match = re.search(r'xsec_token=([^&]+)', url)
                if xsec_match:
                    explore_url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_match.group(1)}&xsec_source=pc_search"
                else:
                    explore_url = f"https://www.xiaohongshu.com/explore/{note_id}"
                await page.goto(explore_url, wait_until="domcontentloaded", timeout=20000)

            await page.wait_for_timeout(5000)
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            # 提取数据（包括正文和互动量）
            detail_data = await page.evaluate("""
            () => {
                var result = { likes: -1, collects: -1, comments: -1, note_text: '', _all_text: '' };

                function parseCount(s) {
                    if (!s) return -1;
                    s = s.replace(',', '');
                    if (s.includes('万')) return Math.round(parseFloat(s) * 10000);
                    var n = parseInt(s, 10);
                    return isNaN(n) ? -1 : n;
                }

                var all = document.documentElement.textContent || '';
                result._all_text = all;

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
                if (result.likes < 0 || result.collects < 0) {
                    var m;
                    if (result.likes < 0) { m = all.match(/赞[\\s\\S]{0,10}([\\d,]+)/); if (m) result.likes = parseCount(m[1]); }
                    if (result.collects < 0) { m = all.match(/收藏[\\s\\S]{0,10}([\\d,]+)/); if (m) result.collects = parseCount(m[1]); }
                }
                var candidates = document.querySelectorAll('.note-text');
                var best = '';
                for (var el of candidates) {
                    var t = (el.textContent || '').trim();
                    if (t.length > best.length) best = t;
                }
                result.note_text = best;
                result._has_container = container !== null;
                return result;
            }
            """)

            # 提取完了，检查结果里有没有广告屏蔽文字
            note_text = detail_data.get("note_text", "") or ""
            has_container = detail_data.get("_has_container", False)
            is_adblock_note = ("广告屏蔽插件" in note_text or "您的浏览器似乎" in note_text)
            # 如果 note_text 没有广告词但有内容，且页面有互动容器 → 正常
            if not is_adblock_note and note_text and has_container:
                break
            # 如果 note_text 明确有广告词 → 拦截
            if is_adblock_note:
                if attempt < 2:
                    print(f"    被反爬拦截（第{attempt+1}次），Escape 退回重试...", file=sys.stderr)
                    for _ in range(2):
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(500)
                    await page.wait_for_timeout(2000)
                else:
                    print(f"    重试后仍被反爬拦截，使用卡片数据", file=sys.stderr)
                    return {**item, "comments_list": []}
                continue
            # note_text 为空但也没互动容器 → 可能被屏蔽页面没加载出来
            if not note_text and not has_container:
                if attempt < 2:
                    print(f"    页面内容未加载（第{attempt+1}次），Escape 退回重试...", file=sys.stderr)
                    for _ in range(2):
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(500)
                    await page.wait_for_timeout(2000)
                else:
                    print(f"    页面内容仍未加载，使用卡片数据", file=sys.stderr)
                    return {**item, "comments_list": []}
                continue
            # 以上都不满足（有内容但没广告词，或只有部分加载）→ 正常返回
            break
        else:
            # for 循环自然结束（正常 break 没被执行）
            return {**item, "comments_list": []}

        # 提取评论（公用展开+提取函数）
        comments_list = []
        comment_images = 0
        if max_comments > 0 and detail_data.get("comments", 0) > 0:
            try:
                comments_list, comment_images = await xhs_expand_comments(page, max_comments)
            except Exception as e:
                print(f"    评论区加载异常: {e}", file=sys.stderr)

        return {
            **item,
            "text": detail_data.get("note_text", "") or item.get("title", ""),
            "likes": detail_data.get("likes", -1) if detail_data.get("likes", -1) >= 0 else item.get("likes", -1),
            "collects": detail_data.get("collects", -1) if detail_data.get("collects", -1) >= 0 else item.get("collects", -1),
            "comments": detail_data.get("comments", -1) if detail_data.get("comments", -1) >= 0 else item.get("comments", -1),
            "comments_list": comments_list,
            "comment_images": comment_images,
        }
    except Exception as e:
        print(f"    小红书详情页异常: {e}", file=sys.stderr)
        return {**item, "text": item.get("title", ""), "comments_list": []}


async def search_xiaohongshu(page, keyword: str, per_keyword: int, max_comments: int, sort_by: str = "likes", content_type: str = "all") -> list[dict]:
    """在小红书搜索关键词，总是进入详情页获取完整正文和评论。"""
    items = await _search_xiaohongshu(page, keyword, per_keyword, sort_by, content_type)

    print(f"    进入详情页获取完整正文和评论...", file=sys.stderr)
    for idx, item in enumerate(items):
        if idx > 0:
            await random_delay(3, 7, "小红书详情页间隔")
        enriched = await _fetch_xiaohongshu_detail(page, item, max_comments)
        items[idx] = enriched
        t = (enriched.get("text") or enriched.get("title", "") or "")[:24]
        lk = enriched.get("likes", "?")
        cl = enriched.get("collects", "?")
        cm = enriched.get("comments", "?")
        cc = f"({len(enriched.get('comments_list', []))}条评论)" if enriched.get("comments_list") else ""
        print(f"      [{idx+1}] {t}... 赞{lk} 收{cl} 评{cm}{cc}", file=sys.stderr)

        # 返回搜索结果页（Escape 关闭详情弹窗）
        if idx < len(items) - 1:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(2000)

    return items


# ---------- 主函数 ----------

async def search_keywords(
    keywords: list[str],
    platforms: list[str],
    per_keyword: int = 10,
    max_comments: int = 5,
    min_interaction: int = 0,
    sort_by: str = "likes",
    content_type: str = "all",
    headless: bool = False,
) -> dict:
    """多关键词多平台搜索。总是进入详情页提取完整正文和评论。
    Args:
        keywords: 搜索关键词列表
        platforms: 平台列表，可包含 "weibo" 和/或 "xiaohongshu"
        per_keyword: 每个关键词每个平台采集多少条结果
        max_comments: 每条内容最多采集评论数（默认 5）
        min_interaction: 互动量（点赞+收藏/转发）最低阈值，低于此值则跳过该关键词
        sort_by: 小红书筛选排序，"likes"=最多点赞/"comments"=最多评论
        content_type: 小红书内容类型，"all"=不限/"image_text"=仅图文
        headless: 是否无头模式
        headless: 是否无头模式

    Returns:
        符合输出格式的 dict
    """
    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    platform_results = []

    edge_user_data = get_edge_user_data()

    async with async_playwright() as p:
        context, page, _tmpdir = await launch_browser(
            p, headless=headless, user_data_dir=edge_user_data, label="keyword_search"
        )

        try:
            # ── 检测登录状态 ──
            await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            if "login" in page.url or "passport" in page.url:
                print("\n⚠️ 检测到未登录，请在浏览器窗口中完成登录", file=sys.stderr)
                await wait_for_login(page)

            for keyword in keywords:
                for platform_idx, platform in enumerate(platforms):
                    if len(platform_results) > 0:
                        # 跨域切换时清理页面状态（小红书→微博或反之）
                        if platform_idx > 0 and platforms[platform_idx - 1] != platform:
                            try:
                                await page.goto("about:blank", wait_until="commit", timeout=10000)
                                await page.wait_for_timeout(1000)
                            except Exception:
                                pass
                        await random_delay(5, 10, "切换关键词/平台")

                    print(f"[{platform}] 搜索关键词: {keyword}", file=sys.stderr)

                    if platform == "weibo":
                        items = await search_weibo(
                            page, keyword, per_keyword, max_comments
                        )
                    elif platform == "xiaohongshu":
                        items = await search_xiaohongshu(
                            page, keyword, per_keyword, max_comments, sort_by, content_type
                        )
                    else:
                        continue

                    # 将 comments_list 压平为纯文本 + 互动量筛选
                    clean_items = []
                    for item in items:
                        # 智搜回答 — 只保留原始字段，不加工
                        if item.get("author") == "智搜回答":
                            clean_items.append({
                                "title": item.get("title", ""),
                                "text": item.get("text", ""),
                                "author": "智搜回答",
                                "url": item.get("url", ""),
                            })
                            continue

                        raw_comments = item.get("comments_list", [])
                        comments_text = flatten_comments(raw_comments)
                        clean_item = {
                            "title": item.get("title", ""),
                            "text": item.get("text", ""),
                            "author": item.get("author", ""),
                            "likes": item.get("likes", -1) if isinstance(item.get("likes"), int) else -1,
                            "comments": item.get("comments", -1) if isinstance(item.get("comments"), int) else -1,
                            "collects": item.get("collects", 0) if isinstance(item.get("collects"), int) else 0,
                            "reposts": item.get("reposts", 0) if isinstance(item.get("reposts"), int) else 0,
                            "url": item.get("url", ""),
                            "time": item.get("time", ""),
                            "comments_text": comments_text,
                            "comment_images": item.get("comment_images", 0),
                        }
                        if min_interaction > 0:
                            likes = max(clean_item.get("likes", 0) or 0, 0)
                            collects = max(clean_item.get("collects", 0) or 0, 0)
                            reposts = max(clean_item.get("reposts", 0) or 0, 0)
                            total = likes + max(collects, reposts)
                            if total >= min_interaction:
                                clean_items.append(clean_item)
                            else:
                                print(f"    跳过: 互动量{total}<{min_interaction} - {(clean_item.get('text') or clean_item.get('title',''))[:40]}", file=sys.stderr)
                        else:
                            clean_items.append(clean_item)

                    if min_interaction > 0 and not clean_items:
                        print(f"  关键词[{keyword}]全部低于阈值({min_interaction})，不返回", file=sys.stderr)
                        continue

                    platform_results.append({
                        "platform": platform,
                        "keyword": keyword,
                        "total_items": len(clean_items),
                        "items": clean_items,
                    })
                    print(f"  完成：{len(clean_items)} 条", file=sys.stderr)

        finally:
            await context.close()

    return {
        "collected_at": collected_at,
        "keywords": keywords,
        "platforms": platform_results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="关键词采集工具 — 微博 & 小红书"
    )
    parser.add_argument(
        "--keywords", "-k", type=str, required=True,
        help="搜索关键词，多个用逗号分隔，如：元气森林,气泡水",
    )
    parser.add_argument(
        "--platforms", "-p", type=str, default="both",
        choices=["weibo", "xiaohongshu", "both"],
        help="搜索平台（默认 both）",
    )
    parser.add_argument(
        "--per-keyword", "-n", type=int, default=10,
        help="每个关键词每个平台采集结果数（默认 10）",
    )
    parser.add_argument(
        "--max-comments", type=int, default=30,
        help="每条内容最多采集评论数（默认 30）",
    )
    parser.add_argument(
        "--min-interaction", type=int, default=0,
        help="互动量（点赞+收藏/转发）最低阈值，低于此值则跳过该关键词（默认 0 不过滤）",
    )
    parser.add_argument(
        "--sort-by", type=str, default="likes", choices=["likes", "comments"],
        help="小红书筛选排序：likes=最多点赞/comments=最多评论（默认 likes）",
    )
    parser.add_argument(
        "--content-type", type=str, default="all", choices=["all", "image_text"],
        help="小红书内容类型：all=不限/image_text=仅图文（默认 all）",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="输出 JSON 文件路径（默认输出到 stdout）",
    )

    args = parser.parse_args()

    keyword_list = [kw.strip() for kw in args.keywords.split(",") if kw.strip()]

    if args.platforms == "both":
        platform_list = ["weibo", "xiaohongshu"]
    else:
        platform_list = [args.platforms]

    if not keyword_list:
        print("错误: 请提供至少一个关键词", file=sys.stderr)
        sys.exit(1)

    print(f"搜索关键词: {keyword_list}", file=sys.stderr)
    print(f"搜索平台: {platform_list}", file=sys.stderr)
    print(f"每关键词每平台采集 {args.per_keyword} 条", file=sys.stderr)
    print(f"最大评论数: {args.max_comments}", file=sys.stderr)
    print(f"小红书排序: {args.sort_by}, 内容类型: {args.content_type}", file=sys.stderr)
    if args.min_interaction > 0:
        print(f"互动量阈值: {args.min_interaction}", file=sys.stderr)
    print(file=sys.stderr)

    result = asyncio.run(search_keywords(
        keywords=keyword_list,
        platforms=platform_list,
        per_keyword=args.per_keyword,
        max_comments=args.max_comments,
        min_interaction=args.min_interaction,
        sort_by=args.sort_by,
        content_type=args.content_type,
        headless=False,
    ))

    write_output(result, args.output)


if __name__ == "__main__":
    main()
