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
DEFAULT_SENDER = ""
DEFAULT_CHAT = ""
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.isfile(dotenv_path):
    with open(dotenv_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                if k == "FEISHU_WEBHOOK":
                    DEFAULT_WEBHOOK = v.strip()
                elif k == "FEISHU_SENDER":
                    DEFAULT_SENDER = v.strip()
                elif k == "FEISHU_CHAT":
                    DEFAULT_CHAT = v.strip()


def detect_type(data: dict) -> str | None:
    """自动识别数据类型。"""
    if "platforms" in data and "keywords" in data:
        return "keyword_search"       # keyword_search 多平台关键词搜索
    if "platforms" in data:
        return "merged_hot"       # hot_search.py 合并热搜
    if "topics" in data:
        # 检查是否有 hot_badge 字段 → 抖音热搜
        items = data.get("topics", [])
        if items and "hot_value" in items[0] and "hot_badge" in items[0]:
            return "douyin_hot"
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

    if data_type == "merged_hot":
        return _build_merged_hot(data, collected_at)
    elif data_type == "keyword_search":
        return _build_keyword_search(data, collected_at)
    elif data_type == "hot_search":
        return _build_hot_search(data, collected_at)
    elif data_type == "douyin_hot":
        return _build_douyin_hot(data, collected_at)
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
    board = data.get("board", "hot")
    title = f"🔥 {'微博热搜榜' if board == 'hot' else '微博文娱榜'} ({collected_at})"
    elements = []

    for t in topics[:15]:
        rank = t.get("rank", "?")
        title_text = t.get("title", "")
        hot = t.get("hot_value", "")
        badge = f" **[{hot}]**" if hot else ""
        answer = t.get("zhishou_answer") or {}
        answer_text = (answer.get("text", "") or "")[:200]
        answer_line = f"\n> 🤖 {answer_text}" if answer_text else ""
        elements.append(_md(f"**#{rank} {title_text}**{badge}{answer_line}"))
        elements.append(_hr())

    elements.append(_md(f"🕐 采集时间: {collected_at}"))
    return _card_template(title, elements, "red")


def _build_douyin_hot(data: dict, collected_at: str) -> dict:
    topics = data.get("topics", [])
    title = f"🎵 抖音热榜 ({collected_at})"
    elements = []

    for t in topics[:15]:
        rank = t.get("rank", "?")
        title_text = t.get("title", "")
        hot = t.get("hot_value", "")
        badge = t.get("hot_badge", "")
        badge_str = f" **[{badge}]**" if badge else ""
        hot_str = f" **({hot})**" if hot else ""
        elements.append(_md(f"**#{rank} {title_text}**{badge_str}{hot_str}"))
        elements.append(_hr())

    elements.append(_md(f"🕐 采集时间: {collected_at}"))
    return _card_template(title, elements, "orange")


def _build_merged_hot(data: dict, collected_at: str) -> dict:
    """
    合并热搜卡片：先展示抖音热榜（橙色），再展示微博热搜（红色），再展示微博文娱榜（紫色）。
    """
    platforms = data.get("platforms", [])
    title = f"🔥 全平台热搜榜 ({collected_at})"
    elements = []

    # 找各平台数据
    douyin = next((p for p in platforms if p.get("platform") == "douyin"), None)
    weibo_hot = next((p for p in platforms if p.get("platform") == "weibo" and p.get("board") == "hot"), None)
    weibo_ent = next((p for p in platforms if p.get("platform") == "weibo" and p.get("board") == "entertainment"), None)

    # ── 抖音热榜 ──
    if douyin:
        dy_topics = douyin.get("topics", [])
        if dy_topics:
            elements.append(_md("**🎵 抖音热榜**"))
            for t in dy_topics[:15]:
                rank = t.get("rank", "?")
                title_text = t.get("title", "")
                hot = t.get("hot_value", "")
                badge = t.get("hot_badge", "")
                badge_str = f" **[{badge}]**" if badge else ""
                hot_str = f" ({hot})" if hot else ""
                elements.append(_md(f"**#{rank} {title_text}**{badge_str}{hot_str}"))
            elements.append(_hr())

    # ── 微博热搜 ──
    if weibo_hot:
        wb_topics = weibo_hot.get("topics", [])
        if wb_topics:
            elements.append(_md("**🔥 微博热搜**"))
            for t in wb_topics[:15]:
                rank = t.get("rank", "?")
                title_text = t.get("title", "")
                hot = t.get("hot_value", "")
                badge = f" **[{hot}]**" if hot else ""
                answer = t.get("zhishou_answer") or {}
                answer_text = (answer.get("text", "") or "")[:150]
                answer_line = f"\n> 🤖 {answer_text}" if answer_text else ""
                elements.append(_md(f"**#{rank} {title_text}**{badge}{answer_line}"))
            elements.append(_hr())

    # ── 微博文娱榜 ──
    if weibo_ent:
        wb_topics = weibo_ent.get("topics", [])
        if wb_topics:
            elements.append(_md("**🎬 微博文娱榜**"))
            for t in wb_topics[:15]:
                rank = t.get("rank", "?")
                title_text = t.get("title", "")
                hot = t.get("hot_value", "")
                badge = f" **[{hot}]**" if hot else ""
                answer = t.get("zhishou_answer") or {}
                answer_text = (answer.get("text", "") or "")[:150]
                answer_line = f"\n> 🤖 {answer_text}" if answer_text else ""
                elements.append(_md(f"**#{rank} {title_text}**{badge}{answer_line}"))
            elements.append(_hr())

    if not elements:
        elements.append(_md("(未采集到数据)"))

    elements.append(_md(f"🕐 采集时间: {collected_at}"))
    return _card_template(title, elements, "red")
                badge = f" **[{hot}]**" if hot else ""
                posts = t.get("posts", [])
                post_lines = []
                for p in posts[:2]:
                    text = (p.get("text", "") or "")[:80]
                    likes = p.get("likes", "?")
                    comments_cnt = p.get("comments", "?")
                    text_clean = text.replace("**", "").replace("__", "")
                    line = f"> 📝 {text_clean}  (👍{likes} 💬{comments_cnt})"
                    cc = p.get("comments_list", [])
                    for c in cc[:3]:
                        line += f"\n> 💬 {c.get('user', '')}: {(c.get('content', '') or '')[:40]}"
                    post_lines.append(line)
                ps = "\n".join(post_lines) if post_lines else "  (无微博数据)"
                elements.append(_md(f"**#{rank} {title_text}**{badge}\n{ps}"))
            elements.append(_hr())

    elements.append(_md(f"🕐 采集时间: {collected_at}"))

    # 两条数据都没有
    if not elements:
        elements.append(_md("(未采集到数据)"))

    return _card_template(title, elements, "red")


def _build_keyword_search(data: dict, collected_at: str) -> dict:
    keywords = data.get("keywords", [])
    platforms = data.get("platforms", [])
    kw_str = "、".join(keywords[:5])
    if len(keywords) > 5:
        kw_str += f" 等{len(keywords)}个关键词"
    title = f"🔍 关键词搜索结果 ({collected_at})"
    elements = [_md(f"**搜索关键词：** {kw_str}")]
    for p in platforms:
        platform = p.get("platform", "")
        keyword = p.get("keyword", "")
        items = p.get("items", [])
        icon = "📱" if platform == "weibo" else "📕"
        name = "微博" if platform == "weibo" else "小红书"
        elements.append(_md(f"\n**{icon} {name} · {keyword}**（{len(items)} 条）"))
        for item in items[:5]:
            text = (item.get("text", "") or item.get("title", "") or "")[:80]
            likes = item.get("likes", "?")
            comments_cnt = item.get("comments", "?")
            collects = item.get("collects", "?")
            line = f"> 📝 {text}"
            if platform == "weibo":
                line += f"  (👍{likes} 💬{comments_cnt})"
            else:
                line += f"  (👍{likes} 📂{collects} 💬{comments_cnt})"
            cc = item.get("comments_list", [])
            for c in cc[:3]:
                line += f"\n> 💬 {c.get('user', '')}: {(c.get('content', '') or '')[:40]}"
            elements.append(_md(line))
        elements.append(_hr())
    elements.append(_md(f"🕐 采集时间: {collected_at}"))
    return _card_template(title, elements, "indigo")


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
            cc = item.get("comments_list", [])
            comment_lines = ""
            for c in cc[:3]:
                comment_lines += f"\n> 💬 {c.get('user', '')}: {(c.get('content', '') or '')[:40]}"
            if platform == "xiaohongshu":
                title_t = (item.get("title", "") or "")
                content = (item.get("content", "") or "")[:80]
                likes = item.get("likes", "?")
                collects = item.get("collects", "?")
                comments_cnt = item.get("comments", "?")
                pub_at = item.get("published_at", "")
                date_str = f" [{pub_at}]" if pub_at else ""
                display = f"**{title_t}**{date_str}" if title_t else ""
                if content and content != title_t:
                    display += f"\n> {content}"
                item_lines.append(f"> 📝 {display}\n>    👍{likes}  📂{collects}  💬{comments_cnt}{comment_lines}")
            else:
                wtext = (item.get("text", "") or "")[:80]
                likes = item.get("likes", "?")
                comments_cnt = item.get("comments", "?")
                reposts = item.get("reposts", "?")
                item_lines.append(f"> 📝 {wtext}  (转{reposts} 👍{likes} 💬{comments_cnt}){comment_lines}")
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
        comment_lines = ""
        for c in cc[:3]:
            comment_lines += f"\n> 💬 {c.get('user', '')}: {(c.get('content', '') or '')[:40]}"
        elements.append(_md(
            f"📝 {text}\n"
            f"   🔄 {reposts}  👍 {likes}  💬 {comments}{comment_lines}"
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
        comment_lines = ""
        for c in cc[:3]:
            comment_lines += f"\n> 💬 {c.get('user', '')}: {(c.get('content', '') or '')[:40]}"
        body = content if content else title_text
        elements.append(_md(
            f"📝 {body}\n"
            f"   👍 {likes}  📂 {collects}  💬 {comments}{comment_lines}"
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


def send_to_feishu(webhook: str, message: dict, sender_id: str = "", chat_id: str = "") -> bool:
    """发送消息到飞书群。"""
    payload = message
    # 如果提供了 sender_id / chat_id，注入到 payload 中
    if sender_id or chat_id:
        if "card" not in payload:
            payload.setdefault("card", {})
        extra = {}
        if sender_id:
            extra["sender_id"] = sender_id
        if chat_id:
            extra["chat_id"] = chat_id
        payload.setdefault("extra", extra)
    try:
        resp = requests.post(webhook, json=payload, timeout=15)
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
    parser.add_argument("--sender", default=DEFAULT_SENDER, help="sender_id（飞书 open_id）")
    parser.add_argument("--chat", default=DEFAULT_CHAT, help="chat_id（飞书群/会话 ID）")
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
    ok = send_to_feishu(args.webhook, message, sender_id=args.sender, chat_id=args.chat)
    if ok:
        print("✅ 已发送到飞书群", file=sys.stderr)
    else:
        print("❌ 发送失败", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
