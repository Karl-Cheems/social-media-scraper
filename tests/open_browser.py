"""
打开小红书浏览器供人工演示操作流程
"""
import asyncio, os, sys, subprocess, socket, random, json, tempfile, shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from common import get_edge_user_data, _edge_lock_clear, _EDGE_LOCK, _find_edge_exe

async def main():
    _edge_lock_clear()

    # 关闭旧 Edge
    subprocess.run(["taskkill", "/f", "/t", "/im", "msedge.exe"], capture_output=True, timeout=10)
    await asyncio.sleep(2)
    print("旧 Edge 进程已清理", file=sys.stderr)

    edge_exe = _find_edge_exe()
    user_data_dir = get_edge_user_data()
    pw_data_dir = os.path.join(os.path.dirname(user_data_dir), "PlaywrightUserData")
    os.makedirs(pw_data_dir, exist_ok=True)
    for f in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        p2 = os.path.join(pw_data_dir, f)
        if os.path.exists(p2):
            try: os.remove(p2)
            except: pass

    DEBUG_PORT = random.randint(20000, 60000)
    proc = subprocess.Popen([edge_exe, f"--remote-debugging-port={DEBUG_PORT}", "--remote-allow-origins=*", f"--user-data-dir={pw_data_dir}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Edge 已启动 (PID={proc.pid})，端口={DEBUG_PORT}", file=sys.stderr)

    # 端口就绪
    for i in range(20):
        await asyncio.sleep(1)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        if s.connect_ex(("127.0.0.1", DEBUG_PORT)) == 0:
            s.close()
            break
        s.close()

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{DEBUG_PORT}")
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)
        print(f"已打开小红书，当前URL: {page.url[:80]}", file=sys.stderr)
        print(f"浏览器窗口已打开，你可以进行操作了。", file=sys.stderr)
        print(f"操作完成后，在此终端按 Ctrl+C 关闭浏览器。", file=sys.stderr)

        # 保持页面打开，每10秒检查是否还在
        while True:
            await asyncio.sleep(10)
            try:
                await page.evaluate("1")
            except:
                print("页面已关闭", file=sys.stderr)
                break

    proc.kill()

if __name__ == "__main__":
    asyncio.run(main())
