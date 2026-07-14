"""
打开浏览器到小红书explore页，等用户手动操作
"""
import asyncio, sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
from playwright.async_api import async_playwright
from common import launch_browser, get_edge_user_data

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp_ui_test")

async def main():
    user_data = get_edge_user_data()
    async with async_playwright() as p:
        context, page, proc = await launch_browser(
            p, headless=False, user_data_dir=user_data, label="xhs_manual"
        )

        try:
            await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            print("=" * 60, file=sys.stderr)
            print("浏览器已打开到小红书探索页", file=sys.stderr)
            print("请：", file=sys.stderr)
            print("1. 搜索任意关键词进入搜索结果页", file=sys.stderr)
            print("2. 点击'筛选'按钮展开筛选面板", file=sys.stderr)
            print("脚本会自动检测到筛选面板并分析结构", file=sys.stderr)
            print("等待中...（最长10分钟）", file=sys.stderr)
            print("=" * 60, file=sys.stderr)

            # 轮询检测筛选面板出现
            found = False
            for i in range(120):
                await page.wait_for_timeout(5000)
                has_panel = await page.evaluate("""() => {
                    var txt = document.body.innerText || '';
                    return {
                        hasDianzan: txt.includes('最多点赞'),
                        hasYizhounei: txt.includes('一周内'),
                        hasBuXian: txt.includes('不限'),
                        hasKeyWords: ['最多点赞','最多收藏','最多评论','一周内','一天内','半年内','不限','最新','已看过','未看过'].filter(function(k) { return txt.includes(k); })
                    };
                }""")
                if has_panel.get("hasDianzan") or has_panel.get("hasBuXian"):
                    print(f"\n检测到筛选面板! 关键词: {has_panel['hasKeyWords']}", file=sys.stderr)
                    found = True
                    break
                if i % 6 == 0:
                    print(f"  等待 {i//12+1} 分钟...", file=sys.stderr)
                    await page.evaluate("console.log('still waiting')")  # keep alive

            if found:
                await page.wait_for_timeout(1000)
                # dump全部结构
                result = await page.evaluate("""() => {
                    var r = {};
                    var kw = ['最多点赞','最多收藏','最多评论','一周内','一天内','半年内','不限','视频','图文','最新','综合','已看过','未看过','已关注','同城','附近'];
                    var allDivs = document.querySelectorAll('div');
                    r.candidates = [];
                    for (var i = 0; i < allDivs.length; i++) {
                        var d = allDivs[i];
                        if (d.offsetParent === null) continue;
                        var txt = (d.textContent || '').trim();
                        if (txt.length < 5) continue;
                        var c = 0;
                        for (var k = 0; k < kw.length; k++) { if (txt.includes(kw[k])) c++; }
                        if (c >= 2) {
                            var cn = ''; try { cn = (typeof d.className === 'string') ? d.className : ''; } catch(e) {}
                            var rect = d.getBoundingClientRect();
                            r.candidates.push({
                                cls: cn.substring(0, 80), tag: d.tagName,
                                rect: Math.round(rect.left)+','+Math.round(rect.top)+' '+Math.round(rect.width)+'x'+Math.round(rect.height),
                                c: c, text: txt.substring(0, 150), html: d.outerHTML.substring(0, 2000)
                            });
                        }
                    }
                    r.candidates.sort(function(a,b){ return b.c - a.c; });
                    r.candidates = r.candidates.slice(0, 10);

                    // 所有data-hp-bound
                    r.hpBound = Array.from(document.querySelectorAll('[data-hp-bound]')).map(function(el) {
                        var cn = ''; try { cn = (typeof el.className === 'string') ? el.className : ''; } catch(e) {}
                        return { tag: el.tagName, id: el.id, cls: cn.substring(0,50), text: (el.textContent||'').trim().substring(0,20), visible: el.offsetParent !== null, rect: el.offsetParent !== null ? JSON.stringify(el.getBoundingClientRect()) : 'hidden' };
                    });

                    // 所有.tags
                    r.tags = Array.from(document.querySelectorAll('.tags, [class*=tags]')).map(function(el) {
                        var cn = ''; try { cn = (typeof el.className === 'string') ? el.className : ''; } catch(e) {}
                        return { tag: el.tagName, cls: cn.substring(0,50), text: (el.textContent||'').trim().substring(0,80), children: el.children.length, html: el.outerHTML.substring(0, 800) };
                    });

                    // body文本筛选行
                    var lines = (document.body.innerText || '').split('\\n');
                    r.filterLines = [];
                    for (var l = 0; l < lines.length; l++) {
                        var line = lines[l].trim();
                        if (kw.includes(line) || line.includes('筛选')) r.filterLines.push(line);
                    }

                    return r;
                }""")
                save_json(result, "filter_manual.json")
                print(f"\n✅ 已保存到 filter_manual.json", file=sys.stderr)
                print(f"找到了 {len(result.get('candidates',[]))} 个候选", file=sys.stderr)
                for item in result.get("candidates", []):
                    print(f"  [{item['tag']}] {item['rect']} matches={item['c']} cls={item['cls'][:40]}", file=sys.stderr)
                    print(f"    text={item['text'][:60]}", file=sys.stderr)
                print(f"\nhp-bound: {len(result.get('hpBound',[]))} 个", file=sys.stderr)
                for item in result.get("hpBound", []):
                    print(f"  {item['tag']}#{item['id']} visible={item['visible']} text={item['text']}", file=sys.stderr)
                print(f"\ntags: {len(result.get('tags',[]))} 个", file=sys.stderr)
                for item in result.get("tags", []):
                    print(f"  {item['cls']} text={item['text']}", file=sys.stderr)
                print(f"\n筛选文本: {result.get('filterLines',[])}", file=sys.stderr)
            else:
                print("\n超时，未检测到筛选面板", file=sys.stderr)

            await page.wait_for_timeout(30000)
        finally:
            await context.close()
            if proc:
                try: proc.kill()
                except: pass

def save_json(data, filename):
    with open(os.path.join(OUT_DIR, filename), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

asyncio.run(main())
