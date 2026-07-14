"""
探测小红书详情页的实际 DOM 结构，找出正文对应的 CSS 选择器
"""
import asyncio, sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from playwright.async_api import async_playwright
from common import kill_edge, launch_browser, get_edge_user_data

async def main():
    edge_user_data = get_edge_user_data()
    async with async_playwright() as p:
        context, page, _tmpdir = await launch_browser(p, headless=False, user_data_dir=edge_user_data, label="probe")
        await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)

        # 直接打开一个笔记
        test_urls = [
            "https://www.xiaohongshu.com/explore/6a4b60a0000000001101197f?xsec_token=ABaCkC-VwLxXVRFfFlL9jF9_1bch2azbI5AVOG_8AqO58=&xsec_source=pc_search",
        ]
        for url in test_urls:
            print(f"\n=== 打开: {url[:60]}... ===")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(8000)

            # 1. 找所有包含正文长度>50的元素的class
            classes = await page.evaluate("""() => {
                var results = [];
                var all = document.querySelectorAll('*');
                for (var el of all) {
                    var t = (el.textContent || '').trim();
                    if (t.length >= 30 && t.length < 5000 && el.children.length <= 3) {
                        // 排除页脚和导航这类
                        var tag = el.tagName.toLowerCase();
                        if (['script','style','nav','footer','header'].includes(tag)) continue;
                        var cls = el.className;
                        if (typeof cls !== 'string') continue;
                        // 获取元素的类名和id
                        var id = el.id || '';
                        var parentCls = el.parentElement ? el.parentElement.className : '';
                        var grandCls = el.parentElement && el.parentElement.parentElement ? el.parentElement.parentElement.className : '';
                        results.push({
                            tag: tag,
                            id: id.substring(0,40),
                            cls: cls.substring(0,80),
                            parentCls: (typeof parentCls === 'string' ? parentCls : '').substring(0,60),
                            grandCls: (typeof grandCls === 'string' ? grandCls : '').substring(0,60),
                            textLen: t.length,
                            textStart: t.substring(0,60)
                        });
                    }
                }
                // 按文本长度降序
                results.sort((a,b) => b.textLen - a.textLen);
                return results.slice(0, 15);
            }""")
            print("=== 包含正文的最可能的元素 TOP 15 ===")
            for i, r in enumerate(classes):
                print(f"  {i+1}. <{r['tag']}> id={r['id']} class={r['cls']}")
                print(f"     parent: {r['parentCls']} | grand: {r['grandCls']}")
                print(f"     长度:{r['textLen']} 开头: {r['textStart'][:60]}")

            # 2. 逐层找笔记正文容器
            container_info = await page.evaluate("""() => {
                // 找包含 "note" 关键词的类名元素
                var noteCandidates = document.querySelectorAll('[class*=note], [class*=content], [class*=article], [class*=detail], [class*=desc]');
                var result = [];
                for (var el of noteCandidates) {
                    var t = (el.textContent || '').trim();
                    if (t.length > 20) {
                        result.push({
                            selector: el.tagName + '.' + (el.className || '').substring(0,80),
                            textLen: t.length,
                            textStart: t.substring(0,60)
                        });
                    }
                }
                return result.slice(0, 10);
            }""")
            print("\n=== 包含 note/content 关键词的容器 ===")
            for r in container_info:
                print(f"  {r['selector']}")
                print(f"    长度:{r['textLen']} 开头: {r['textStart'][:60]}")

            # 3. 检查有没有广告屏蔽文字
            adblock = await page.evaluate("""() => {
                var text = document.documentElement.textContent || '';
                var idx1 = text.indexOf('广告屏蔽插件');
                var idx2 = text.indexOf('您的浏览器似乎');
                var results = [];
                if (idx1 >= 0) results.push({keyword:'广告屏蔽插件', idx: idx1, context: text.substring(Math.max(0,idx1-30), idx1+80)});
                if (idx2 >= 0) results.push({keyword:'您的浏览器似乎', idx: idx2, context: text.substring(Math.max(0,idx2-30), idx2+80)});
                return results;
            }""")
            print(f"\n=== 广告屏蔽检测 ===")
            if adblock:
                for r in adblock:
                    print(f"  找到 '{r['keyword']}' 在位置 {r['idx']}: ...{r['context']}...")
            else:
                print("  未发现广告屏蔽文字")

            # 4. 看 body 纯文字长度和内容
            all_text = await page.evaluate("(document.documentElement.textContent || '').substring(0, 300)")
            print(f"\n=== textContent 前300字 ===")
            print(f"  {all_text}")

asyncio.run(main())
