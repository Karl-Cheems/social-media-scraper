"""
社交媒体监控工具 — 主入口

快速启动图形界面：
    python main.py

直接运行采集脚本（跳过 GUI）：
    python scripts/keyword_search.py --keywords "气泡水" --platforms xiaohongshu
    python scripts/weibo_hot_search.py --limit 10
    python scripts/url_detail.py --url https://weibo.com/xxx

打包为单文件：
    py -3.12 -m PyInstaller 社交监控工具.spec
"""

import os
import sys

_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from social_monitor_gui import main

if __name__ == "__main__":
    main()
