---
name: lark-shared
version: 7.0.9
description: "飞书/Lark CLI 共享基础：认证登录（auth login）、权限与 scope 管理、Permission denied 错误处理、安全规则。当使用登录授权、遇到权限不足、配置 scope、或首次使用 lark-cli 时触发。"
---

# 安装

本包内置 Linux / macOS / Windows 版 lark-cli 二进制。

```bash
# 解压后运行（自动检测系统）
chmod +x setup.sh && ./setup.sh

# Windows（PowerShell）：
# .\setup.ps1
```

完成后 `lark-cli` 在当前目录。建议加入 PATH。

---

# 🚨 重要：永远不要用 --no-wait！所有 auth login 必须用 stdbuf -oL

`--no-wait` 会直接返回，无法等待授权完成。**正确做法**：用 background + stdbuf -oL 启动 auth login，它会先输出 JSON（含授权链接），然后阻塞等授权。你可以先 read 拿到链接发给用户，再 poll 等完成。

# 默认登录
当用户输入"飞书授权"或类似请求时，**严格按以下顺序执行，中间不得回复文字**：

1. `exec run background=true command="stdbuf -oL lark-cli auth login --domain all --json 2>&1"`
2. 拿到 sessionId 后，立刻 `exec read sessionId=<id>` 获取 JSON 输出
3. 从 JSON 提取 `verification_uri`，用 message 工具发 `[点击授权](verification_uri)`
4. 循环 `exec poll sessionId=<id>` 直到 status="done"
5. `exec read sessionId=<id>` 获取授权结果，告知用户"授权成功"

关键：`stdbuf -oL` 强制行缓冲，JSON 立刻输出但命令继续阻塞等授权。

# lark-cli 共享规则

本技能指导你如何通过 lark-cli 操作飞书资源。(lark-cli 路径: `lark-cli`，已在 PATH 中)

## 认证

### 认证流程（一条 background 命令搞定）

```
Step 1: exec run background=true command="stdbuf -oL lark-cli auth login --domain all --json 2>&1"
  → 返回 {"sessionId":"xxx","status":"running"}

Step 2: exec read sessionId=xxx
  → 拿到 {"event":"device_authorization","verification_uri":"https://...","user_code":"XXXX-XXXX"}

Step 3: message content="[点击授权](verification_uri)"
  → 用户收到链接，去浏览器输入 user_code 完成授权

Step 4: 循环 exec poll sessionId=xxx（每 5-10 秒一次）
  → status="running" 时继续等，status="done" 时进入下一步

Step 5: exec read sessionId=xxx，告知用户"授权成功！"
```

**执行顺序严格为 1→2→3→4→5，Step 3 发完链接后不要回复文字，直接进入 Step 4！**

### 权限不足处理

遇到权限相关错误时，错误响应中包含 `permission_violations` 和 `hint`。按 hint 执行增量授权（也用 background + stdbuf，不要用 --no-wait）：
```bash
stdbuf -oL lark-cli auth login --scope "<missing_scope>" --json
```

## 安全规则

- **禁止输出密钥**（appSecret、accessToken）到终端明文。
- **写入/删除操作前必须确认用户意图**。
- 用 `--dry-run` 预览危险请求。
