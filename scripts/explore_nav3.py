"""
探索微博热搜页 - 搜索智搜相关文本
"""
import asyncio, sys
sys.path.insert(0, "D:/Users/Desktop/网络热点搜集/scripts")
from common import launch_browser, get_edge_user_data
from playwright.async_api import async_playwright

async def explore():
    data = get_edge_user_data()
    async with async_playwright() as p:
        c, page = await launch_browser(p, headless=True, user_data_dir=data, label="explore")
        await page.goto("https://weibo.com/hot/search", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(6000)

        # 获取整个页面文本，找智搜相关
        text = await page.evaluate("document.body.innerText")
        for line in text.split('\n'):
            l = line.strip()
            if not l: continue
            if '智搜' in l or 'AI' in l or 'ai' in l.lower() and len(l) < 30:
                print(f"  [{l}]")

        # 找左侧导航列表
        nav_items = await page.evaluate("""
            () => {
                var side = document.querySelector('._side_1ubn9_37');
                if (!side) return 'no side found';
                return side.innerText;
            }
        """)
        print(f"\n=== 左侧导航文本 ===\n{nav_items}")

        # 截图保存检查
        await page.screenshot(path="D:/Users/Desktop/网络热点搜集/hot_page_debug.png")
        print("\n截图已保存")

asyncio.run(explore())
