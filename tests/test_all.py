"""
全面测试脚本 — 依次测试每个功能
每个测试独立运行，捕获输出不阻塞
"""
import subprocess, sys, os, json, time

BASE = "D:/Users/Desktop/网络热点搜集"

def run_with_timeout(cmd, timeout=120):
    """运行命令，超时则 kill"""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=BASE,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        code = -1
    return code, out.decode("utf-8", errors="replace")

def test(name, cmd, timeout=120):
    print(f"\n{'='*60}")
    print(f"测试: {name}")
    print(f"命令: {' '.join(cmd)}")
    print(f"{'='*60}")
    code, out = run_with_timeout(cmd, timeout)
    print(out[-2000:] if len(out) > 2000 else out)
    status = "✅ PASS" if code == 0 else "❌ FAIL"
    print(f"{status} (exit={code})")
    return code == 0

results = []

# 1. 微博关键词搜索（只搜索不进入详情，看筛选）
results.append((
    "微博搜索",
    test("微博搜索", [
        sys.executable, "scripts/keyword_search.py",
        "--keywords", "元气森林",
        "--platforms", "weibo",
        "--per-keyword", "3",
        "--max-comments", "2",
    ])
))

# 2. 小红书关键词搜索
results.append((
    "小红书搜索",
    test("小红书搜索", [
        sys.executable, "scripts/keyword_search.py",
        "--keywords", "元气森林",
        "--platforms", "xiaohongshu",
        "--per-keyword", "3",
        "--max-comments", "2",
    ])
))

# 3. 微博热搜
results.append((
    "微博热搜",
    test("微博热搜", [
        sys.executable, "scripts/weibo_hot_search.py",
        "--limit", "5",
    ])
))

# 4. 小红书账号采集
results.append((
    "小红书账号采集",
    test("小红书账号采集", [
        sys.executable, "scripts/xiaohongshu_scraper.py",
        "--limit", "2",
        "--no-comments",
    ], timeout=180)
))

print(f"\n{'='*60}")
print("测试汇总")
print(f"{'='*60}")
all_pass = True
for name, ok in results:
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}")
    if not ok:
        all_pass = False

if all_pass:
    print("\n🎉 全部通过")
else:
    print("\n⚠️ 有失败项")
