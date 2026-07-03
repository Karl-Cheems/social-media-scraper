"""探索热搜页左侧导航完整列表"""
import asyncio, sys
sys.path.insert(0, "D:/Users/Desktop/网络热点搜集/scripts")
from common import launch_browser, get_edge_user_data
from playwright.async_api import async_playwright

async def explore():
    data = get_edge_user_data()
    async with async_playwright() as p:
        c, page = await launch_browser(p, headless=True, user_data_dir=data, label="explore")
        await page.goto("https://weibo.com/hot/search", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)
        print("URL:", page.url)

        # 左侧导航所有文字
        nav_text = await page.evaluate("""
            () => {
                var side = document.querySelector('._side_1ubn9_37');
                if (!side) return 'NO_SIDE';
                var items = side.querySelectorAll('a, span, div');
                var seen = new Set();
                var r = [];
                for (var el of items) {
                    var t = (el.textContent || '').trim();
                    if (t && t.length < 30 && !seen.has(t)) {
                        seen.add(t);
                        r.push({text: t, href: (el.href || '').substring(0, 100), tag: el.tagName});
                    }
                }
                return r;
            }
        """)
        print(f"\n左侧导航 ({len(nav_text)} 项):")
        for n in nav_text:
            print(f"  [{n['tag']}] text={n['text']}  href={n['href']}")

        # 尝试找aisearch或AI搜索
        all_links = await page.evaluate("""
            () => {
                var links = document.querySelectorAll('a');
                var r = [];
                for (var l of links) {
                    var h = (l.href || '').toLowerCase();
                    var t = (l.textContent || '').trim();
                    if (h.indexOf('aisearch') >= 0 || h.indexOf('ais') >= 0 || t.indexOf('AI') >= 0 || t.indexOf('智能') >= 0) {
                        r.push({text: t, href: l.href});
                    }
                }
                return r;
            }
        """)
        print(f"\nAI/智搜链接 ({len(all_links)}):")
        for l in all_links:
            print(f"  text=[{l['text']}]  href=[{l['href']}]")

        # 全页文本搜索"智搜"
        body = await page.evaluate("document.body.innerText")
        lines = [l.strip() for l in body.split('\n') if '智搜' in l or 'AI搜索' in l]
        print(f"\n含'智搜'的文本行: {lines[:10] if lines else '无'}")

asyncio.run(explore())
