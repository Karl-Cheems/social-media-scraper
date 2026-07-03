"""
探索微博热搜页左侧导航栏结构
"""
import asyncio, sys, json
sys.path.insert(0, "D:/Users/Desktop/网络热点搜集/scripts")
from common import launch_browser, get_edge_user_data
from playwright.async_api import async_playwright

async def explore():
    data = get_edge_user_data()
    async with async_playwright() as p:
        c, page = await launch_browser(p, headless=False, user_data_dir=data, label="explore")
        await page.goto("https://weibo.com/hot/search", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(6000)
        print("URL:", page.url)

        # 获取页面所有链接的文本和 href
        links = await page.evaluate("""
            () => {
                var items = document.querySelectorAll('a, [class*=tab], [class*=nav], [class*=side], [class*=menu]');
                var r = [];
                for (var el of items) {
                    var t = (el.textContent || '').trim().substring(0, 50);
                    var h = el.href || '';
                    var c = el.className || '';
                    if (t || h) r.push({text: t, href: h, cls: c.substring(0, 60)});
                }
                // 去重
                var seen = new Set();
                return r.filter(x => {
                    var k = x.text + x.href;
                    return seen.has(k) ? false : (seen.add(k), true);
                });
            }
        """)
        print(f"\n=== 共 {len(links)} 个链接/导航 ===")
        for l in links:
            print(f"  text=[{l['text']}]  href=[{l['href'][:80]}]  cls=[{l['cls'][:50]}]")

        # 截图
        await page.screenshot(path="D:/Users/Desktop/网络热点搜集/hot_page.png", full_page=True)
        print("\n截图已保存")

        await asyncio.sleep(300)

asyncio.run(explore())
