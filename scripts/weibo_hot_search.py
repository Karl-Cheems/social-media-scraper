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
# ── 路径修补 ──
_scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from pydantic import BaseModel, Field
from playwright.async_api import async_playwright
from common import kill_edge, launch_browser, get_edge_user_data, write_output, random_delay, wait_for_login


class ZhishouAnswer(BaseModel):
    """智搜回答"""
    text: str = Field(description="智搜回答正文")
    expanded: str = Field(default="", description="点击「查看更多」后展开的补充内容")
    source_url: str = Field(default="", description="aisearch 页面 URL")


class TopicDetail(BaseModel):
    """热搜/文娱话题详情"""
    rank: int = Field(description="排名")
    title: str = Field(description="热搜词")
    hot_value: str = Field(description="热度标识（热/爆/沸/新/荐等）")
    topic_url: str = Field(description="话题搜索链接")
    board: str = Field(default="hot", description="hot | entertainment")
    zhishou_answer: ZhishouAnswer | None = Field(default=None, description="智搜回答，可能没有")


HOT_SEARCH_URL = "https://weibo.com/hot/search"


async def scrape_hot_search(
    limit: int = 10,
    board: str = "hot",
    headless: bool = False,
) -> list[TopicDetail]:
    """采集微博热搜榜/文娱榜，及各话题下的智搜回答。"""
    results = []
    edge_user_data = get_edge_user_data()

    async with async_playwright() as p:
        context, page, _tmpdir = await launch_browser(p, headless=headless, user_data_dir=edge_user_data, label="weibo_hot")

        try:
            # 第一阶段：获取榜单
            BOARD_URLS = {
                "hot": "https://weibo.com/hot/search",
                "entertainment": "https://weibo.com/hot/entertainment",
            }
            entry_url = BOARD_URLS.get(board, BOARD_URLS["hot"])
            board_name = "热搜榜" if board == "hot" else "文娱榜"
            print(f"正在打开微博{board_name}: {entry_url}", file=sys.stderr)
            await page.goto(entry_url, wait_until="domcontentloaded", timeout=30000)
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
                        // 跳过置顶（rankText 非纯数字，如"置顶""推荐"）
                        if (rankText && !/^\d+$/.test(rankText)) continue;
                        // 没有 rank 元素且文本不以数字开头 → 置顶/推荐位，跳过
                        if (!rankEl && !/^\d/.test(txt)) continue;
                        var rank = parseInt(rankText, 10);
                        if (isNaN(rank) || rank < 1 || rank > 100) {
                            // 备选：从文本开头提取数字
                            var m = txt.match(/^(\\d+)/);
                            if (m) {
                                rank = parseInt(m[1], 10);
                            } else {
                                // 兜底：用 DOM 顺序索引
                                rank = i + 1;
                            }
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
                if idx > 0:
                    await random_delay(3, 6, "热搜话题间隔")
                try:
                    topic = await _fetch_topic_detail(
                        page, item, board=board
                    )
                    if topic:
                        results.append(topic)
                    has_answer = "🤖有" if topic and topic.zhishou_answer else "无智搜"
                    print(f"  [{idx+1}/{limit}] #{item['rank']} {item['title']}: {has_answer}", file=sys.stderr)
                except Exception as e:
                    print(f"  [{idx+1}/{limit}] #{item['rank']} {item['title']}: 获取失败 - {e}", file=sys.stderr)

        finally:
            await context.close()

    return results


async def _fetch_topic_detail(
    page, item: dict, board: str = "hot",
) -> TopicDetail | None:
    """直接构造 aisearch URL 获取智搜回答。"""
    title = item.get("title", "")
    rank = item.get("rank", 0)
    hot = item.get("hot", "")
    topic_url = item.get("url", "")

    # 直接构造 aisearch URL
    aisearch_url = f"https://s.weibo.com/aisearch?q={title}&Refer=weibo_aisearch"

    zhishou_answer = None
    try:
        zhishou_answer = await _fetch_zhishou_detail(page, aisearch_url)
        if zhishou_answer and zhishou_answer.text:
            print(f"    ✅ 智搜回答 {len(zhishou_answer.text)} 字符", file=sys.stderr)
        else:
            print(f"    智搜回答为空", file=sys.stderr)
            zhishou_answer = None
    except Exception as e:
        print(f"    智搜回答采集失败: {e}", file=sys.stderr)

    return TopicDetail(
        rank=rank,
        title=title,
        hot_value=hot,
        topic_url=topic_url,
        board=board,
        zhishou_answer=zhishou_answer,
    )


async def _fetch_zhishou_detail(page, aisearch_url: str) -> ZhishouAnswer | None:
    """进入 aisearch 页面，提取智搜回答正文，尝试展开查看更多。"""
    await page.goto(aisearch_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)

    # 提取回答正文：只从主内容区域提取，排除右侧榜单侧边栏
    text = await page.evaluate("""
        () => {
            // 只取主内容区域，排除右侧热搜榜侧边栏
            var mainEl = document.querySelector('#pl_feedlist_index') || document.querySelector('.main-full');
            if (!mainEl) return '';
            var all = mainEl.innerText || '';
            var lines = all.split(String.fromCharCode(10));
            var skip = new Set(['NEW', '综合', '用户', '实时', '视频', '图片', '关注', '超话',
                '高级搜索', '搜索结果', '更多', '刷新', '我的', '微博热搜', '热搜榜', '文娱榜',
                '首页', '推荐', '话题']);
            // 遇到这些标记立即终止
            var stopMarkers = ['信源追溯', '风险提示', '查看完整热搜榜单', '创作者中心', '帮助中心',
                '关于微博', 'Copyright', '客服', '数据中心'];
            var clean = [];
            var inAnswer = false;

            for (var i = 0; i < lines.length; i++) {
                var l = lines[i].trim();
                if (!l) continue;

                if (l === '回答' || l === '深度思考') {
                    inAnswer = true;
                    continue;
                }
                var shouldStop = false;
                for (var s = 0; s < stopMarkers.length; s++) {
                    if (l.indexOf(stopMarkers[s]) >= 0) { shouldStop = true; break; }
                }
                if (shouldStop) break;
                if (skip.has(l)) continue;
                if (inAnswer && l.length > 3) clean.push(l);
            }

            // 兜底：取所有大段文字
            if (clean.length < 3) {
                clean = [];
                for (var i = 0; i < lines.length; i++) {
                    var l = lines[i].trim();
                    if (!l || skip.has(l)) continue;
                    var shouldStop = false;
                    for (var s = 0; s < stopMarkers.length; s++) {
                        if (l.indexOf(stopMarkers[s]) >= 0) { shouldStop = true; break; }
                    }
                    if (shouldStop) break;
                    if (l.length > 30) clean.push(l);
                }
            }

            return clean.join(String.fromCharCode(10));
        }
    """)

    # 尝试点击"查看更多"
    expanded = ""
    try:
        more_clicked = await page.evaluate("""
            () => {
                var links = document.querySelectorAll('a');
                for (var link of links) {
                    if ((link.textContent || '').indexOf('查看更多') >= 0) {
                        link.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        if more_clicked:
            await page.wait_for_timeout(2000)
            expanded = await page.evaluate("""
                () => {
                    var mainEl = document.querySelector('#pl_feedlist_index') || document.querySelector('.main-full');
                    if (!mainEl) return '';
                    var all = mainEl.innerText || '';
                    var lines = all.split(String.fromCharCode(10));
                    var stopMarkers = ['创作者中心',
                        '帮助中心', '关于微博', 'Copyright', '客服', '数据中心'];
                    var clean = [];
                    for (var i = 0; i < lines.length; i++) {
                        var l = lines[i].trim();
                        if (!l) continue;
                        var shouldStop = false;
                        for (var s = 0; s < stopMarkers.length; s++) {
                            if (l.indexOf(stopMarkers[s]) >= 0) { shouldStop = true; break; }
                        }
                        if (shouldStop) break;
                        if (l.length > 10) clean.push(l);
                    }
                    return clean.join(String.fromCharCode(10));
                }
            """)
            if expanded == text:
                expanded = ""
    except Exception:
        pass

    if not text:
        return None

    return ZhishouAnswer(
        text=text[:5000],
        expanded=expanded[:5000] if expanded else "",
        source_url=aisearch_url,
    )


def main():
    parser = argparse.ArgumentParser(
        description="微博热搜/文娱监控工具 - 采集榜单及智搜回答"
    )
    parser.add_argument("--limit", type=int, default=10, help="采集数量上限（默认 10）")
    parser.add_argument("--board", default="hot",
                        choices=["hot", "entertainment", "both"],
                        help="榜单类型: hot=热搜, entertainment=文娱, both=两者（默认 hot）")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径")

    args = parser.parse_args()

    if args.board == "both":
        results = []
        for b in ("hot", "entertainment"):
            batch = asyncio.run(scrape_hot_search(
                limit=args.limit,
                board=b,
                headless=False,
            ))
            for t in batch:
                t.board = b
            results.extend(batch)
            if b == "hot":
                import time
                time.sleep(random.uniform(5, 10))
    else:
        results = asyncio.run(scrape_hot_search(
            limit=args.limit,
            board=args.board,
            headless=False,
        ))

    from datetime import datetime
    output = {
        "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "weibo_hot_search",
        "total_topics": len(results),
        "topics": [r.model_dump(mode="json") for r in results],
    }

    write_output(output, args.output)


if __name__ == "__main__":
    main()
