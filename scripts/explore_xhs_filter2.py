"""探索小红书搜索结果筛选栏 2"""
import asyncio, sys
sys.path.insert(0, "D:/Users/Desktop/网络热点搜集/scripts")
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from common import launch_browser, get_edge_user_data

async def main():
    data = get_edge_user_data()
    async with async_playwright() as p:
        c, page = await launch_browser(p, headless=False, user_data_dir=data, label="e")
        await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        # 搜索
        si = page.locator("#search-input").first
        if await si.count() == 0:
            si = page.locator("input").first
        await si.wait_for(state="visible", timeout=10000)
        await si.focus()
        await page.keyboard.press("Control+a")
        await page.keyboard.press("Delete")
        await page.keyboard.type("聚会", delay=60)
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(5000)

        # 截取页面文本中所有包含筛选词的行
        text = await page.evaluate('document.body.innerText')
        for line in text.split(chr(10)):
            l = line.strip()
            if any(k in l for k in ['一周', '周内', '排序', '点赞', '最热', '最新', '筛选', '笔记', '视频', '综合']):
                print(f"[{l[:80]}]")

        # 截图
        await page.screenshot(path="D:/Users/Desktop/网络热点搜集/xhs_search.png")
        print("\n截图已保存")
        input("\n按 Enter 继续...")

asyncio.run(main())
