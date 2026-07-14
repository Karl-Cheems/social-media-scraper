"""连接到已有的 Edge 实例，探查当前页面的完整结构"""
import asyncio, json, os, sys, socket, subprocess, tempfile, glob

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from common import _EDGE_LOCK

async def main():
    # 从锁文件获取端口
    port = None
    try:
        if os.path.isfile(_EDGE_LOCK):
            with open(_EDGE_LOCK) as f:
                data = json.load(f)
            port = data.get("port")
    except: pass

    if not port:
        print("找不到 Edge 锁文件，尝试扫描端口...")
        # 扫描常见端口
        for p in range(9200, 9300):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", p)) == 0:
                # 尝试 CDP 握手
                try:
                    import http.client
                    conn = http.client.HTTPConnection("127.0.0.1", p, timeout=1)
                    conn.request("GET", "/json/version")
                    resp = conn.getresponse()
                    if resp.status == 200:
                        port = p
                        s.close()
                        conn.close()
                        break
                    conn.close()
                except: pass
            s.close()

    if not port:
        # 尝试常见的调试端口范围
        for p in range(10000, 60000):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.1)
            if s.connect_ex(("127.0.0.1", p)) == 0:
                try:
                    import http.client
                    conn = http.client.HTTPConnection("127.0.0.1", p, timeout=0.5)
                    conn.request("GET", "/json/version")
                    resp = conn.getresponse()
                    if resp.status == 200:
                        port = p
                        s.close()
                        conn.close()
                        break
                    conn.close()
                except: pass
            s.close()

    if not port:
        print("找不到 Edge 调试端口，请确保 Edge 已通过脚本启动")
        return

    print(f"连接到 Edge 调试端口: {port}")

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        print(f"已连接，有 {len(browser.contexts)} 个 context, {sum(len(ctx.pages) for ctx in browser.contexts)} 个页面")

        # 获取所有页面
        for ctx in browser.contexts:
            for pg in ctx.pages:
                print(f"\n=== 页面: {pg.url[:100]} ===")

                # 获取完整 DOM 分析
                analysis = await pg.evaluate("""() => {
                    const r = {
                        url: location.href,
                        bodyClass: document.body.className,
                        // 搜索框
                        textareas: [],
                    };

                    // 所有 textarea
                    document.querySelectorAll('textarea').forEach(el => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        r.textareas.push({
                            id: el.id || '',
                            placeholder: el.placeholder || '',
                            value: el.value,
                            visible: rect.width > 0 && rect.height > 0 && style.display !== 'none',
                            rect: { w: Math.round(rect.width), h: Math.round(rect.height) },
                            opacity: style.opacity,
                        });
                    });

                    // 检查当前 activeElement
                    const ae = document.activeElement;
                    r.activeElement = ae ? ae.tagName + '#' + (ae.id || '') : 'none';

                    // 筛选相关的全部元素 - 深度遍历 ai-chat-section
                    const filterSection = document.querySelector('.ai-chat-section, .ai-chat-filter');
                    r.filterSectionHTML = filterSection ? filterSection.outerHTML.substring(0, 3000) : 'none';

                    return r;
                }""")

                print(json.dumps(analysis, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
