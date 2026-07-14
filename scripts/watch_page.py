"""持续监控页面状态，每3秒出一次关键变化"""
import asyncio, json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

last_state = {}

async def poll(page):
    global last_state
    data = await page.evaluate("""() => {
        const r = {
            url: location.href.substring(0, 120),
            bodyClass: document.body.className.substring(0, 80),
        };

        // 搜索框
        r.searchInputs = [];
        document.querySelectorAll('textarea, input[type="text"], input:not([type])').forEach(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            const tag = el.tagName;
            r.searchInputs.push({
                id: el.id || '',
                tag,
                cls: (el.getAttribute('class') || '').substring(0, 40),
                placeholder: (el.placeholder || '').substring(0, 20),
                value: (el.value || '').substring(0, 20),
                visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && parseFloat(style.opacity) > 0.01,
            });
        });

        // 筛选按钮
        r.filters = [];
        document.querySelectorAll('.filter').forEach(el => {
            const rect = el.getBoundingClientRect();
            r.filters.push({
                cls: (el.getAttribute('class') || '').substring(0, 60),
                text: (el.textContent || '').trim().substring(0, 10),
                visible: rect.width > 0 && rect.height > 0,
            });
        });

        // 筛选面板
        r.filterPanels = [];
        document.querySelectorAll('.filter-panel').forEach(el => {
            const rect = el.getBoundingClientRect();
            const tags = Array.from(el.querySelectorAll('[data-hp-bound]')).map(t => ({
                text: (t.textContent || '').trim().substring(0, 20),
            }));
            r.filterPanels.push({
                visible: rect.width > 0 && rect.height > 0,
                tags,
                inner: (el.textContent || '').trim().substring(0, 100),
            });
        });

        // ai-chat-section 内部 - 检查是否有 .filter-panel
        r.chatFilterPanel = null;
        const chatFilter = document.querySelector('.ai-chat-filter');
        if (chatFilter) {
            const fp = chatFilter.querySelector('.filter-panel');
            if (fp) {
                r.chatFilterPanel = {
                    visible: fp.getBoundingClientRect().width > 0,
                    inner: (fp.textContent || '').trim().substring(0, 100),
                    tags: Array.from(fp.querySelectorAll('[data-hp-bound]')).map(t => ({
                        text: (t.textContent || '').trim().substring(0, 20),
                    })),
                };
            } else {
                r.chatFilterPanel = { visible: false, inner: 'no filter-panel found', tags: [] };
            }
        }

        // 所有 data-hp-bound
        r.hpBounds = [];
        document.querySelectorAll('[data-hp-bound]').forEach(el => {
            r.hpBounds.push({
                cls: (el.getAttribute('class') || '').substring(0, 40),
                text: (el.textContent || '').trim().substring(0, 20),
                tag: el.tagName,
            });
        });

        r.noteCount = document.querySelectorAll('section.note-item').length;
        r.hasDetail = !!document.querySelector('.interact-container, .comments-container, .note-detail');
        r.activeEl = document.activeElement ? document.activeElement.tagName + '#' + (document.activeElement.id || '') : 'none';

        return r;
    }""")

    # 只打印变化
    changes = []
    if last_state:
        if last_state.get('url','') != data['url']: changes.append(f"URL: {data['url'][:60]}")
        if last_state.get('noteCount') != data['noteCount']: changes.append(f"卡片: {data['noteCount']}")
        if last_state.get('hasDetail') != data['hasDetail']: changes.append(f"详情页: {data['hasDetail']}")
        if last_state.get('activeEl') != data['activeEl']: changes.append(f"焦点: {data['activeEl']}")
        if last_state.get('filterPanels') != data['filterPanels']:
            for fp in data['filterPanels']:
                if fp['visible']: changes.append(f"筛选面板: 可见 tags={[t['text'] for t in fp['tags']]}")
            for fp in last_state.get('filterPanels',[]):
                if fp['visible'] and not any(f['visible'] for f in data['filterPanels']): changes.append("筛选面板: 关闭")
        if last_state.get('hpBounds') != data['hpBounds']:
            vis = [h for h in data['hpBounds'] if h['text']]
            if vis: changes.append(f"data-hp-bound: {[(h['text'],h['cls']) for h in vis]}")
        si_vis = [(s['id'], s['value']) for s in data['searchInputs'] if s['visible'] and s['tag'] == 'TEXTAREA']
        si_old = [(s['id'], s['value']) for s in last_state.get('searchInputs',[]) if s['visible'] and s['tag'] == 'TEXTAREA']
        if si_vis != si_old: changes.append(f"可见搜索框: {si_vis}")
        if data['bodyClass'] != last_state.get('bodyClass',''): changes.append(f"UI: {data['bodyClass']}")
    else:
        changes = ["首次探测"]

    now = time.strftime("%H:%M:%S")
    if changes:
        print(f"\n[{now}] {'|'.join(changes)}", flush=True)

    last_state = data

async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:32679")
        ctx = browser.contexts[0]
        target = None
        for pg in ctx.pages:
            if 'xiaohongshu' in pg.url:
                target = pg
                break
        if not target:
            target = ctx.pages[0]
        print(f"监控页面: {target.url[:80]}", flush=True)
        print("每3秒检测一次，等你操作...", flush=True)
        while True:
            await poll(target)
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(main())
