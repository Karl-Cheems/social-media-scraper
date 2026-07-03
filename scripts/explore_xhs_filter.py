"""
探索小红书的搜索结果筛选栏
"""
import asyncio, sys
sys.path.insert(0, "D:/Users/Desktop/网络热点搜集/scripts")
sys.stdout.reconfigure(encoding="utf-8")
import sys
from playwright.async_api import async_playwright
from common import launch_browser, get_edge_user_data

async def main():
    data = get_edge_user_data()
    async with async_playwright() as p:
        c, page = await launch_browser(p, headless=False, user_data_dir=data, label="e")
        await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # 搜索
        search_input = page.locator("#search-input").first
        if await search_input.count() == 0:
            search_input = page.locator("input").first
        await search_input.wait_for(state="visible", timeout=10000)
        await search_input.focus()
        await page.keyboard.press("Control+a")
        await page.keyboard.press("Delete")
        await page.keyboard.type("聚会", delay=60)
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(3000)

        # 看看筛选栏有啥
        filter_html = await page.evaluate("""
            () => {
                // 找筛选按钮/栏
                var filters = document.querySelectorAll('[class*=filter], [class*=sort], [class*=search-filter], [class*=search_sort], [class*=search-option]');
                var r = [];
                for (var el of filters) {
                    r.push({cls: el.className.substring(0, 60), html: el.innerHTML.substring(0, 800)});
                }
                return r;
            }
        """)
        print(f"筛选栏 ({len(filter_html)}):")
        for f in filter_html:
            print(f"  [{f['cls']}]\n  {f['html']}\n")

        # 所有含"一周"的文本
        text = await page.evaluate('document.body.innerText')
        for line in text.split(chr(10)):
            if '一周' in line or '周内' in line or '点赞' in line or '最热' in line or '最新' in line:
                print(f"  filter: [{line.strip()[:60]}]")

        input("\n按 Enter 继续...")

asyncio.run(main())
