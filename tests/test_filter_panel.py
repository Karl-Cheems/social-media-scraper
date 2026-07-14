"""
测试小红书筛选面板：打开 explore → 搜索 → 打开筛选面板 → 点击排序标签
"""
import asyncio, sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright
from common import launch_browser, get_edge_user_data, xhs_search_by_input, detect_xhs_ui_version

async def main():
    edge_user_data = get_edge_user_data()
    async with async_playwright() as p:
        context, page, _tmpdir = await launch_browser(p, headless=False, user_data_dir=edge_user_data, label="filter_test")

        # 搜索
        ok = await xhs_search_by_input(page, "职场整活", "测试搜索")
        if not ok:
            print("❌ 搜索失败", file=sys.stderr)
            return
        await page.wait_for_timeout(3000)
        print("✅ 搜索完成", file=sys.stderr)

        # 检测 UI 版本
        ui_version = await detect_xhs_ui_version(page)
        print(f"UI: {ui_version}", file=sys.stderr)

        # 点筛选按钮
        await page.evaluate("""() => {
            var btn = document.querySelector('.filter, .ai-chat-filter');
            if (btn) btn.dispatchEvent(new MouseEvent('click', { bubbles: true, view: window }));
        }""")
        print("筛选按钮已 dispatchEvent", file=sys.stderr)
        await page.wait_for_timeout(500)

        # 检查面板
        has_panel = await page.evaluate("document.querySelector('.filter-panel') ? true : false")
        print(f"筛选面板显示: {has_panel}", file=sys.stderr)

        if has_panel:
            # 打印所有可点元素
            items = await page.evaluate("""() => {
                var panel = document.querySelector('.filter-panel');
                if (!panel) return [];
                var els = panel.querySelectorAll('div, span');
                var r = [];
                for (var el of els) {
                    var t = (el.textContent || '').trim();
                    var rect = el.getBoundingClientRect();
                    if (t.length > 0 && t.length < 10 && rect.width >= 20 && rect.height >= 20) {
                        r.push({text: t, w: Math.round(rect.width), h: Math.round(rect.height),
                                x: Math.round(rect.left + rect.width/2), y: Math.round(rect.top + rect.height/2)});
                    }
                }
                return r;
            }""")
            print(f"面板内可点元素 ({len(items)}):", file=sys.stderr)
            for it in items:
                print(f"  '{it['text']}' size={it['w']}x{it['h']} @({it['x']},{it['y']})", file=sys.stderr)

            # 测试：点"最多评论"
            sort_tag = "最多评论"
            coords = await page.evaluate(f"""(text) => {{
                var panel = document.querySelector('.filter-panel');
                if (!panel) return null;
                var els = panel.querySelectorAll('div');
                for (var d of els) {{
                    var r = d.getBoundingClientRect();
                    if (r.width < 20 || r.height < 20) continue;
                    if ((d.textContent || '').trim() === text) {{
                        return {{ x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2) }};
                    }}
                    var spans = d.querySelectorAll('span');
                    for (var s of spans) {{
                        if ((s.textContent || '').trim() === text) {{
                            var sr = s.getBoundingClientRect();
                            if (sr.width >= 20 && sr.height >= 20) {{
                                return {{ x: Math.round(sr.left + sr.width/2), y: Math.round(sr.top + sr.height/2) }};
                            }}
                        }}
                    }}
                }}
                return null;
            }}""", sort_tag)
            if coords:
                print(f"点击: {sort_tag} @({coords['x']}, {coords['y']})", file=sys.stderr)
                await page.mouse.click(coords['x'], coords['y'])
                await page.wait_for_timeout(500)
                print(f"已点击 {sort_tag}", file=sys.stderr)
            else:
                print(f"未找到 {sort_tag}", file=sys.stderr)

        print("\n观察 15s 后关闭...", file=sys.stderr)
        await page.wait_for_timeout(15000)
        await context.close()

asyncio.run(main())
