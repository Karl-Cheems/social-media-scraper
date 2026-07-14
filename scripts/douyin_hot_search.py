"""
抖音热搜监控脚本
使用 Playwright + Edge 浏览器，采集抖音热搜榜单

用法：
    python douyin_hot_search.py
    python douyin_hot_search.py --limit 10
    python douyin_hot_search.py --limit 20 -o result.json
"""

import argparse
import asyncio
import json
import os
import re
import sys
# ── 路径修补：PyInstaller exe 内子进程需要找到 common.py ──
_scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from pydantic import BaseModel, Field
from playwright.async_api import async_playwright
from common import kill_edge, launch_browser, get_edge_user_data, write_output, random_delay


class HotItem(BaseModel):
    """单条热搜"""
    rank: int = Field(description="排名")
    title: str = Field(description="热搜词")
    hot_value: str = Field(description="热度值，如 1210.6万")
    hot_badge: str = Field(default="", description="热/爆/沸/新 标识（如有）")
    detail_url: str = Field(default="", description="话题详情页链接")


HOT_SEARCH_URL = "https://www.douyin.com/hot"


async def scrape_hot_search(
    limit: int = 10,
    headless: bool = False,
) -> list[HotItem]:
    """采集抖音热搜榜单。"""
    edge_user_data = get_edge_user_data()

    async with async_playwright() as p:
        context, page, _tmpdir = await launch_browser(p, headless=False, user_data_dir=edge_user_data, label="douyin")

        try:
            print(f"正在打开热搜榜: {HOT_SEARCH_URL}", file=sys.stderr)
            await page.goto(HOT_SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # 抖音页面是 CSR（客户端渲染），等待热榜列表出现
            # 新版：ul.tUZ3t9oh > li.xqnrQ8ZV
            await page.wait_for_selector("ul.tUZ3t9oh", timeout=15000)

            # 滚动到底确保全部加载
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)

            # 提取热搜列表
            hot_items = await page.evaluate("""
                () => {
                    var ul = document.querySelector('ul.tUZ3t9oh');
                    if (!ul) return [];
                    var items = ul.querySelectorAll(':scope > li.xqnrQ8ZV');
                    var results = [];

                    for (var i = 0; i < items.length; i++) {
                        var li = items[i];
                        var rank = i + 1;

                        // 标题（在 .OQtNjDJ9 > a.RZuwF26I 里）
                        var title = '';
                        var titleLink = li.querySelector('.OQtNjDJ9 a.RZuwF26I');
                        if (titleLink) {
                            title = (titleLink.textContent || '').trim();
                        }
                        if (!title) continue;

                        // 热度值（在 span.ZZFBf5Wm 里）
                        var hotValue = '';
                        var hotSpan = li.querySelector('span.ZZFBf5Wm');
                        if (hotSpan) {
                            hotValue = (hotSpan.textContent || '').trim();
                        }

                        // 话题链接
                        var detailUrl = '';
                        if (titleLink) {
                            var href = titleLink.getAttribute('href') || '';
                            if (href) {
                                detailUrl = href.startsWith('http') ? href : 'https://www.douyin.com' + href;
                            }
                        }

                        // 热度 badge（前3有特殊图标）
                        var badge = '';
                        var img = li.querySelector('._Q3ByIgH img');
                        if (img) {
                            var src = img.getAttribute('src') || '';
                            if (src.indexOf('hot_top') >= 0) badge = '🔥';
                            else if (src.indexOf('hot_new') >= 0) badge = '新';
                            else if (src.indexOf('hot_boom') >= 0) badge = '爆';
                        }

                        results.push({
                            rank: rank,
                            title: title,
                            hot_value: hotValue,
                            hot_badge: badge,
                            detail_url: detailUrl,
                        });
                    }

                    return results;
                }
            """)

            # 按序号排序
            hot_items.sort(key=lambda x: x.get("rank", 0))
            show_list = hot_items[:limit]

            if not show_list:
                print("  未解析到热搜数据，请检查页面结构", file=sys.stderr)
                return []

            print(f"获取到 {len(show_list)} 条热搜（取前 {limit} 条）", file=sys.stderr)
            for item in show_list:
                badge = item.get("hot_badge", "") or ""
                print(f"  #{item['rank']} {item['title']} [{item['hot_value']}] {badge}", file=sys.stderr)

            results = [HotItem(**item) for item in show_list]

        finally:
            await context.close()

    return results


def main():
    parser = argparse.ArgumentParser(
        description="抖音热搜监控工具 - 采集抖音热搜榜单"
    )
    parser.add_argument("--limit", type=int, default=10, help="采集热搜数量上限（默认 10）")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径")

    args = parser.parse_args()

    results = asyncio.run(scrape_hot_search(
        limit=args.limit,
        headless=False,
    ))

    from datetime import datetime
    output = {
        "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_topics": len(results),
        "topics": [r.model_dump(mode="json") for r in results],
    }

    write_output(output, args.output)


if __name__ == "__main__":
    main()
