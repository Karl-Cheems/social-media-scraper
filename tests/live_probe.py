"""实时探查页面状态 — 每按一次回车刷新一次"""
import asyncio, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

async def probe(page):
    data = await page.evaluate("""() => {
        const r = {
            url: location.href.substring(0, 120),
            bodyClass: document.body.className.substring(0, 80),
        };

        // 所有 textarea 搜索框
        r.textareas = [];
        document.querySelectorAll('textarea').forEach(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            r.textareas.push({
                id: el.id || '',
                placeholder: (el.placeholder || '').substring(0, 30),
                value: (el.value || '').substring(0, 30),
                visible: rect.width > 0 && rect.height > 0 && style.display !== 'none',
                rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                opacity: parseFloat(style.opacity),
            });
        });

        // 所有 input[type=text]
        r.inputs = [];
        document.querySelectorAll('input[type="text"], input:not([type])').forEach(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            r.inputs.push({
                id: el.id || '',
                cls: el.getAttribute('class') || '',
                visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && parseFloat(style.opacity) > 0.01,
            });
        });

        // activeElement
        const ae = document.activeElement;
        r.activeElement = ae ? ae.tagName + '#' + (ae.id || '') : 'none';

        // 筛选按钮
        r.filters = [];
        document.querySelectorAll('.filter').forEach(el => {
            const rect = el.getBoundingClientRect();
            r.filters.push({
                cls: el.getAttribute('class') || '',
                text: (el.textContent || '').trim().substring(0, 10),
                visible: rect.width > 0 && rect.height > 0,
                rect: { w: Math.round(rect.width), h: Math.round(rect.height), top: Math.round(rect.top), left: Math.round(rect.left) },
            });
        });

        // ai-chat-section 内部详细结构
        const chatSection = document.querySelector('.ai-chat-section');
        r.chatSection = chatSection ? {
            w: Math.round(chatSection.getBoundingClientRect().width),
            h: Math.round(chatSection.getBoundingClientRect().height),
            children: chatSection.children.length,
            html: chatSection.innerHTML.substring(0, 500),
        } : null;

        // filter-panel 及其内部
        r.filterPanels = [];
        document.querySelectorAll('.filter-panel, [class*="filter-panel"]').forEach(el => {
            const rect = el.getBoundingClientRect();
            r.filterPanels.push({
                cls: el.getAttribute('class') || '',
                visible: rect.width > 0 && rect.height > 0,
                rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                inner: (el.textContent || '').trim().substring(0, 200),
                tags: Array.from(el.querySelectorAll('[data-hp-bound]')).map(t => ({
                    text: (t.textContent || '').trim().substring(0, 20),
                    cls: t.getAttribute('class') || '',
                })),
            });
        });

        // 所有 data-hp-bound 元素
        r.hpBounds = [];
        document.querySelectorAll('[data-hp-bound]').forEach(el => {
            const rect = el.getBoundingClientRect();
            r.hpBounds.push({
                cls: el.getAttribute('class') || '',
                text: (el.textContent || '').trim().substring(0, 20),
                visible: rect.width > 0 && rect.height > 0,
                tag: el.tagName,
            });
        });

        // note-item 卡片数量
        r.noteCount = document.querySelectorAll('section.note-item').length;

        // 遮罩层
        r.overlays = [];
        document.querySelectorAll('[class*="overlay"], [class*="mask"]').forEach(el => {
            if (el.offsetParent !== null) {
                r.overlays.push(el.getAttribute('class') || '');
            }
        });

        // 是否有详情页特征
        r.hasDetail = !!document.querySelector('.interact-container, .note-detail, .comments-container');

        // 搜索框附近结构 - search-area
        r.searchAreas = [];
        document.querySelectorAll('[class*="search-area"]').forEach(el => {
            const rect = el.getBoundingClientRect();
            r.searchAreas.push({
                cls: el.getAttribute('class') || '',
                visible: rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).display !== 'none',
            });
        });

        return r;
    }""")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print("---")

async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:32679")
        pages = browser.contexts[0].pages if browser.contexts else []
        target = None
        for pg in pages:
            if 'xiaohongshu.com/explore' in pg.url or 'xiaohongshu.com/search' in pg.url:
                target = pg
                break
        if not target:
            target = pages[0] if pages else await browser.contexts[0].new_page()
        print(f"当前页面: {target.url[:100]}")
        print("按回车探查一次，输入 q 退出")
        # 首次探查
        await probe(target)
        while True:
            line = sys.stdin.readline().strip()
            if line == 'q': break
            await probe(target)

if __name__ == "__main__":
    asyncio.run(main())
