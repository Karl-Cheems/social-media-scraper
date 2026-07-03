"""探索热搜话题搜索页左侧"""
import asyncio, sys
sys.path.insert(0, "D:/Users/Desktop/网络热点搜集/scripts")
from common import launch_browser, get_edge_user_data
from playwright.async_api import async_playwright

async def explore():
    data = get_edge_user_data()
    async with async_playwright() as p:
        c, page = await launch_browser(p, headless=True, user_data_dir=data, label="explore")
        # 走热搜榜，然后进一个话题的搜索页
        await page.goto("https://weibo.com/hot/search", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)

        # 点第一个热搜话题
        clicked = await page.evaluate("""
            () => {
                var items = document.querySelectorAll('[class*=_titout_]');
                for (var item of items) {
                    var link = item.querySelector('a[href*="weibo.com"], a[href*="s.weibo"]');
                    if (link) {
                        link.click();
                        return link.href;
                    }
                }
                return 'no link';
            }
        """)
        print(f"点击话题链接: {clicked}")
        await page.wait_for_timeout(5000)
        print(f"当前URL: {page.url}")

        # 在这个页面左侧找智搜
        side_text = await page.evaluate("""
            () => {
                var navs = document.querySelectorAll('[class*=side], nav, [class*=left]');
                var r = [];
                for (var n of navs) {
                    var t = n.textContent.trim().substring(0, 500);
                    r.push({cls: n.className.substring(0, 60), text: t});
                }
                return r;
            }
        """)
        print(f"\n侧边栏区域 ({len(side_text)}):")
        for s in side_text[:3]:
            print(f"  [{s['cls']}]: {s['text'][:200]}")

        # 全页找aisearch/智搜
        aisearch_links = await page.evaluate("""
            () => {
                var links = document.querySelectorAll('a');
                var r = [];
                for (var l of links) {
                    var h = (l.href || '').toLowerCase();
                    var t = (l.textContent || '').trim();
                    if (h.indexOf('aisearch') >= 0 || h.indexOf('ai') >= 0 || t.indexOf('智搜') >= 0 || t.indexOf('AI') >= 0) {
                        r.push({text: t.substring(0, 40), href: l.href.substring(0, 100)});
                    }
                }
                return r;
            }
        """)
        print(f"\nAI/智搜链接: {aisearch_links}")

        # 完整页面文本
        text = await page.evaluate("document.body.innerText")
        for line in text.split('\n'):
            if '智搜' in line:
                print(f"  '智搜': {line.strip()[:100]}")

asyncio.run(explore())
