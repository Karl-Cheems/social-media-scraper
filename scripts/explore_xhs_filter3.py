"""小红书搜索结果筛选 - 无头自动探索"""
import asyncio, sys
sys.path.insert(0, "D:/Users/Desktop/网络热点搜集/scripts")
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from common import launch_browser, get_edge_user_data

async def main():
    data = get_edge_user_data()
    async with async_playwright() as p:
        c, page = await launch_browser(p, headless=True, user_data_dir=data, label="e")
        await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
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

        # 所有可见的按钮/链接
        btns = await page.evaluate("""
            () => {
                var items = document.querySelectorAll('a, button, [class*=tab], [class*=filter], [class*=sort], [role=button]');
                var r = [];
                for (var el of items) {
                    var t = (el.textContent || '').trim();
                    var c = '';
                    if (el.className && typeof el.className === 'string') c = el.className.substring(0, 40);
                    if (t && t.length < 20) r.push({text: t, cls: c});
                }
                return r;
            }
        """)
        print("所有按钮/标签:")
        for b in btns:
            print(f"  [{b['text']}] cls={b['cls']}")

        # 找筛选区域
        filter_area = await page.evaluate("""
            () => {
                var els = document.querySelectorAll('[class*=sort], [class*=filter], [class*=search-option], [class*=tab]');
                var r = [];
                for (var el of els) {
                    var c = '';
                    if (el.className && typeof el.className === 'string') c = el.className.substring(0, 60);
                    var t = (el.textContent || '').trim().substring(0, 500);
                    if (t) r.push({cls: c, text: t});
                }
                return r;
            }
        """)
        print(f"\n筛选/排序区域 ({len(filter_area)}):")
        for f in filter_area:
            print(f"  cls=[{f['cls']}] text=[{f['text']}]")

        # 所有含"一周"的文字
        body = await page.evaluate('document.body.innerText')
        lines = [l.strip() for l in body.split(chr(10)) if '一周' in l or '周' in l or '三天' in l or '半年' in l]
        print(f"\n时间筛选选项:")
        for l in lines[:15]:
            print(f"  [{l[:60]}]")

asyncio.run(main())
