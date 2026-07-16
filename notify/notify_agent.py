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
import math
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
DEFAULT_PREFIX = _read_env("AGENT_PREFIX") or "使用social-intelligence-refinery处理以下内容"


def detect_type(data: dict) -> str:
    """自动识别数据类型，返回中文标签。"""
    if "source" in data and data.get("source") == "url_detail":
        d = data.get("data", {})
        plat = d.get("platform", "")
        return f"内容详情（{plat}）"

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
    if "source" in data and data.get("source") == "url_detail":
        d = data.get("data", {})
        plat = d.get("platform", "")
        return f"内容详情（{plat}）"
    if "notes" in data:
        author = data.get("author", "")
        return f"小红书账号数据（{author}）" if author else "小红书账号数据"
    return "社交媒体数据"


def detect_type_key(data: dict) -> str:
    """返回机器可读的数据类型 key。"""
    if "source" in data and data.get("source") == "url_detail":
        return "detail"
    if "source" in data and data.get("source") == "url_detail":
        d = data.get("data", {})
        plat = d.get("platform", "")
        return f"内容详情（{plat}）"

    if "platforms" in data and "keywords" in data:
        return "keyword"
    if "platforms" in data:
        return "hot"
    if "topics" in data:
        return "hot"
    if "accounts" in data or "weibos" in data or "notes" in data:
        return "account"
    return "unknown"


def build_summary(data: dict, data_type: str) -> str:
    """构建发送给 Agent 的文本摘要。"""
    lines = [f"【{data_type}】{data.get('collected_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}"]

    if "source" in data and data.get("source") == "url_detail":
        d = data.get("data", {})
        plat = d.get("platform", "")
        lines.append(f"平台: {plat}")
        lines.append(f"标题: {d.get('title', '')}")
        text = d.get('text', '') or ''
        lines.append(f"正文: {text[:500]}")
        likes = d.get('likes', '?')
        comments_cnt = d.get('comments', '?')
        author = d.get('author', '?')
        img = d.get('comment_images', 0)
        lines.append(f"作者: {author}  👍{likes}  💬{comments_cnt}" + (f"  🖼️{img}" if img else ""))
        cc = d.get("comments_text", "")
        if cc:
            clines = cc.strip().split("\n")
            lines.append(f"\n评论（{len([l for l in clines if l and l != '---'])} 条）:")
            for l in clines[:120]:
                if l == "---":
                    lines.append(l)
                elif l.startswith("  回复:"):
                    lines.append(f"    ↳ {l[4:].strip()[:60]}")
                else:
                    lines.append(f"  💬 {l[:80]}")
        return "\n".join(lines)

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
                img_cnt = item.get("comment_images", 0)
                line = f"  {text} (👍{likes} 💬{comments_cnt})"
                if img_cnt:
                    line += f" 🖼️{img_cnt}"
                lines.append(line)
                cc = item.get("comments_text", "")
                if cc:
                    clines = cc.strip().split("\n")
                    shown = 0
                    for l in clines:
                        if shown >= 5:
                            break
                        if l == "---":
                            continue
                        if l.startswith("  回复:"):
                            lines.append(f"      ↳ {l[4:].strip()[:40]}")
                        else:
                            lines.append(f"      💬 {l[:40]}")
                            shown += 1

    elif "platforms" in data:
        platforms = data.get("platforms", [])
        for p in platforms:
            platform = p.get("platform", "?")
            board = p.get("board", "")
            if platform == "weibo":
                name = "微博热搜榜" if board == "hot" else "微博文娱榜" if board == "entertainment" else "微博"
            elif platform == "douyin":
                name = "抖音"
            else:
                name = platform
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
                    img_cnt = item.get("comment_images", 0)
                    line = f"  📝 {(text or '')[:80]} (👍{likes} 💬{comments})"
                    if img_cnt: line += f" 🖼️{img_cnt}"
                    lines.append(line)
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
            cc = w.get("comments_text", "")
            if cc:
                for l in cc.strip().split("\n")[:10]:
                    if l == "---":
                        continue
                    if l.startswith("  回复:"):
                        lines.append(f"     ↳ {l[4:].strip()[:50]}")
                    else:
                        lines.append(f"   💬 {l[:50]}")

    elif "notes" in data:
        author = data.get("author", "?")
        lines.append(f"\n账号: {author}")
        for n in data["notes"][:10]:
            content = n.get("content", "") or n.get("title", "")
            likes = n.get("likes", "?")
            collects = n.get("collects", "?")
            comments = n.get("comments", "?")
            img_cnt = n.get("comment_images", 0)
            line = f"   👍{likes}  📂{collects}  💬{comments}"
            if img_cnt: line += f"  🖼️{img_cnt}"
            lines.append(f"\n📝 {(content or '')[:120]}")
            lines.append(line)
            cc = n.get("comments_text", "")
            if cc:
                for l in cc.strip().split("\n")[:10]:
                    if l == "---":
                        continue
                    if l.startswith("  回复:"):
                        lines.append(f"     ↳ {l[4:].strip()[:50]}")
                    else:
                        lines.append(f"   💬 {l[:50]}")

    return "\n".join(lines)


def sanitize_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): sanitize_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_json(v) for v in value]
    return value


def send(data: dict, server_url: str, sender_id: str, chat_id: str,
         source_type: str | None = None,
         prefix: str | None = None) -> bool:
    """发送数据到服务端 Agent。

    Args:
        data: 采集的原始 JSON 数据
        server_url: Agent RPC 地址
        sender_id: 发送者 ID
        chat_id: 会话 ID
        source_type: 来源类型 (self/competitor/keyword/hot)，None 则自动识别
    """
    data = sanitize_json(data)
    data_type = detect_type(data)
    data_type_key = source_type or detect_type_key(data)

    # 把原始 JSON 转为文本
    raw_json_text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)

    payload = {
        "channel": "feishu",
        "content": f"{prefix or DEFAULT_PREFIX}\n\n{raw_json_text}",
        "sender_id": sender_id,
        "chat_id": chat_id,
        "data_type": data_type_key,       # 机器可读的类型：hot/keyword/account
        "source": {                        # 来源分类，供 Agent 技能路由
            "type": data_type_key,
            "label": data_type,
        },
        "raw_data": data,                  # 完整原始数据
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
    parser.add_argument("--source-type", choices=["self", "self_account", "competitor", "competitor_account", "keyword", "hot", "account", "detail"],
                        default=None, help="来源类型（自动识别如果不传）")
    parser.add_argument("--prefix", default=None, help="content 前缀提示词")
    parser.add_argument("--save-dir", default=None, help="保存原始 JSON 的目录（可选）")

    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    data_type = detect_type(data)
    summary = build_summary(data, data_type)
    print(f"识别类型: {data_type}", file=sys.stderr)
    print(f"来源类型: {args.source_type or '自动识别'}", file=sys.stderr)
    print(f"数据概要: {len(summary)} 字符", file=sys.stderr)

    # 保存原始 JSON 副本到指定目录
    save_dir = args.save_dir or os.environ.get("SOCIAL_MONITOR_DATA_DIR")
    if save_dir:
        source_key = args.source_type or detect_type_key(data)
        sub_map = {"hot": "hot", "keyword": "keyword", "account": "account",
                   "self": "account", "self_account": "account", "competitor": "account",
                   "competitor_account": "account"}
        sub = sub_map.get(source_key, "")
        target_dir = os.path.join(save_dir, sub) if sub else save_dir
        os.makedirs(target_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = os.path.join(target_dir, f"agent_{source_key}_{ts}.json")
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[保存原始数据] {save_path}", file=sys.stderr)

    if args.dry_run:
        print(summary)
        return

    ok = send(data, args.url, args.sender, args.chat, source_type=args.source_type, prefix=args.prefix)
    if ok:
        print("✅ 已发送到服务端 Agent", file=sys.stderr)
    else:
        print("❌ 发送失败", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
