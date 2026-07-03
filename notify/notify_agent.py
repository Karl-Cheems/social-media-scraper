"""
发送采集数据到服务端 Agent - 替代/补充飞书推送
将采集到的数据通过 RPC 接口发送给 AI Agent 处理

用法：
    python notify_agent.py -i result.json
    python notify_agent.py -i result.json --url http://your-server:port/paopao/rpc

支持自动识别数据类型并标注 channel 和内容类型。
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
def _read_env(key: str) -> str:
    dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.isfile(dotenv_path):
        with open(dotenv_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() == key:
                        return v.strip()
    return ""

DEFAULT_URL = _read_env("AGENT_URL")
DEFAULT_SENDER = _read_env("AGENT_SENDER") or "ou_66f8c01a0c53113c68ced2a1685ddf72"
DEFAULT_CHAT = _read_env("AGENT_CHAT") or "ou_66f8c01a0c53113c68ced2a1685ddf72"


def detect_type(data: dict) -> str:
    """自动识别数据类型，返回中文标签。"""
    if "platforms" in data and "keywords" in data:
        return "关键词搜索"
    if "platforms" in data:
        return "全平台热搜"
    if "topics" in data:
        items = data.get("topics", [])
        if items and "hot_badge" in items[0]:
            return "抖音热榜"
        return "微博热搜"
    if "accounts" in data:
        return "竞品监控"
    if "weibos" in data:
        author = data.get("author", "")
        return f"微博账号数据（{author}）" if author else "微博账号数据"
    if "notes" in data:
        author = data.get("author", "")
        return f"小红书账号数据（{author}）" if author else "小红书账号数据"
    return "社交媒体数据"


def build_summary(data: dict, data_type: str) -> str:
    """构建发送给 Agent 的文本摘要。"""
    lines = [f"【{data_type}】{data.get('collected_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}"]

    if "platforms" in data and "keywords" in data:
        keywords = data.get("keywords", [])
        lines.append(f"关键词: {'、'.join(keywords)}")
        for p in data["platforms"]:
            platform = p.get("platform", "")
            keyword = p.get("keyword", "")
            items = p.get("items", [])
            name = "微博" if platform == "weibo" else "小红书"
            lines.append(f"\n【{name} · {keyword}】（{len(items)} 条）")
            for item in items[:5]:
                text = (item.get("text", "") or item.get("title", "") or "")[:80]
                likes = item.get("likes", "?")
                comments_cnt = item.get("comments", "?")
                lines.append(f"  {text} (👍{likes} 💬{comments_cnt})")
                cc = item.get("comments_list", [])
                for c in cc[:3]:
                    lines.append(f"    💬 {c.get('user', '')}: {(c.get('content', '') or '')[:40]}")

    elif "platforms" in data:
        platforms = data.get("platforms", [])
        for p in platforms:
            platform = p.get("platform", "?")
            name = "抖音" if platform == "douyin" else "微博" if platform == "weibo" else platform
            topics = p.get("topics", [])
            lines.append(f"\n═══ {name}热榜（共{len(topics)}条）═══")
            for t in topics[:20]:
                rank = t.get("rank", "?")
                title = t.get("title", "")
                hot = t.get("hot_value", "")
                badge = t.get("hot_badge", "") or ""
                hot_str = f"({hot})" if hot else ""
                badge_str = f"[{badge}]" if badge else ""
                lines.append(f"#{rank} {title} {hot_str}{badge_str}")
                if platform == "weibo":
                    answer = t.get("zhishou_answer") or {}
                    answer_text = (answer.get("text", "") or "")[:200]
                    if answer_text:
                        lines.append(f"  🤖 {answer_text}")

    elif "topics" in data:
        data_type_label = detect_type(data)
        for t in data["topics"][:20]:
            rank = t.get("rank", "?")
            title = t.get("title", "")
            hot = t.get("hot_value", "")
            badge = t.get("hot_badge", "") or ""
            hot_str = f"({hot})" if hot else ""
            badge_str = f"[{badge}]" if badge else ""
            lines.append(f"\n#{rank} {title} {hot_str}{badge_str}")
            if data_type_label != "抖音热榜":
                posts = t.get("posts", [])
                for p in posts[:3]:
                    text = (p.get("text", "") or "")[:100]
                    likes = p.get("likes", "?")
                    comments = p.get("comments", "?")
                    lines.append(f"  {text} (👍{likes} 💬{comments})")

    elif "accounts" in data:
        for a in data["accounts"]:
            platform = a.get("platform", "?")
            author = a.get("author", "?")
            total = a.get("total_collected", 0)
            lines.append(f"\n【{author}】（{platform}，共{total}条）")
            for item in a.get("items", [])[:5]:
                if platform == "xiaohongshu":
                    text = item.get("content", "") or item.get("title", "")
                    likes = item.get("likes", "?")
                    comments = item.get("comments", "?")
                    lines.append(f"  📝 {(text or '')[:80]} (👍{likes} 💬{comments})")
                else:
                    text = item.get("text", "") or ""
                    likes = item.get("likes", "?")
                    reposts = item.get("reposts", "?")
                    comments = item.get("comments", "?")
                    lines.append(f"  📝 {(text or '')[:80]} (转{reposts} 👍{likes} 💬{comments})")

    elif "weibos" in data:
        author = data.get("author", "?")
        lines.append(f"\n账号: {author}")
        for w in data["weibos"][:10]:
            text = (w.get("text", "") or "")[:120]
            reposts = w.get("reposts", "?")
            comments = w.get("comments", "?")
            likes = w.get("likes", "?")
            lines.append(f"\n📝 {text}")
            lines.append(f"   🔄{reposts}  👍{likes}  💬{comments}")
            cc = w.get("comments_list", [])
            for c in cc[:3]:
                lines.append(f"   💬 {c.get('user', '')}: {(c.get('content', '') or '')[:50]}")

    elif "notes" in data:
        author = data.get("author", "?")
        lines.append(f"\n账号: {author}")
        for n in data["notes"][:10]:
            content = n.get("content", "") or n.get("title", "")
            likes = n.get("likes", "?")
            collects = n.get("collects", "?")
            comments = n.get("comments", "?")
            lines.append(f"\n📝 {(content or '')[:120]}")
            lines.append(f"   👍{likes}  📂{collects}  💬{comments}")
            cc = n.get("comments_list", [])
            for c in cc[:3]:
                lines.append(f"   💬 {c.get('user', '')}: {(c.get('content', '') or '')[:50]}")

    return "\n".join(lines)


def send(data: dict, server_url: str, sender_id: str, chat_id: str) -> bool:
    """发送数据到服务端 Agent。"""
    data_type = detect_type(data)

    # 构建摘要文本
    summary = build_summary(data, data_type)

    payload = {
        "channel": "feishu",
        "content": f"【{data_type}】\n\n{summary}",
        "sender_id": sender_id,
        "chat_id": chat_id,
    }

    try:
        resp = requests.post(server_url, json=payload, timeout=30)
        print(f"状态码: {resp.status_code}", file=sys.stderr)
        print(f"响应: {resp.text[:500]}", file=sys.stderr)
        return resp.status_code == 200
    except requests.RequestException as e:
        print(f"发送失败: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="发送采集数据到服务端 Agent")
    parser.add_argument("-i", "--input", required=True, help="JSON 文件路径（任意采集脚本的输出）")
    parser.add_argument("--url", default=DEFAULT_URL, help="Agent RPC 接口地址")
    parser.add_argument("--sender", default=DEFAULT_SENDER, help="sender_id")
    parser.add_argument("--chat", default=DEFAULT_CHAT, help="chat_id")
    parser.add_argument("--dry-run", action="store_true", help="仅预览摘要，不发送")

    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    data_type = detect_type(data)
    summary = build_summary(data, data_type)
    print(f"识别类型: {data_type}", file=sys.stderr)
    print(f"数据概要: {len(summary)} 字符", file=sys.stderr)

    if args.dry_run:
        print(summary)
        return

    ok = send(data, args.url, args.sender, args.chat)
    if ok:
        print("✅ 已发送到服务端 Agent", file=sys.stderr)
    else:
        print("❌ 发送失败", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
