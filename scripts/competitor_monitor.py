"""
竞品账号内容运营数据采集脚本
支持微博和小红书，自动识别平台，统一输出格式

用法：
    python competitor_monitor.py --urls https://weibo.com/xxx https://xiaohongshu.com/user/profile/xxx
    python competitor_monitor.py --urls https://weibo.com/xxx --limit 5 --comments
    python competitor_monitor.py --urls url1 url2 -o result.json
"""

import argparse
import asyncio
import json
import os
import random
import re
import sys
import time

from common import write_output

import weibo_scraper
import xiaohongshu_scraper


def detect_platform(identifier: str) -> str:
    """根据输入判断平台。weibo URL → weibo，纯数字 → xiaohongshu，xiaohongshu URL → xiaohongshu。"""
    if re.search(r'weibo\.com', identifier):
        return 'weibo'
    if re.search(r'xiaohongshu\.com', identifier):
        return 'xiaohongshu'
    if re.match(r'^\d+$', identifier.strip()):
        return 'xiaohongshu'
    raise ValueError(f"不支持的平台，输入: {identifier}")


def _build_profile_url(identifier: str) -> str:
    """把输入转为 scraper 实际使用的 profile URL。微博保持原样，小红书号 → profile/{id}。"""
    platform = detect_platform(identifier)
    if platform == 'weibo':
        return identifier
    if platform == 'xiaohongshu':
        uid = identifier.strip()
        if 'xiaohongshu.com' in uid:
            return uid
        return f"https://www.xiaohongshu.com/user/profile/{uid}"
    return identifier


async def scrape_account(identifier: str, limit: int, fetch_comments: bool,
                         max_comments: int, headless: bool,
                         no_content: bool = False) -> dict:
    """采集单个账号的数据，返回统一格式的 dict。"""
    platform = detect_platform(identifier)
    profile_url = _build_profile_url(identifier)

    if platform == 'weibo':
        result = await weibo_scraper.scrape_profile(
            profile_url=profile_url,
            limit=limit,
            headless=headless,
            fetch_comments=fetch_comments,
            max_comments=max_comments,
        )
        return {
            "platform": "weibo",
            "author": result.author,
            "url": profile_url,
            "total_collected": result.total_collected,
            "items": [
                {
                    "text": w.text,
                    "reposts": w.reposts,
                    "comments": w.comments,
                    "likes": w.likes,
                    "url": w.url,
                    "published_at": w.published_at,
                    "comments_list": [
                        {"user": c.user, "content": c.content, "likes": c.likes}
                        for c in w.comments_list
                    ],
                }
                for w in result.weibos
            ],
        }

    elif platform == 'xiaohongshu':
        result = await xiaohongshu_scraper.scrape_profile(
            profile_url=profile_url,
            limit=limit,
            headless=headless,
            fetch_comments=fetch_comments,
            max_comments=max_comments,
            no_content=no_content,
        )
        return {
            "platform": "xiaohongshu",
            "author": result.author,
            "url": profile_url,
            "total_collected": result.total_collected,
            "items": [
                {
                    "title": n.title,
                    "content": n.content,
                    "likes": n.likes,
                    "collects": n.collects,
                    "comments": n.comments,
                    "url": n.url,
                    "published_at": n.published_at,
                    "comments_list": [
                        {"user": c.user, "content": c.content, "likes": c.likes}
                        for c in n.comments_list
                    ],
                }
                for n in result.notes
            ],
        }


def main():
    parser = argparse.ArgumentParser(
        description="竞品账号监控工具 - 支持微博和小红书，自动识别平台"
    )
    parser.add_argument(
        "--urls", nargs="+",
        help="竞品账号主页 URL（支持多个，用空格分隔，与 --file 二选一）",
    )
    parser.add_argument(
        "--file", "-f",
        help="读取 URL 列表的文本文件（每行一个 URL，与 --urls 二选一）",
    )
    parser.add_argument("--limit", type=int, default=10, help="每个账号采集数量上限（默认 10）")
    parser.add_argument("--no-content", action="store_true", help="不获取笔记正文（小红书，默认获取）")
    parser.add_argument("--no-comments", action="store_true", help="不获取评论（默认获取）")
    parser.add_argument("--max-comments", type=int, default=10, help="每条内容最多采集评论数（默认 10）")
    parser.add_argument("--visible", action="store_true", help="显示浏览器窗口（默认无头模式）")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径")

    args = parser.parse_args()

    # 收集 URL：优先从文件读取，否则用 --urls
    urls = []
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            for line in f:
                url = line.strip()
                if url and not url.startswith("#"):
                    urls.append(url)
        print(f"从文件读取到 {len(urls)} 个 URL", file=sys.stderr)
    elif args.urls:
        urls = args.urls
    else:
        parser.error("请提供 --urls 或 --file 参数")

    async def run_all():
        results = []
        for idx, url in enumerate(urls):
            if idx > 0:
                delay = random.uniform(2, 4)
                print(f"  ⏳ 账号采集间隔（等待 {delay:.1f}s）", file=sys.stderr)
                time.sleep(delay)
            try:
                platform = detect_platform(url)
                print(f"\n[{idx+1}/{len(urls)}] 正在采集 {platform} 账号: {url}", file=sys.stderr)
                account_data = await scrape_account(
                    identifier=url,
                    limit=args.limit,
                    fetch_comments=not args.no_comments,
                    max_comments=args.max_comments,
                    headless=not args.visible,
                    no_content=args.no_content,
                )
                results.append(account_data)
                print(f"  ✓ 完成: {account_data['author']} ({account_data['total_collected']} 条)", file=sys.stderr)
            except Exception as e:
                print(f"  ✗ 采集失败: {e}", file=sys.stderr)
                results.append({"platform": "unknown", "url": url, "error": str(e)})

        from datetime import datetime
        output = {
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_accounts": len(results),
            "accounts": results,
        }
        return output

    output = asyncio.run(run_all())

    write_output(output, args.output)


if __name__ == "__main__":
    main()
