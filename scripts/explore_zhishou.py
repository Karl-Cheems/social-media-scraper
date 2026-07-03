"""
快速探索：微博热搜页左侧"智搜"栏目的 DOM 结构
"""
import asyncio, sys, json
sys.path.insert(0, "D:/Users/Desktop/网络热点搜集/scripts")
from common import launch_browser, get_edge_user_data, wait_for_login
from playwright.async_api import async_playwright

async def explore():
    edge_user_data = get_edge_user_data()
    async with async_playwright() as p:
        context, page = await launch_browser(p, headless=False, user_data_dir=edge_user_data, label="explore")
        await page.goto("https://weibo.com/hot/search", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)

        # 1. 获取左侧导航栏的 HTML 片段
        nav_html = await page.evaluate("""
            () => {
                // 找左侧导航区域
                var side = document.querySelector('[class*=_side_], [class*=sidebar], [class*=left], [class*=nav_]');
                if (!side) {
                    // 尝试找所有可能包含"智搜"的链接
                    var links = document.querySelectorAll('a');
                    var results = [];
                    for (var l of links) {
                        if ((l.textContent || '').indexOf('智搜') >= 0) {
                            results.push({
                                text: l.textContent.trim(),
                                href: l.getAttribute('href') || '',
                                class: l.className,
                                outer: l.outerHTML.substring(0, 200),
                            });
                        }
                    }
                    return JSON.stringify({nav_not_found: true, zhishou_links: results});
                }
                return side.innerHTML.substring(0, 3000);
            }
        """)
        print("=== 左侧导航 / 智搜链接 ===")
        print(nav_html[:2000])
        print()

        # 2. 截图全页看布局
        await page.screenshot(path="D:/Users/Desktop/网络热点搜集/hot_page.png", full_page=True)
        print("截图保存到 hot_page.png")

        # 3. 尝试获取页面完整文本找"智搜"位置
        body_text = await page.evaluate("document.body.innerText")
        lines = [l.strip() for l in body_text.split('\n') if l.strip()]
        zhishou_lines = [l for l in lines if '智搜' in l]
        print(f"\n=== 包含"智搜"的文本行 ({len(zhishou_lines)} 条) ===")
        for l in zhishou_lines[:20]:
            print(f"  {l[:100]}")

        input("\n按 Enter 继续...")

        # 4. 尝试点击"智搜"链接
        clicked = await page.evaluate("""
            () => {
                var links = document.querySelectorAll('a');
                for (var l of links) {
                    if ((l.textContent || '').trim() === '智搜') {
                        l.click();
                        return 'clicked: ' + l.href;
                    }
                }
                return 'not found';
            }
        """)
        print(f"\n=== 点击智搜: {clicked} ===")
        await page.wait_for_timeout(3000)
        print(f"当前 URL: {page.url}")

        # 5. 点击后看右边内容
        if 'aisearch' in page.url or '智搜' in page.text:
            await page.wait_for_timeout(2000)
            right_text = await page.evaluate("""
                () => {
                    var main = document.querySelector('[class*=main], [class*=content], [class*=right], main');
                    if (main) return main.innerText.substring(0, 2000);
                    return document.body.innerText.substring(0, 2000);
                }
            """)
            print(f"\n=== 右边内容 ===")
            print(right_text[:1500])

        await asyncio.sleep(60)  # 保持窗口

asyncio.run(explore())
