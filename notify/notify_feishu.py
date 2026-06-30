"""
飞书通知脚本 - 将采集到的竞品/热搜数据发送到飞书群

用法：
    # 采集并发送（一步到位）
    python weibo_scraper.py --limit 5 -o temp.json && python notify_feishu.py -i temp.json

    # 或先保存再发送
    python competitor_monitor.py -f urls.txt -o result.json
    python notify_feishu.py -i result.json

    # 指定 Webhook（不指定则用默认的）
    python notify_feishu.py -i result.json --webhook https://open.feishu.cn/open-apis/bot/v2/hook/xxx
"""

import argparse
import json
import os
import sys
from datetime import datetime

try:
    import requests
except ImportError:
    print("需要安装 requests: pip install requests", file=sys.stderr)
    sys.exit(1)

# 从 .env 读取配置
DEFAULT_WEBHOOK = ""
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.isfile(dotenv_path):
    with open(dotenv_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == "FEISHU_WEBHOOK":
                    DEFAULT_WEBHOOK = v.strip()


def detect_type(data: dict) -> str | None:
    """自动识别数据类型。"""
    if "topics" in data:
        return "hot_search"       # weibo_hot_search.py
    if "accounts" in data:
        return "competitor"       # competitor_monitor.py
    if "weibos" in data:
        return "weibo_account"    # weibo_scraper.py
    if "notes" in data:
        return "xiaohongshu"      # xiaohongshu_scraper.py
    return None


def build_message(data_type: str, data: dict) -> dict:
    """根据数据类型构建飞书消息（富文本卡片）。"""
    collected_at = data.get("collected_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    if data_type == "hot_search":
        return _build_hot_search(data, collected_at)
    elif data_type == "competitor":
        return _build_competitor(data, collected_at)
    elif data_type == "weibo_account":
        return _build_weibo_account(data, collected_at)
    elif data_type == "xiaohongshu":
        return _build_xiaohongshu(data, collected_at)
    else:
        return _build_fallback(data, collected_at)


def _card_template(title: str, elements: list, color: str = "blue") -> dict:
    """飞书消息卡片模板。"""
    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": color,
            },
            "elements": elements,
        },
    }


def _md(content: str) -> dict:
    """辅助：飞书卡片的 markdown 元素。"""
    return {"tag": "markdown", "content": content}


def _hr() -> dict:
    """辅助：分隔线。"""
    return {"tag": "hr"}


def _build_hot_search(data: dict, collected_at: str) -> dict:
    topics = data.get("topics", [])
    title = f"🔥 微博热搜榜 ({collected_at})"
    elements = []

    for t in topics[:15]:
        rank = t.get("rank", "?")
        title_text = t.get("title", "")
        hot = t.get("hot_value", "")
        badge = f" **[{hot}]**" if hot else ""
        posts = t.get("posts", [])
        post_lines = []
        for p in posts[:2]:
            text = (p.get("text", "") or "")[:80]
            likes = p.get("likes", "?")
            comments = p.get("comments", "?")
            text_clean = text.replace("**", "").replace("__", "")
            post_lines.append(f"> 📝 {text_clean}  (👍{likes} 💬{comments})")
        ps = "\n".join(post_lines) if post_lines else "  (无微博数据)"
        elements.append(_md(f"**#{rank} {title_text}**{badge}\n{ps}"))
        elements.append(_hr())

    elements.append(_md(f"🕐 采集时间: {collected_at}"))
    return _card_template(title, elements, "red")


def _build_competitor(data: dict, collected_at: str) -> dict:
    accounts = data.get("accounts", [])
    title = f"📊 竞品账号监控 ({collected_at})"
    elements = []

    for a in accounts:
        platform = a.get("platform", "?")
        author = a.get("author", "?")
        url = a.get("url", "")
        total = a.get("total_collected", 0)
        icon = "📱" if platform == "xiaohongshu" else "📱"
        header = f"**{icon} {author}**（{platform}，共 {total} 条）"
        items = a.get("items", [])
        item_lines = []
        for item in items[:5]:
            if platform == "xiaohongshu":
                title_t = item.get("title", "")
                content = (item.get("content", "") or "")[:80]
                likes = item.get("likes", "?")
                comments = item.get("comments", "?")
                text = content if content else title_t
                item_lines.append(f"> 📝 {text}  (👍{likes} 💬{comments})")
            else:
                text = (item.get("text", "") or "")[:80]
                likes = item.get("likes", "?")
                comments = item.get("comments", "?")
                reposts = item.get("reposts", "?")
                item_lines.append(f"> 📝 {text}  (转{reposts} 👍{likes} 💬{comments})")
        if item_lines:
            elements.append(_md(f"{header}\n" + "\n".join(item_lines)))
        else:
            elements.append(_md(f"{header}\n  (暂无数据)"))
        elements.append(_hr())

    if not accounts:
        elements.append(_md("(未采集到数据)"))

    elements.append(_md(f"🕐 采集时间: {collected_at}"))
    return _card_template(title, elements, "indigo")


def _build_weibo_account(data: dict, collected_at: str) -> dict:
    author = data.get("author", "?")
    total = data.get("total_collected", 0)
    weibos = data.get("weibos", [])
    title = f"📱 微博 @{author} 最新内容 ({collected_at})"

    elements = []
    for w in weibos[:10]:
        text = (w.get("text", "") or "")[:120]
        reposts = w.get("reposts", "?")
        comments = w.get("comments", "?")
        likes = w.get("likes", "?")
        cc = w.get("comments_list", [])
        comment_snippet = ""
        if cc:
            top = cc[0]
            comment_snippet = f"\n> 💬 {top.get('user', '')}: {top.get('content', '')[:40]}"
        elements.append(_md(
            f"📝 {text}\n"
            f"   🔄 {reposts}  👍 {likes}  💬 {comments}{comment_snippet}"
        ))
        elements.append(_hr())

    elements.append(_md(f"🕐 采集时间: {collected_at}"))
    return _card_template(title, elements, "blue")


def _build_xiaohongshu(data: dict, collected_at: str) -> dict:
    author = data.get("author", "?")
    total = data.get("total_collected", 0)
    notes = data.get("notes", [])
    title = f"📱 小红书 @{author} 最新内容 ({collected_at})"

    elements = []
    for n in notes[:10]:
        title_text = n.get("title", "")
        content = (n.get("content", "") or "")[:120]
        likes = n.get("likes", "?")
        collects = n.get("collects", "?")
        comments = n.get("comments", "?")
        cc = n.get("comments_list", [])
        comment_snippet = ""
        if cc:
            top = cc[0]
            comment_snippet = f"\n> 💬 {top.get('user', '')}: {top.get('content', '')[:40]}"
        body = content if content else title_text
        elements.append(_md(
            f"📝 {body}\n"
            f"   👍 {likes}  📂 {collects}  💬 {comments}{comment_snippet}"
        ))
        elements.append(_hr())

    elements.append(_md(f"🕐 采集时间: {collected_at}"))
    return _card_template(title, elements, "blue")


def _build_fallback(data: dict, collected_at: str) -> dict:
    """未知格式，直接 JSON 原文发送。"""
    return _card_template(f"📋 数据报告 ({collected_at})", [
        _md(f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)[:2000]}\n```"),
        _md(f"🕐 采集时间: {collected_at}"),
    ], "grey")


def send_to_feishu(webhook: str, message: dict) -> bool:
    """发送消息到飞书群。"""
    try:
        resp = requests.post(webhook, json=message, timeout=15)
        result = resp.json()
        if result.get("code") == 0:
            return True
        else:
            print(f"飞书 API 返回错误: {result}", file=sys.stderr)
            return False
    except requests.RequestException as e:
        print(f"发送失败: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="发送采集数据到飞书群")
    parser.add_argument("-i", "--input", required=True, help="JSON 文件路径（任意采集脚本的输出）")
    parser.add_argument("--webhook", default=DEFAULT_WEBHOOK, help="飞书自定义机器人 Webhook URL")
    parser.add_argument("--dry-run", action="store_true", help="仅预览消息，不发送")

    args = parser.parse_args()

    # 读取 JSON
    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 识别类型
    data_type = detect_type(data)
    if data_type:
        print(f"识别为: {data_type}", file=sys.stderr)
    else:
        print("未能识别数据类型，按通用格式发送", file=sys.stderr)

    # 构建消息
    message = build_message(data_type, data)

    if args.dry_run:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        print(json.dumps(message, ensure_ascii=False, indent=2))
        return

    # 发送
    ok = send_to_feishu(args.webhook, message)
    if ok:
        print("✅ 已发送到飞书群", file=sys.stderr)
    else:
        print("❌ 发送失败", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
