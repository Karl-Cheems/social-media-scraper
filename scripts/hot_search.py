"""
微博+抖音 热搜合并采集脚本
分别调用 weibo_hot_search 和 douyin_hot_search 采集数据，
合并为一个带 platforms 字段的 JSON 输出。

支持三榜：微博热搜、微博文娱、抖音热榜

用法：
    python hot_search.py --weibo-limit 10 --douyin-limit 10
    python hot_search.py --weibo-board both --douyin-limit 15
    python hot_search.py -o result.json --visible
"""

import argparse
import asyncio
import importlib
import json
import os
import random
import sys
# ── 路径修补 ──
_scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
import time
from datetime import datetime

from common import write_output


def main():
    parser = argparse.ArgumentParser(
        description="微博热搜/文娱 + 抖音热榜 合并采集工具"
    )
    parser.add_argument("--weibo-limit", type=int, default=10, help="微博热搜数量（默认 10）")
    parser.add_argument("--weibo-board", default="both",
                        choices=["hot", "entertainment", "both"],
                        help="微博榜单: hot=热搜, entertainment=文娱, both=两者（默认 both）")
    parser.add_argument("--douyin-limit", type=int, default=10, help="抖音热榜数量（默认 10）")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径")

    args = parser.parse_args()

    weibo_limit = args.weibo_limit
    douyin_limit = args.douyin_limit
    headless = False

    # 确保 scripts 目录在 sys.path 中
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    platforms_data = []

    # ── 1. 抖音热榜 ──────────────────────────────────
    print("=" * 50, file=sys.stderr)
    print("▶ 阶段 1/3：采集抖音热榜", file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    try:
        dy = importlib.import_module("douyin_hot_search")
        dy_results = asyncio.run(dy.scrape_hot_search(
            limit=douyin_limit,
            headless=headless,
        ))
        dy_output = {
            "platform": "douyin",
            "total_topics": len(dy_results),
            "topics": [r.model_dump(mode="json") if hasattr(r, "model_dump") else r for r in dy_results],
        }
        platforms_data.append(dy_output)
        print(f"  抖音热榜完成：{len(dy_results)} 条", file=sys.stderr)
    except Exception as e:
        print(f"  ❌ 抖音采集失败: {e}", file=sys.stderr)
        platforms_data.append({
            "platform": "douyin",
            "total_topics": 0,
            "topics": [],
            "error": str(e),
        })

    # ── 平台切换延迟 ──
    delay = random.uniform(10, 15)
    print(f"  ⏳ 平台切换间隔（等待 {delay:.1f}s）", file=sys.stderr)
    time.sleep(delay)

    # ── 2. 微博热搜/文娱 ──────────────────────────────
    wb = importlib.import_module("weibo_hot_search")
    boards_to_run = ["hot", "entertainment"] if args.weibo_board == "both" else [args.weibo_board]

    for b in boards_to_run:
        board_name = "热搜榜" if b == "hot" else "文娱榜"
        print("=" * 50, file=sys.stderr)
        print(f"▶ 阶段 2：采集微博{board_name}", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        try:
            batch = asyncio.run(wb.scrape_hot_search(
                limit=weibo_limit,
                board=b,
                headless=headless,
            ))
            wb_output = {
                "platform": "weibo",
                "board": b,
                "total_topics": len(batch),
                "topics": [r.model_dump(mode="json") for r in batch],
            }
            platforms_data.append(wb_output)
            print(f"  微博{board_name}完成：{len(batch)} 条", file=sys.stderr)
        except Exception as e:
            print(f"  ❌ 微博{board_name}采集失败: {e}", file=sys.stderr)
            platforms_data.append({
                "platform": "weibo",
                "board": b,
                "total_topics": 0,
                "topics": [],
                "error": str(e),
            })

        if len(boards_to_run) > 1 and b == boards_to_run[0]:
            delay = random.uniform(5, 10)
            print(f"  ⏳ 榜单切换间隔（等待 {delay:.1f}s）", file=sys.stderr)
            time.sleep(delay)

    # ── 合并输出 ──────────────────────────────────────
    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output = {
        "collected_at": collected_at,
        "source": "hot_search",
        "platforms": platforms_data,
    }

    write_output(output, args.output)


if __name__ == "__main__":
    main()
