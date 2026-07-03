"""
探索微博热搜页左侧导航栏 - 无头模式
"""
import asyncio, sys, json
sys.path.insert(0, "D:/Users/Desktop/网络热点搜集/scripts")
from common import launch_browser, get_edge_user_data
from playwright.async_api import async_playwright

async def explore():
    data = get_edge_user_data()
    async with async_playwright() as p:
        c, page = await launch_browser(p, headless=True, user_data_dir=data, label="explore")
        await page.goto("https://weibo.com/hot/search", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(6000)

        # 获取页面所有a标签的文本和href
        links = await page.evaluate("""
            () => {
                var items = document.querySelectorAll('a, [class*=tab], [class*=nav], [class*=side]');
                var r = [];
                var seen = new Set();
                for (var el of items) {
                    var t = (el.textContent || '').trim().substring(0, 60);
                    var h = el.href || '';
                    var c = el.className || '';
                    var k = t + h;
                    if ((t || h) && !seen.has(k)) {
                        seen.add(k);
                        r.push({text: t, href: h.substring(0, 120), cls: c.substring(0, 60)});
                    }
                }
                return r;
            }
        """)
        print(f"\n=== 共 {len(links)} 个链接/导航 ===")
        for l in links:
            if '智搜' in l['text'] or '智搜' in l['href'] or 'aisearch' in l['href']:
                print(f"  ★ 智搜: text=[{l['text']}]  href=[{l['href']}]  cls=[{l['cls']}]")

        # 也搜一下"ai"或"Ai"的链接
        for l in links:
            t = l['text'].lower()
            h = l['href'].lower()
            if ('ai' in t or 'ai' in h or '搜索' in t or '搜' in t):
                print(f"  候选: text=[{l['text']}]  href=[{l['href'][:80]}]")

        # 找左侧栏
        sidebar = await page.evaluate("""
            () => {
                var els = document.querySelectorAll('[class*=side], [class*=left], [class*=nav], [class*=menu]');
                var r = [];
                for (var el of els) {
                    var html = el.innerHTML.substring(0, 500);
                    var cls = el.className.substring(0, 60);
                    if (html.length > 50) r.push({cls: cls, html: html});
                }
                return r;
            }
        """)
        print(f"\n=== 侧边栏 ({len(sidebar)} 个) ===")
        for s in sidebar:
            print(f"  cls=[{s['cls']}]")
            print(f"  html=[{s['html'][:400]}]")
            print()

asyncio.run(explore())
