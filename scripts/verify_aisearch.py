"""
验证：直接构造 aisearch URL 获取智搜回答内容
"""
import asyncio, sys, json
sys.path.insert(0, "D:/Users/Desktop/网络热点搜集/scripts")
from playwright.async_api import async_playwright
from common import launch_browser, get_edge_user_data

async def main():
    data = get_edge_user_data()
    async with async_playwright() as p:
        c, page = await launch_browser(p, headless=True, user_data_dir=data, label="verify")
        # 测试一个热搜话题
        topic = "花少8北京开录"
        url = f"https://s.weibo.com/aisearch?q={topic}&Refer=weibo_aisearch"
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)

        # 提取智搜回答内容
        result = await page.evaluate("""
            () => {
                // 找所有大段文字区域
                var all = document.body.innerText || '';
                var lines = all.split(String.fromCharCode(10));
                var answer = [];
                var inAnswer = false;
                for (var i = 0; i < lines.length; i++) {
                    var l = lines[i].trim();
                    if (!l) continue;
                    // 跳过导航和榜单
                    if (['NEW', '综合', '用户', '实时', '视频', '图片', '关注', '超话', '微博热搜',
                        '热搜榜', '文娱榜', '要闻榜', '更多', '刷新', '我的', '推荐', '体育',
                        '生活', '科技', 'ACG', '社会', '财经', '音乐', '电影', '追星',
                        '同城', '榜单', '好友搜索', '搜狗', '微信', '首页', '话题'].indexOf(l) >= 0) continue;
                    if (l.length > 30) {
                        answer.push(l);
                    }
                }
                return answer.join(String.fromCharCode(10));
            }
        """)
        print(f"=== 话题: {topic} ===")
        print(f"智搜回答:\n{result[:800]}")
        print(f"\n--- 共 {len(result)} 字符 ---")

        # 查看更多
        more = await page.evaluate("""
            () => {
                var links = document.querySelectorAll('a');
                for (var l of links) {
                    if ((l.textContent || '').indexOf('查看更多') >= 0) {
                        l.click();
                        return 'clicked';
                    }
                }
                return 'no more btn';
            }
        """)
        print(f"查看更多: {more}")

asyncio.run(main())
