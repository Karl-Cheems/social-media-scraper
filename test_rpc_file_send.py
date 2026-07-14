"""
测试向 RPC 端点发送文件的多种方式
"""
import json, base64, os, sys, tempfile

try:
    import requests
except ImportError:
    print("pip install requests")
    sys.exit(1)

URL = "http://101.42.14.156:8443/paopao/rpc"
SENDER = "ou_66f8c01a0c53113c68ced2a1685ddf72"
CHAT = "ou_66f8c01a0c53113c68ced2a1685ddf72"


def test_name(n):
    print(f"\n{'='*60}")
    print(f"  测试 {n}")
    print(f"{'='*60}")


def report(r):
    print(f"  状态码: {r.status_code}")
    print(f"  响应体: {r.text[:800]}")
    # 尝试解析 JSON
    try:
        j = r.json()
        print(f"  JSON: {json.dumps(j, ensure_ascii=False, indent=2)[:600]}")
    except:
        pass
    print()


# ── 准备测试数据 ──
test_text = "这是一条来自 RPC 文件发送测试的消息"
test_file_content = "hello, this is a test file content\nline2\nline3"
test_file_b64 = base64.b64encode(test_file_content.encode()).decode()

# 先拿一份真实的采集数据作为 raw_data（从已有的 JSON 取）
sample_data = {
    "collected_at": "2026-07-09 16:00:00",
    "source": "test",
    "data": {"platform": "test", "text": "测试数据", "author": "测试"}
}

tmp_file = os.path.join(tempfile.gettempdir(), "rpc_test_file.txt")
with open(tmp_file, "w", encoding="utf-8") as f:
    f.write(test_file_content)


# ════════════════════════════════════════
# 方式 1: 最基本的 channel=rpc + content (无文件, 纯文本)
# 验证 server 是否正常响应
# ════════════════════════════════════════
test_name("1 - 基础 channel=rpc 纯文本（验证连通性）")
r = requests.post(URL, json={
    "channel": "rpc",
    "content": test_text,
    "sender_id": SENDER,
    "chat_id": CHAT,
}, timeout=30)
report(r)


# ════════════════════════════════════════
# 方式 2: channel=rpc + files(base64)
# 参考格式: {"channel":"rpc","content":"看这个文件","files":[{"name":"test.txt","content":"base64"}]}
# ════════════════════════════════════════
test_name("2 - channel=rpc + content + files(base64)")
r = requests.post(URL, json={
    "channel": "rpc",
    "content": test_text,
    "sender_id": SENDER,
    "chat_id": CHAT,
    "files": [{"name": "test.txt", "content": test_file_b64}]
}, timeout=30)
report(r)


# ════════════════════════════════════════
# 方式 3: channel=rpc + 多个文件 (base64)
# ════════════════════════════════════════
test_name("3 - channel=rpc + 多个文件(base64)")
r = requests.post(URL, json={
    "channel": "rpc",
    "content": test_text,
    "sender_id": SENDER,
    "chat_id": CHAT,
    "files": [
        {"name": "hello.txt", "content": test_file_b64},
        {"name": "data.json", "content": base64.b64encode(json.dumps({"a": 1, "b": 2}, ensure_ascii=False).encode()).decode()},
    ]
}, timeout=30)
report(r)


# ════════════════════════════════════════
# 方式 4: multipart 上传文件
# 参考: curl -F "channel=rpc" -F "content=看这个文件" -F "files=@/path/to/test.txt"
# ════════════════════════════════════════
test_name("4 - multipart 上传文件")
with open(tmp_file, "rb") as f:
    r = requests.post(URL, data={
        "channel": "rpc",
        "content": test_text,
        "sender_id": SENDER,
        "chat_id": CHAT,
    }, files=[
        ("files", ("test.txt", f, "text/plain"))
    ], timeout=30)
report(r)


# ════════════════════════════════════════
# 方式 5: multipart 多个文件
# ════════════════════════════════════════
test_name("5 - multipart 多个文件")
tmp_file2 = os.path.join(tempfile.gettempdir(), "rpc_test_data.json")
with open(tmp_file2, "w", encoding="utf-8") as f:
    json.dump({"key": "value", "num": 42}, f)

with open(tmp_file, "rb") as f1, open(tmp_file2, "rb") as f2:
    r = requests.post(URL, data={
        "channel": "rpc",
        "content": test_text,
        "sender_id": SENDER,
        "chat_id": CHAT,
    }, files=[
        ("files", ("test.txt", f1, "text/plain")),
        ("files", ("data.json", f2, "application/json")),
    ], timeout=30)
report(r)


# ════════════════════════════════════════
# 方式 6: 模仿 notify_agent.py 的发送方式, 但是把 raw_data 作为文件发
# channel=feishu + files(base64)
# ════════════════════════════════════════
test_name("6 - channel=feishu + files(base64)")
raw_json = json.dumps(sample_data, ensure_ascii=False)
r = requests.post(URL, json={
    "channel": "feishu",
    "content": f"【测试】\n{test_text}",
    "sender_id": SENDER,
    "chat_id": CHAT,
    "files": [{"name": "采集数据.json", "content": base64.b64encode(raw_json.encode()).decode()}],
}, timeout=30)
report(r)


# ════════════════════════════════════════
# 方式 7: channel=rpc, 但 content 为空, 把采集数据全部当作文件发
# ════════════════════════════════════════
test_name("7 - channel=rpc, content放摘要, files放完整数据")
r = requests.post(URL, json={
    "channel": "rpc",
    "content": f"【测试摘要】{test_text}",
    "sender_id": SENDER,
    "chat_id": CHAT,
    "files": [{"name": "full_data.json", "content": base64.b64encode(raw_json.encode()).decode()}],
}, timeout=30)
report(r)


# ════════════════════════════════════════
# 方式 8: 和方式2相同, 但用原始方式发(不指定sender/chat, 纯参考格式)
# ════════════════════════════════════════
test_name("8 - 最简格式: channel=rpc + content + files(base64), 无sender/chat")
r = requests.post(URL, json={
    "channel": "rpc",
    "content": test_text,
    "files": [{"name": "minimal.txt", "content": test_file_b64}]
}, timeout=30)
report(r)


print("所有测试完成!")
