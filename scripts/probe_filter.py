"""
探查小红书 ai-layout 搜索结果页的筛选面板结构
"""
import asyncio, json, os, sys
from urllib.parse import quote

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from common import kill_edge, launch_browser, get_edge_user_data, xhs_search_by_input, detect_xhs_ui_version

OUT = os.path.join(os.path.dirname(__file__), "..", "tmp_ui_test")
os.makedirs(OUT, exist_ok=True)


async def probe(page, label):
    data = await page.evaluate("""() => {
        const r = { url: location.href, bodyClass: document.body.className };

        // 筛选按钮
        const filters = [];
        document.querySelectorAll('.filter, [class*="filter"], [class*="graphic"], [class*="ai-chat"]').forEach(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            filters.push({
                cls: el.getAttribute('class') || '',
                tag: el.tagName,
                text: (el.textContent || '').trim().substring(0, 20),
                visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && parseFloat(style.opacity) > 0.01,
                rect: { w: Math.round(rect.width), h: Math.round(rect.height), top: Math.round(rect.top), left: Math.round(rect.left) },
            });
        });

        // 各种面板
        const panels = [];
        document.querySelectorAll('.filter-panel, .ai-chat-filter, .ai-chat-section, [class*="filter-panel"], [class*="popover"], [class*="dropdown"]').forEach(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            panels.push({
                cls: el.getAttribute('class') || '',
                visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && parseFloat(style.opacity) > 0.01,
                rect: { w: Math.round(rect.width), h: Math.round(rect.height), top: Math.round(rect.top), left: Math.round(rect.left) },
                innerText: (el.textContent || '').trim().substring(0, 200),
            });
        });

        // .tags[data-hp-bound] 标签
        const tags = [];
        document.querySelectorAll('.tags[data-hp-bound]').forEach(el => {
            const rect = el.getBoundingClientRect();
            tags.push({
                text: (el.textContent || '').trim().substring(0, 30),
                visible: rect.width > 0 && rect.height > 0,
                rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                parentCls: (el.parentElement ? (el.parentElement.getAttribute('class') || '') : ''),
            });
        });

        // 所有 data-hp-bound
        const hpBounds = [];
        document.querySelectorAll('[data-hp-bound]').forEach(el => {
            const rect = el.getBoundingClientRect();
            hpBounds.push({
                cls: el.getAttribute('class') || '',
                tag: el.tagName,
                text: (el.textContent || '').trim().substring(0, 40),
                visible: rect.width > 0 && rect.height > 0,
                rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
            });
        });

        // 遮罩层
        const overlays = [];
        document.querySelectorAll('[class*="overlay"], [class*="mask"], [class*="modal"]').forEach(el => {
            if (el.offsetParent !== null || (el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0)) {
                overlays.push({
                    cls: el.getAttribute('class') || '',
                    rect: { w: Math.round(el.getBoundingClientRect().width), h: Math.round(el.getBoundingClientRect().height) },
                });
            }
        });

        r.noteCount = document.querySelectorAll('section.note-item').length;
        return { ...r, filters, panels, tags, hpBounds, overlays };
    }""")

    with open(os.path.join(OUT, f"filter_{label}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n[{label}] url: {data.get('url','')[:60]}")
    print(f"  class: {data.get('bodyClass','')}")
    print(f"  筛选按钮:")
    for f in data.get('filters',[]):
        print(f"    cls={f['cls'][:60]} text={f['text']} visible={f['visible']} rect={f['rect']}")
    print(f"  面板:")
    for p in data.get('panels',[]):
        print(f"    cls={p['cls'][:60]} visible={p['visible']} rect={p['rect']} text={p['innerText'][:80]}")
    print(f"  tags[data-hp-bound]:")
    for t in data.get('tags',[]):
        print(f"    text={t['text']} visible={t['visible']} parent={t['parentCls']}")
    print(f"  all data-hp-bound: {len(data.get('hpBounds',[]))}")
    for h in data.get('hpBounds',[])[:10]:
        print(f"    cls={h['cls'][:50]} text={h['text']} visible={h['visible']}")
    print(f"  遮罩: {len(data.get('overlays',[]))}")


async def main():
    kill_edge()
    async with async_playwright() as p:
        edge_ud = get_edge_user_data()
        ctx, page, proc = await launch_browser(p, headless=False, user_data_dir=edge_ud, label="probe")

        # 1. 导航到搜索结果页
        search_url = f"https://www.xiaohongshu.com/search_result_ai?keyword={quote('奶茶')}&source=web_search_result_notes"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)
        ui = await detect_xhs_ui_version(page)
        print(f"\n=== UI: {ui} ===")
        await probe(page, "01-on-search-page")

        # 2. 点击筛选按钮
        try:
            filter_btn = page.locator(".filter.ai-chat-filter").first
            await filter_btn.wait_for(state="visible", timeout=8000)
            print(f"\n  点击筛选按钮...")
            await filter_btn.click(force=True)
            await page.wait_for_timeout(3000)
            await probe(page, "02-after-filter-click")
        except Exception as e:
            print(f"\n  点击筛选按钮失败: {e}")

        # 3. 等更久再看看 tags
        try:
            hp_tags = page.locator("[data-hp-bound]").first
            visible = await hp_tags.is_visible(timeout=3000)
            if not visible:
                print("\n  data-hp-bound 还没出现，再等一下...")
                await page.wait_for_timeout(5000)
                await probe(page, "03-after-longer-wait")
        except:
            pass

        # 4. 如果 tags 始终没有，试试手动点击 panel
        try:
            # .ai-chat-filter 可能是整个筛选区，里面直接有标签
            chat_filter = page.locator(".ai-chat-filter").first
            vis = await chat_filter.is_visible()
            if vis:
                print("\n  直接点.ai-chat-filter里面的标签...")
                inners = chat_filter.locator("[data-hp-bound]")
                cnt = await inners.count()
                print(f"    .ai-chat-filter内有 {cnt} 个 data-hp-bound")
                for i in range(cnt):
                    t = await inners.nth(i).inner_text()
                    print(f"      [{i}] {t.strip()}")
        except Exception as e:
            print(f"  检查.ai-chat-filter失败: {e}")

        await ctx.close()
        if proc: proc.kill()


if __name__ == "__main__":
    from playwright.async_api import async_playwright
    asyncio.run(main())
