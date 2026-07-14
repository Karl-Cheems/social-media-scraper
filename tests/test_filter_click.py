"""
测试点击筛选标签：用各种方式点击，看哪个能生效
"""
import asyncio, json, os, sys, subprocess, socket, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from common import get_edge_user_data, _find_edge_exe

async def main():
    # 清理旧进程
    subprocess.run(['taskkill','/f','/t','/im','msedge.exe'], capture_output=True, timeout=10)
    await asyncio.sleep(2)

    u = get_edge_user_data()
    pw = os.path.join(os.path.dirname(u), 'PlaywrightUserData')
    os.makedirs(pw, exist_ok=True)
    for f in ['SingletonLock','SingletonCookie','SingletonSocket']:
        p2 = os.path.join(pw, f)
        if os.path.exists(p2):
            try: os.remove(p2)
            except: pass

    exe = _find_edge_exe()
    port = random.randint(20000, 50000)
    proc = subprocess.Popen([exe, f'--remote-debugging-port={port}', '--remote-allow-origins=*', f'--user-data-dir={pw}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for i in range(20):
        await asyncio.sleep(1)
        s = socket.socket(); s.settimeout(1)
        if s.connect_ex(('127.0.0.1', port)) == 0: s.close(); break
        s.close()

    print(f'PORT={port}', flush=True)
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
        ctx = b.contexts[0] if b.contexts else await b.new_context()
        pg = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await pg.goto('https://www.xiaohongshu.com/explore', wait_until='domcontentloaded', timeout=60000)
        await pg.wait_for_timeout(3000)
        print('READY', flush=True)

        # 等待用户操作到搜索结果页
        while True:
            await asyncio.sleep(3)
            try:
                url = await pg.evaluate('location.href')
                if 'search_result' in url:
                    print(f'检测到搜索结果页: {url[:80]}', flush=True)
                    break
            except: break

        # 现在测试点击筛选
        await asyncio.sleep(2)

        # 1. 先点筛选按钮打开面板
        btn = pg.locator('.filter.ai-chat-filter').first
        await btn.wait_for(state='visible', timeout=5000)
        await btn.click()
        await asyncio.sleep(2)
        print('筛选面板已打开', flush=True)

        # 2. 探查面板内所有可点击的标签
        info = await pg.evaluate("""() => {
            const r = {};

            // 方法1: tags[data-hp-bound]
            r.tags_hp = Array.from(document.querySelectorAll('.tags[data-hp-bound]')).map(el => ({
                text: (el.textContent||'').trim(),
                rect: el.getBoundingClientRect(),
                cls: el.getAttribute('class')||'',
                opacity: parseFloat(window.getComputedStyle(el).opacity),
                pointerEvents: window.getComputedStyle(el).pointerEvents,
            }));

            // 方法2: filter-panel 内所有 span/div button（直接找可见文本）
            const panel = document.querySelector('.filter-panel');
            if (panel) {
                r.panel = {
                    rect: panel.getBoundingClientRect(),
                    html: panel.innerHTML.slice(0, 3000),
                };
                r.panelSpans = Array.from(panel.querySelectorAll('span')).map(el => ({
                    text: (el.textContent||'').trim(),
                    rect: el.getBoundingClientRect(),
                    parentCls: (el.parentElement?.getAttribute('class')||'').slice(0,40),
                }));
            }

            // 方法3: 所有带有筛选标签文字的 button/div/span （不限边界）
            r.allClickable = [];
            document.querySelectorAll('div, span, button').forEach(el => {
                const text = (el.textContent||'').trim();
                if (['最多点赞','一周内','图文','综合','最新发布','视频','不限'].includes(text)) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 10 && rect.height > 10) {
                        r.allClickable.push({
                            text,
                            tag: el.tagName,
                            rect: {x: Math.round(rect.left), y: Math.round(rect.top), w: Math.round(rect.width), h: Math.round(rect.height)},
                            cls: (el.getAttribute('class')||'').slice(0,50),
                            opacity: parseFloat(window.getComputedStyle(el).opacity),
                        });
                    }
                }
            });

            return r;
        }""")
        print(json.dumps(info, ensure_ascii=False, indent=2), flush=True)

        # 3. 用 page.mouse.click 点"最多点赞"
        target = '最多点赞'
        coords = await pg.evaluate(f"""() => {{
            var all = document.querySelectorAll('div, span');
            for (var el of all) {{
                var text = (el.textContent||'').trim();
                if (text !== '{target}') continue;
                var rect = el.getBoundingClientRect();
                if (rect.width < 10 || rect.height < 10) continue;
                var opacity = parseFloat(window.getComputedStyle(el).opacity);
                if (opacity < 0.01) continue;
                return {{ x: Math.round(rect.left + rect.width/2), y: Math.round(rect.top + rect.height/2) }};
            }}
            return null;
        }}""")
        if coords:
            print(f'点击 {target} 坐标: {coords}', flush=True)
            await pg.mouse.click(coords['x'], coords['y'])
            await asyncio.sleep(1)
            # 确认点击是否生效
            info2 = await pg.evaluate("""() => {
                return Array.from(document.querySelectorAll('.filter-panel .tags.active')).map(el => (el.textContent||'').trim());
            }""")
            print(f'点击后 active 标签: {info2}', flush=True)
        else:
            print(f'找不到 {target} 坐标', flush=True)

        # 保持打开
        print('DONE', flush=True)
        while True: await asyncio.sleep(60)

    proc.kill()

asyncio.run(main())
