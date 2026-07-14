"""
探查小红书 ai-layout 在搜索结果页的结构
流程：explore → 搜索"奶茶" → 观察搜索结果页结构 → 返回 → 第二次搜索"咖啡"
"""
import asyncio, json, os, sys, tempfile, random
from urllib.parse import quote

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from common import kill_edge, launch_browser, get_edge_user_data, xhs_search_by_input, detect_xhs_ui_version

OUT = os.path.join(os.path.dirname(__file__), "..", "tmp_ui_test")
os.makedirs(OUT, exist_ok=True)


async def probe_elements(page, label: str):
    """探查当前页面各种关键元素的状态"""
    data = await page.evaluate("""() => {
        const r = { url: location.href, title: document.title, bodyClass: document.body.className };

        // 搜索框相关
        const searchInputs = [];
        document.querySelectorAll('input[type="text"], input:not([type]), textarea, [class*="search"]').forEach(el => {
            const tag = el.tagName;
            const cls = el.className;
            const placeholder = el.placeholder || '';
            const id = el.id || '';
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            searchInputs.push({
                tag, id, cls, placeholder,
                visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0',
                rect: { w: Math.round(rect.width), h: Math.round(rect.height), top: Math.round(rect.top) },
                opacity: style.opacity,
                ariaHidden: el.getAttribute('aria-hidden') || '',
                tabIndex: el.getAttribute('tabindex') || '',
                value: el.value?.substring(0, 30) || '',
            });
        });

        // .search-area
        const searchAreas = [];
        document.querySelectorAll('[class*="search-area"]').forEach(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            searchAreas.push({
                cls: el.className,
                visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && parseFloat(style.opacity) > 0.01,
                rect: { w: Math.round(rect.width), h: Math.round(rect.height), top: Math.round(rect.top) },
                opacity: style.opacity,
            });
        });

        // 筛选按钮
        const filters = [];
        document.querySelectorAll('.filter, [class*="filter"]').forEach(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            filters.push({
                cls: el.className,
                tag: el.tagName,
                text: (el.textContent || '').trim().substring(0, 20),
                visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && parseFloat(style.opacity) > 0.01,
                rect: { w: Math.round(rect.width), h: Math.round(rect.height), top: Math.round(rect.top), left: Math.round(rect.left) },
            });
        });

        // 筛选面板
        const panels = [];
        document.querySelectorAll('.filter-panel, [class*="filter-panel"], [class*="filter_panel"]').forEach(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            panels.push({
                cls: el.className,
                tag: el.tagName,
                visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && parseFloat(style.opacity) > 0.01,
                rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                innerText: (el.textContent || '').trim().substring(0, 100),
            });
        });

        // .tags[data-hp-bound]
        const tags = [];
        document.querySelectorAll('.tags[data-hp-bound]').forEach(el => {
            const rect = el.getBoundingClientRect();
            tags.push({
                text: (el.textContent || '').trim().substring(0, 30),
                visible: rect.width > 0 && rect.height > 0,
                rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                parentCls: el.parentElement?.className?.substring(0, 50) || '',
            });
        });

        // 顶部 tabs（ai-layout新版的特征）
        const tabs = [];
        document.querySelectorAll('.tab').forEach(el => {
            tabs.push({
                text: (el.textContent || '').trim(),
                cls: el.className,
            });
        });

        // .ai-chat-section / .ai-chat-filter
        const aiChat = document.querySelectorAll('.ai-chat-section, .ai-chat-filter').length;

        // note-item 卡片数量
        const noteCount = document.querySelectorAll('section.note-item').length;

        // 详情页检测
        const hasDetail = !!document.querySelector('.interact-container, .comments-container, .note-detail');

        return { ...r, searchInputs, searchAreas, filters, panels, tags, tabs, aiChat, noteCount, hasDetail };
    }""")

    with open(os.path.join(OUT, f"{label}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  [{label}] url: {data.get('url','')[:60]}")
    print(f"  class: {data.get('bodyClass','')}")
    print(f"  搜索框: {len(data.get('searchInputs',[]))}个")
    for s in data.get('searchInputs',[]):
        print(f"    {s['tag']}#{s['id']} cls={s['cls'][:50]} visible={s['visible']} rect={s['rect']} opacity={s['opacity']} ph={s['placeholder']} val={s['value']}")
    print(f"  search-area: {len(data.get('searchAreas',[]))}个")
    for a in data.get('searchAreas',[]):
        print(f"    cls={a['cls'][:60]} visible={a['visible']} rect={a['rect']} opacity={a['opacity']}")
    print(f"  筛选按钮: {len(data.get('filters',[]))}个")
    for f in data.get('filters',[]):
        print(f"    cls={f['cls'][:60]} text={f['text']} visible={f['visible']} rect={f['rect']}")
    print(f"  筛选面板: {len(data.get('panels',[]))}个")
    for p in data.get('panels',[]):
        print(f"    cls={p['cls'][:60]} visible={p['visible']} text={p['innerText'][:60]}")
    print(f"  tags[data-hp-bound]: {len(data.get('tags',[]))}个")
    for t in data.get('tags',[]):
        print(f"    text={t['text']} visible={t['visible']} parent={t['parentCls']}")
    print(f"  tabs: {data.get('tabs',[])}")
    print(f"  aiChat: {data.get('aiChat')} noteCount: {data.get('noteCount')} hasDetail: {data.get('hasDetail')}")
    print()


async def main():
    kill_edge()
    async with async_playwright() as p:
        edge_ud = get_edge_user_data()
        ctx, page, proc = await launch_browser(p, headless=False, user_data_dir=edge_ud, label="probe")

        # 1. Explore 首页
        await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)
        ui = await detect_xhs_ui_version(page)
        print(f"\n=== UI版本: {ui} ===")
        await probe_elements(page, "01-explore")

        # 2. 搜索第一个关键词 "奶茶"
        ok = await xhs_search_by_input(page, "奶茶", "搜索奶茶")
        print(f"  搜索{'成功' if ok else '失败'}")
        await page.wait_for_timeout(5000)
        await probe_elements(page, "02-search-milk-tea")

        # 3. 点击筛选按钮，展开面板
        try:
            filter_btn = page.locator(".filter.ai-chat-filter, .ai-chat-filter .filter, .filter").first
            await filter_btn.wait_for(state="visible", timeout=8000)
            await filter_btn.click()
            await page.wait_for_timeout(3000)
            await probe_elements(page, "03-filter-open")
        except Exception as e:
            print(f"  点击筛选按钮失败: {e}")

        # 4. 关闭筛选
        try:
            await filter_btn.click()
            await page.wait_for_timeout(1000)
        except:
            pass

        # 5. 回到 explore
        await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        await probe_elements(page, "04-back-to-explore")

        # 6. 搜索第二个关键词 "咖啡"
        ok = await xhs_search_by_input(page, "咖啡", "搜索咖啡")
        print(f"  搜索{'成功' if ok else '失败'}")
        await page.wait_for_timeout(5000)
        await probe_elements(page, "05-search-coffee")

        # 7. 再点筛选
        try:
            filter_btn = page.locator(".filter.ai-chat-filter, .ai-chat-filter .filter, .filter").first
            await filter_btn.wait_for(state="visible", timeout=8000)
            await filter_btn.click()
            await page.wait_for_timeout(3000)
            await probe_elements(page, "06-filter-open-2")
        except Exception as e:
            print(f"  第二次点击筛选按钮失败: {e}")

        # 8. 直接浏览器打开搜索页看筛选面板
        search_url = f"https://www.xiaohongshu.com/search_result?keyword={quote('奶茶')}&source=web_search_result_notes"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)
        await probe_elements(page, "07-direct-search-url")

        try:
            filter_btn = page.locator(".filter.ai-chat-filter, .ai-chat-filter .filter, .filter").first
            await filter_btn.wait_for(state="visible", timeout=8000)
            await filter_btn.click()
            await page.wait_for_timeout(3000)
            await probe_elements(page, "08-direct-search-filter-open")
        except Exception as e:
            print(f"  直接搜索页点筛选按钮失败: {e}")

        await ctx.close()
        if proc: proc.kill()


if __name__ == "__main__":
    from playwright.async_api import async_playwright
    asyncio.run(main())
