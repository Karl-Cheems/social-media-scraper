"""
验证文件是否真的被 LLM（channel=rpc）接收并能读取
"""
import json, base64, sys, time

try:
    import requests
except ImportError:
    print("pip install requests")
    sys.exit(1)

URL = "http://101.42.14.156:8443/paopao/rpc"

# ── 准备测试文件内容 ──
test_content = "这是一篇关于AI行业的最新分析报告。\n2026年Q2，大模型领域发生了多项重大变化...\n字节跳动发布了最新的豆包4.0，在推理能力上有了显著提升。"

# ── 测试1: 文件内容直接写在 content 里发给 LLM ──
print("=" * 60)
print("  测试 A: channel=rpc, files(base64), 让LLM读文件并回复")
print("=" * 60)

r = requests.post(URL, json={
    "channel": "rpc",
    "content": "请读取我发给你的文件，告诉我里面写了什么内容。用中文回复。",
    "sender_id": "ou_66f8c01a0c53113c68ced2a1685ddf72",
    "chat_id": "ou_66f8c01a0c53113c68ced2a1685ddf72",
    "files": [
        {
            "name": "AI行业报告.txt",
            "content": base64.b64encode(test_content.encode()).decode()
        }
    ]
}, timeout=60)

print(f"状态码: {r.status_code}")
try:
    j = r.json()
    print(f"响应: {json.dumps(j, ensure_ascii=False, indent=2)[:2000]}")
except:
    print(f"原始响应: {r.text[:2000]}")
print()


# ── 测试2: channel=rpc, 用 multipart 发送 ──
print("=" * 60)
print("  测试 B: multipart 上传文件, 让LLM读文件并回复")
print("=" * 60)

import tempfile, os
tmp = os.path.join(tempfile.gettempdir(), "analysis_report.txt")
with open(tmp, "w", encoding="utf-8") as f:
    f.write(test_content)

with open(tmp, "rb") as f:
    r = requests.post(URL, data={
        "channel": "rpc",
        "content": "请读取我发给你的文件，告诉我里面写了什么。用中文回复。",
        "sender_id": "ou_66f8c01a0c53113c68ced2a1685ddf72",
        "chat_id": "ou_66f8c01a0c53113c68ced2a1685ddf72",
    }, files=[
        ("files", ("analysis_report.txt", f, "text/plain; charset=utf-8"))
    ], timeout=60)

print(f"状态码: {r.status_code}")
try:
    j = r.json()
    print(f"响应: {json.dumps(j, ensure_ascii=False, indent=2)[:2000]}")
except:
    print(f"原始响应: {r.text[:2000]}")
print()


# ── 测试3: 模拟采集数据JSON作为文件发过去 ──
print("=" * 60)
print("  测试 C: 模拟采集数据JSON作为文件, 让LLM总结")
print("=" * 60)

sample_data = {
    "collected_at": "2026-07-09 16:30:00",
    "source": "keyword",
    "keywords": ["AI", "大模型"],
    "platforms": [{
        "platform": "weibo",
        "keyword": "AI",
        "items": [
            {"text": "字节跳动发布豆包4.0，推理能力大幅提升", "likes": 15230, "comments": 3400},
            {"text": "OpenAI宣布GPT-5将于年底发布", "likes": 8900, "comments": 2100},
        ]
    }]
}

r = requests.post(URL, json={
    "channel": "rpc",
    "content": "请读取这个采集数据文件，给我一份总结报告，列出每个平台的热门话题和互动数据。用中文回复。",
    "sender_id": "ou_66f8c01a0c53113c68ced2a1685ddf72",
    "chat_id": "ou_66f8c01a0c53113c68ced2a1685ddf72",
    "files": [
        {
            "name": "采集数据_AI大模型.json",
            "content": base64.b64encode(json.dumps(sample_data, ensure_ascii=False).encode()).decode()
        }
    ]
}, timeout=60)

print(f"状态码: {r.status_code}")
try:
    j = r.json()
    print(f"响应: {json.dumps(j, ensure_ascii=False, indent=2)[:2000]}")
except:
    print(f"原始响应: {r.text[:2000]}")
print()


print("全部测试完成！")
