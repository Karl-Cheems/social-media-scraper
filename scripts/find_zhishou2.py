"""s.weibo.com搜索页左侧所有栏目标题"""
import asyncio, sys, os
sys.path.insert(0, "D:/Users/Desktop/网络热点搜集/scripts")
os.environ["PYTHONIOENCODING"] = "utf-8"
from playwright.async_api import async_playwright
from common import launch_browser, get_edge_user_data

async def main():
    data = get_edge_user_data()
    async with async_playwright() as p:
        c, page = await launch_browser(p, headless=True, user_data_dir=data, label="e")
        await page.goto("https://s.weibo.com/weibo?q=花少8北京开录", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)
        print(f"URL: {page.url}")

        # 获取左侧所有标题/导航区域
        info = await page.evaluate("""
            () => {
                // 获取所有可见的div、section、aside的innerText（短文本）
                var all = document.querySelectorAll('div, section, aside, nav');
                var titles = [];
                var seen = new Set();
                for (var el of all) {
                    var t = (el.textContent || '').trim();
                    if (t && t.length < 30 && t.length > 1 && !seen.has(t)) {
                        seen.add(t);
                        titles.push(t);
                    }
                }
                return Array.from(titles).sort();
            }
        """)
        print("所有短文本块:")
        for t in info:
            if any(k in t for k in ['智', 'AI', 'ai', '搜索', '搜', '结果', '栏', '列']):
                print(f"  ★ {t}")
            else:
                print(f"  {t}")

        # 特别看左侧区域(包含'智'字)
        zhitext = await page.evaluate("""
            () => {
                var all = document.body.innerText || '';
                var lines = all.split(String.fromCharCode(10));
                return lines.filter(l => l.indexOf('智') >= 0);
            }
        """)
        print(f"\n含'智'字行: {zhitext}")

        # 完整HTML中搜aisearch/zhishou
        html = await page.evaluate("document.documentElement.innerHTML.substring(0, 50000)")
        idx = html.lower().find('aisearch')
        if idx >= 0:
            print(f"\naisearch出现在HTML中位置 {idx}: ...{html[max(0,idx-100):idx+200]}...")
        else:
            idx2 = html.lower().find('智搜')
            if idx2 >= 0:
                print(f"\n智搜出现在HTML: ...{html[max(0,idx2-100):idx2+200]}...")
            else:
                print("\nHTML中未找到aisearch或智搜")

asyncio.run(main())
