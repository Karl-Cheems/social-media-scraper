"""
测试小红书评论区展开 — 直接从指定 URL 打开详情页，测滚动前先点展开的逻辑
"""
import asyncio, sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright
from common import launch_browser, get_edge_user_data

TEST_URL = (
    "https://www.xiaohongshu.com/discovery/item/6a4789b1000000000f0338b6"
    "?source=webshare&xhsshare=pc_web&xsec_token=AB0THumG9g8l5UUu4-iKtD-XhQ2ZzrzDOrnaf5iTF1uPk="
    "&xsec_source=pc_share"
)

async def main():
    edge_user_data = get_edge_user_data()
    async with async_playwright() as p:
        context, page, _tmpdir = await launch_browser(p, headless=False, user_data_dir=edge_user_data, label="comment_test")

        await page.goto(TEST_URL, wait_until="domcontentloaded", timeout=30000)
        print(f"已打开详情页: {page.url[:80]}...", file=sys.stderr)
        await page.wait_for_timeout(5000)  # 等页面渲染

        # 检查评论区
        container = page.locator(".comments-container").first
        if not await container.is_visible(timeout=8000):
            print("⚠️ 评论区不可见，截图中", file=sys.stderr)
            await page.screenshot(path=os.path.expanduser("~/Desktop/debug_comment.png"))
            return

        print("✅ 评论区可见", file=sys.stderr)
        await container.hover()
        await page.wait_for_timeout(500)

        # 初始状态
        init_cnt = await page.evaluate("document.querySelectorAll('.comments-container .parent-comment').length")
        init_btns = await page.evaluate("""() => {
            var btns = document.querySelectorAll('.comments-container .show-more, .comments-container [class*=expand]');
            return Array.from(btns).map(b => ({
                text: (b.textContent||'').trim(),
                top: Math.round(b.getBoundingClientRect().top),
                bottom: Math.round(b.getBoundingClientRect().bottom),
                vh: window.innerHeight
            }));
        }""")
        print(f"初始评论: {init_cnt}, 展开按钮: {len(init_btns)}个", file=sys.stderr)
        for i, b in enumerate(init_btns):
            print(f"  btn[{i}] '{b['text'][:35]}' top={b['top']} bottom={b['bottom']} vh={b['vh']}", file=sys.stderr)

        # 模拟 keyword_search.py 的新逻辑：先扫再滚
        total_clicked = 0
        for rnd in range(50):
            current_cnt = await page.evaluate("document.querySelectorAll('.comments-container .parent-comment').length")
            print(f"\n[第{rnd}轮] 当前评论数: {current_cnt} (目标: ∞)", file=sys.stderr)
            if current_cnt >= 80:
                print("✅ 评论数够了，退出", file=sys.stderr)
                break

            # 第一步：找当前可见展开按钮，点它
            clicked = await page.evaluate("""() => {
                var btns = document.querySelectorAll('.comments-container .show-more, .comments-container [class*=expand]');
                var vh = window.innerHeight;
                var count = 0;
                var details = [];
                for (var btn of btns) {
                    var t = (btn.textContent || '').trim();
                    var r = btn.getBoundingClientRect();
                    var maxBottom = vh + 100;
                    if (r.top >= -100 && r.bottom <= maxBottom &&
                        t.indexOf('条回复') >= 0 && t.indexOf('展开更多') < 0 &&
                        btn.dataset._ex_done !== '1') {
                        btn.dataset._ex_done = '1';
                        btn.scrollIntoView({block: 'center'});
                        btn.click();
                        count++;
                        details.push(t.slice(0, 30) + ' @top=' + Math.round(r.top));
                    }
                }
                return {count: count, details: details};
            }""")
            if clicked['count'] > 0:
                total_clicked += clicked['count']
                print(f"  👆 点了 {clicked['count']} 个展开按钮:", file=sys.stderr)
                for d in clicked['details']:
                    print(f"    - {d}", file=sys.stderr)
                await page.wait_for_timeout(600)

            # 第二步：滚一小段
            await page.mouse.wheel(0, 200)
            await page.wait_for_timeout(500)

            # 每5轮打印一次状态
            if rnd % 5 == 0 or clicked['count'] > 0:
                visible_btns = await page.evaluate("""() => {
                    var btns = document.querySelectorAll('.comments-container .show-more, .comments-container [class*=expand]');
                    var vh = window.innerHeight;
                    return Array.from(btns).map(b => ({
                        text: (b.textContent||'').trim(),
                        top: Math.round(b.getBoundingClientRect().top),
                        bottom: Math.round(b.getBoundingClientRect().bottom),
                        done: b.dataset._ex_done === '1'
                    }));
                }""")
                undone = [b for b in visible_btns if not b['done'] and '条回复' in b['text'] and '展开更多' not in b['text']]
                if undone:
                    print(f"  还有 {len(undone)} 个未点展开:", file=sys.stderr)
                    for b in undone[:5]:
                        print(f"    '{b['text'][:30]}' top={b['top']} bottom={b['bottom']}", file=sys.stderr)

        print(f"\n{'='*50}", file=sys.stderr)
        print(f"总计点击展开: {total_clicked} 次", file=sys.stderr)
        final_cnt = await page.evaluate("document.querySelectorAll('.comments-container .parent-comment').length")
        print(f"最终评论数: {final_cnt}", file=sys.stderr)

        # 检查还有未点的
        remaining = await page.evaluate("""() => {
            var btns = document.querySelectorAll('.comments-container .show-more, .comments-container [class*=expand]');
            var undone = [];
            for (var btn of btns) {
                var t = (btn.textContent || '').trim();
                if (t.indexOf('条回复') >= 0 && t.indexOf('展开更多') < 0 && btn.dataset._ex_done !== '1') {
                    undone.push(t.slice(0, 40));
                }
            }
            return undone;
        }""")
        if remaining:
            print(f"剩余未点: {remaining}", file=sys.stderr)
        else:
            print("✅ 所有展开按钮都已点完", file=sys.stderr)

        print("\n观察 30s 后关闭...", file=sys.stderr)
        await page.wait_for_timeout(30000)
        await context.close()

asyncio.run(main())
