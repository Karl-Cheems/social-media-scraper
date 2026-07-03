"""点击筛选按钮看弹出面板"""
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

        # 点击"筛选"按钮
        clicked = await page.evaluate("""
            () => {
                var btn = document.querySelector('.filter, [class*=filter], button:has-text("筛选"), a:has-text("筛选")');
                if (btn) {
                    btn.click();
                    return 'clicked';
                }
                // 用文本查找
                var all = document.querySelectorAll('a, button, span, div');
                for (var el of all) {
                    if ((el.textContent || '').trim() === '筛选') {
                        el.click();
                        return 'clicked by text: ' + el.className;
                    }
                }
                return 'not found';
            }
        """)
        print(f"点击筛选: {clicked}")
        await page.wait_for_timeout(2000)

        # 看看弹出啥了
        popup = await page.evaluate("""
            () => {
                var panels = document.querySelectorAll('[class*=popup], [class*=panel], [class*=dialog], [class*=modal], [class*=overlay], [class*=drawer], [class*=menu]');
                var r = [];
                for (var el of panels) {
                    var c = '';
                    if (el.className && typeof el.className === 'string') c = el.className.substring(0, 60);
                    var t = (el.textContent || '').trim().substring(0, 1000);
                    if (t) r.push({cls: c, text: t});
                }
                return r;
            }
        """)
        print(f"\n弹出面板 ({len(popup)}):")
        for p in popup:
            print(f"  cls=[{p['cls']}]")
            print(f"  text=[{p['text']}]")
            print()

        # 也截个屏
        await page.screenshot(path="D:/Users/Desktop/网络热点搜集/xhs_filter_panel.png")

asyncio.run(main())
