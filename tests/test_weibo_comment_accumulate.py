"""
测试微博评论累积获取 vs 可见评论行数
看看到底能拿多少条，以及丢失的原因
"""
import asyncio, sys
sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', errors='replace')
from playwright.async_api import async_playwright
from scripts.common import launch_browser, get_edge_user_data

async def test():
    edge_user_data = get_edge_user_data()
    async with async_playwright() as p:
        context, page, _tmpdir = await launch_browser(p, headless=False, user_data_dir=edge_user_data, label='test')
        try:
            detail = await context.new_page()
            await detail.goto('https://weibo.com/5822662089/R8vydodB6', wait_until='domcontentloaded', timeout=30000)
            await detail.wait_for_timeout(8000)

            # 1) 获得页面显示的评论总数
            total = await detail.evaluate('() => { var t = document.body.innerText.split(String.fromCharCode(10)); return parseInt(t[t.indexOf("分享这条博文")-1]); }')
            print(f'页面显示总评论数: {total}')

            # 2) 先定位到评论区域，然后测可见评论行
            await detail.evaluate('() => { var els = document.querySelectorAll("*"); for (var el of els) { if (el.children.length === 0 && (el.textContent || "").trim() === "评论") { el.scrollIntoView({block: "start"}); break; } } }')
            await detail.wait_for_timeout(500)

            # 看当前可见的评论行
            visible = await detail.evaluate('() => { var lines = document.body.innerText.split(String.fromCharCode(10)); var s = lines.indexOf("评论"); var ct=0; for(var j=s+1;j<lines.length;j++){if(lines[j]==="分享这条博文")break;if(j+1<lines.length&&lines[j+1].indexOf(":")===0){ct++;j++;}} return ct; }')
            print(f'当前可见评论行: {visible}')

            # 3) 测试：如果 slow scroll，每轮 300px，每轮都提取累积
            all_comments = []
            seen = set()
            max_rounds = 40
            for i in range(max_rounds):
                await detail.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await detail.wait_for_timeout(300)
                await detail.mouse.wheel(0, 100)
                await detail.wait_for_timeout(500)

                batch = await detail.evaluate('() => { var lines = (document.body.innerText || "").split(String.fromCharCode(10)); var s = lines.indexOf("评论"); if(s<0)return []; var r=[]; for(var j=s+1;j<lines.length;j++){ if(lines[j]==="分享这条博文")break; var n=lines[j+1]||""; if(n.indexOf(":")===0&&n.length>2&&lines[j].indexOf(" ")<0){ r.push({user:lines[j],content:n.substring(1).trim()}); j++; } } return r; }')

                new_c = 0
                for c in batch:
                    k = c['content'][:40]
                    if k and k not in seen:
                        seen.add(k)
                        all_comments.append(c)
                        new_c += 1

                if new_c > 0:
                    if i % 5 == 0:
                        print(f'  round {i}: +{new_c} (total={len(all_comments)})')
                else:
                    if i >= 8:
                        print(f'  round {i}: 停止，累积{len(all_comments)}条')
                        break

            print(f'\\n=== 结果 ===')
            print(f'页面总评论数: {total}')
            print(f'实际采集到: {len(all_comments)}')
            print(f'丢失: {total - len(all_comments)} (如果为负则表示采集到了额外内容)')
        finally:
            await context.close()

asyncio.run(test())
