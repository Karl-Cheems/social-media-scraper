"""在s.weibo.com搜索页找智搜栏目"""
import asyncio, sys
sys.path.insert(0, "D:/Users/Desktop/网络热点搜集/scripts")
from playwright.async_api import async_playwright
from common import launch_browser, get_edge_user_data

async def main():
    data = get_edge_user_data()
    async with async_playwright() as p:
        c, page = await launch_browser(p, headless=True, user_data_dir=data, label="find")
        # 直接进话题搜索页
        await page.goto("https://s.weibo.com/weibo?q=花少8北京开录&xsort=hot", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)
        print("URL:", page.url)

        # 找所有标签/导航栏
        tabs = await page.evaluate("""
            () => {
                var items = document.querySelectorAll('a, [class*=tab], [class*=nav], [class*=type], [class*=filter], li, [class*=menu]');
                var r = [], seen = new Set();
                for (var el of items) {
                    var t = (el.textContent || '').trim();
                    var h = (el.href || '') + (el.getAttribute('action-data') || '');
                    if (t && t.length < 15 && !seen.has(t)) {
                        seen.add(t);
                        r.push({text: t, href: h.substring(0, 100), cls: (el.className+'').substring(0, 40)});
                    }
                }
                return r;
            }
        """)
        print(f"\n所有导航/标签项 ({len(tabs)}):")
        for t in tabs:
            print(f"  [{t['text']}] href={t['href'][:60]}")

        # 搜"智"字
        searches = await page.evaluate("""
            () => {
                var all = document.body.innerText || '';
                var lines = all.split(String.fromCharCode(10));
                return lines.filter(l => l.indexOf('智') >= 0 || l.indexOf('AI') >= 0);
            }
        """)
        print(f"\n含'智'/'AI'的行: {searches[:20]}")

        # 搜aisearch链接
        ai_links = await page.evaluate("""
            () => {
                var links = document.querySelectorAll('a');
                var r = [];
                for (var l of links) {
                    var h = (l.href || '').toLowerCase();
                    if (h.indexOf('aisearch') >= 0) {
                        r.push({text: (l.textContent || '').trim(), href: l.href});
                    }
                }
                return r;
            }
        """)
        print(f"\naisearch链接: {ai_links}")

asyncio.run(main())
