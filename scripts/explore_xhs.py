"""探索小红书搜索框现状"""
import asyncio, sys
sys.path.insert(0, "D:/Users/Desktop/网络热点搜集/scripts")
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from common import launch_browser, get_edge_user_data

async def main():
    data = get_edge_user_data()
    async with async_playwright() as p:
        c, page = await launch_browser(p, headless=False, user_data_dir=data, label="xhs")
        await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)
        print(f"URL: {page.url}")

        # 看看搜索框情况
        info = await page.evaluate("""
            () => {
                var si = document.querySelector('#search-input');
                if (!si) return {found: false};
                var rect = si.getBoundingClientRect();
                var style = window.getComputedStyle(si);
                return {
                    found: true,
                    tag: si.tagName,
                    type: si.type,
                    visible: si.offsetParent !== null,
                    rect: {top: rect.top, left: rect.left, w: rect.width, h: rect.height},
                    display: style.display,
                    visibility: style.visibility,
                    opacity: style.opacity,
                    placeholder: si.placeholder,
                    class: si.className,
                    parentCount: si.closest('[class*=search],[class*=header]') ? 1 : 0
                };
            }
        """)
        print(f"搜索框: {info}")

        # 找所有 input/textarea
        inputs = await page.evaluate("""
            () => {
                var all = document.querySelectorAll('input, textarea');
                return Array.from(all).slice(0, 10).map(el => ({
                    id: el.id,
                    placeholder: el.placeholder,
                    visible: el.offsetParent !== null,
                    tag: el.tagName,
                    type: el.type || '',
                    rect: el.getBoundingClientRect().top.toFixed(0) + 'px'
                }));
            }
        """)
        print(f"所有输入框:")
        for inp in inputs:
            print(f"  id={inp['id']} placeholder={inp['placeholder']} visible={inp['visible']} tag={inp['tag']} top={inp['rect']}")

        # 截屏看结构
        await page.screenshot(path="D:/Users/Desktop/网络热点搜集/xhs_explore.png")
        print("截图已保存")

        await asyncio.sleep(600)

asyncio.run(main())
