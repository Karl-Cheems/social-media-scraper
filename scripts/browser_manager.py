"""
浏览器实例管理器 — 管理 N 个独立的 Edge 实例
每个实例对应一个独立的 User Data 目录和 CDP 端口，可以登录任意平台。

用法:
    from browser_manager import browser_manager
    endpoint = browser_manager.get_endpoint("instance1")
"""
import asyncio
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import secrets
from datetime import datetime
from pathlib import Path

# ── 常量 ──
BASE_DIR = Path(__file__).parent.parent.resolve()
DATA_DIR = os.environ.get("SOCIAL_MONITOR_DATA_DIR") or str(BASE_DIR / "data")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "instances.json")
PROFILES_DIR = os.path.join(DATA_DIR, "profiles")
PORT_START = 10001
PORT_END = 60000

LOGIN_URLS = {
    "xiaohongshu": "https://www.xiaohongshu.com/login",
    "weibo": "https://passport.weibo.com/sso/signin",
    "douyin": "https://www.douyin.com/",
}

PLATFORM_DOMAINS = {
    "xiaohongshu": ("xiaohongshu.com",),
    "weibo": ("weibo.com", "sina.com.cn"),
    "douyin": ("douyin.com",),
}

PLATFORM_LOGIN_COOKIES = {
    "xiaohongshu": {"web_session"},
    "weibo": {"SUB"},
    "douyin": {"sessionid", "sessionid_ss", "sid_guard"},
}

# 截图区域配置（各平台二维码位置不同）
PLATFORM_QR_CLIP = {
    "xiaohongshu": {"x": 0, "y": 0, "w": 1.0, "h": 0.7},       # 全屏顶部
    "weibo": {"x": 0.45, "y": 0.0, "w": 0.55, "h": 0.45},      # 右上角
    "douyin": {"x": 0.35, "y": 0.08, "w": 0.65, "h": 0.6},     # 右侧偏中
}


def _find_edge_exe() -> str:
    try:
        r = subprocess.run(["where", "msedge"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.strip().splitlines()[0]
    except Exception:
        pass
    for base in [
        os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
        os.environ.get("ProgramFiles", "C:\\Program Files"),
        os.environ.get("LOCALAPPDATA", ""),
    ]:
        p = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
        if os.path.isfile(p):
            return p
    raise FileNotFoundError("找不到 Edge 浏览器，请确认已安装 Microsoft Edge")


def _port_is_open(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex(("127.0.0.1", int(port))) == 0
    except (OSError, TypeError, ValueError):
        return False


def _find_free_port(start: int = PORT_START, end: int = PORT_END,
                    reserved: set[int] | None = None) -> int:
    reserved = reserved or set()
    for port in range(start, end):
        if port in reserved:
            continue
        if not _port_is_open(port):
            return port
    raise RuntimeError(f"无可用端口（{start}~{end} 全被占用）")


class BrowserManager:
    """浏览器实例管理器（单例）。每个实例 = 一个 Edge 进程 + 端口。"""

    def __init__(self):
        self._accounts: dict[str, dict] = {}
        self._load()

    # ── 持久化 ──────────────────────────────────────────

    def _load(self):
        os.makedirs(os.path.dirname(ACCOUNTS_FILE), exist_ok=True)
        if os.path.isfile(ACCOUNTS_FILE):
            with open(ACCOUNTS_FILE, encoding="utf-8") as f:
                data = json.load(f)
                for a in data.get("instances", data.get("accounts", [])):
                    self._accounts[a["id"]] = a
        self._repair_instance_assignments()

    def _save(self):
        os.makedirs(os.path.dirname(ACCOUNTS_FILE), exist_ok=True)
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump({"instances": list(self._accounts.values())}, f, ensure_ascii=False, indent=2)

    def _repair_instance_assignments(self):
        """修复旧数据中的重复端口和跨项目 profile 路径。"""
        if not self._accounts:
            return
        changed = False
        used = set()
        declared = {
            int(a.get("port")) for a in self._accounts.values()
            if str(a.get("port", "")).isdigit()
        }
        accounts = list(self._accounts.values())
        accounts.sort(key=lambda a: 0 if (
            a.get("pid") and self._is_process_alive(a["pid"]) and _port_is_open(a.get("port"))
        ) else 1)

        for inst in accounts:
            expected_profile = os.path.join(PROFILES_DIR, inst["id"])
            if os.path.normcase(os.path.abspath(inst.get("profile_dir") or "")) != os.path.normcase(os.path.abspath(expected_profile)):
                inst["profile_dir"] = expected_profile
                changed = True
            os.makedirs(expected_profile, exist_ok=True)

            try:
                port = int(inst.get("port", 0))
            except (TypeError, ValueError):
                port = 0
            if port < PORT_START or port >= PORT_END or port in used:
                port = _find_free_port(reserved=declared | used)
                inst["port"] = port
                declared.add(port)
                changed = True
            used.add(port)

            pid_alive = bool(inst.get("pid") and self._is_process_alive(inst["pid"]))
            if not pid_alive and inst.get("status") in ("running", "busy", "pending_qr"):
                inst["status"] = "stopped"
                inst["pid"] = None
                inst["current_task_id"] = None
                changed = True

        if changed:
            self._save()

    # ── CRUD ────────────────────────────────────────────

    def create_account(self, instance_id: str, name: str, password: str = "",
                       config: dict | None = None) -> dict:
        """创建一个浏览器实例（分配唯一端口和用户数据目录）。"""
        if instance_id in self._accounts:
            raise ValueError(f"实例 {instance_id} 已存在")
        profile_dir = os.path.join(PROFILES_DIR, instance_id)
        os.makedirs(profile_dir, exist_ok=True)
        password_hash = self._hash_password(password) if password else ""
        instance = {
            "id": instance_id,
            "name": name,
            "password_hash": password_hash,
            "status": "stopped",
            "port": _find_free_port(reserved={int(a.get("port")) for a in self._accounts.values() if str(a.get("port", "")).isdigit()}),
            "profile_dir": profile_dir,
            "pid": None,
            "current_task_id": None,
            "flagged": False,
            "flagged_reason": None,
            "flagged_at": None,
            "config": config or {
                "rpc_url": "",
                "sender_id": "",
                "prefix_prompt": "",
            },
            "platform_accounts": [],
        }
        self._accounts[instance_id] = instance
        self._save()
        return instance

    def set_password(self, instance_id: str, password: str):
        inst = self._accounts.get(instance_id)
        if inst:
            inst["password_hash"] = self._hash_password(password)
            self._save()

    def verify_password(self, instance_id: str, password: str) -> bool:
        inst = self._accounts.get(instance_id)
        if not inst or not inst.get("password_hash"):
            return False
        return self._hash_password(password) == inst["password_hash"]

    def _hash_password(self, password: str) -> str:
        """Simple salted SHA256 hash. Not cryptographically strong but sufficient for local/internal use."""
        salt = "social_monitor_v1"
        return hashlib.sha256((salt + password).encode()).hexdigest()

    def get_account(self, instance_id: str) -> dict | None:
        return self._accounts.get(instance_id)

    def list_accounts(self) -> list[dict]:
        return list(self._accounts.values())

    def delete_account(self, instance_id: str):
        self.stop_account(instance_id)
        inst = self._accounts.get(instance_id)
        if inst and inst.get("profile_dir"):
            try:
                import shutil
                if os.path.isdir(inst["profile_dir"]):
                    shutil.rmtree(inst["profile_dir"], ignore_errors=True)
                    print(f"  🧹 已清除实例「{instance_id}」的用户数据目录", file=sys.stderr)
            except Exception as e:
                print(f"  ⚠️ 清除用户数据目录失败: {e}", file=sys.stderr)
        self._accounts.pop(instance_id, None)
        self._save()

    # ── 配置管理 ──────────────────────────────────────────

    def update_config(self, instance_id: str, config_updates: dict):
        inst = self._accounts.get(instance_id)
        if not inst:
            raise ValueError(f"实例 {instance_id} 不存在")
        cfg = inst.setdefault("config", {"rpc_url": "", "sender_id": "", "prefix_prompt": ""})
        for k in ("rpc_url", "sender_id", "prefix_prompt"):
            if k in config_updates:
                cfg[k] = config_updates[k]
        self._save()

    # ── 平台账号管理 ──────────────────────────────────────

    def add_platform_account(self, instance_id: str, platform: str, name: str) -> dict:
        inst = self._accounts.get(instance_id)
        if not inst:
            raise ValueError(f"实例 {instance_id} 不存在")
        accounts = inst.setdefault("platform_accounts", [])
        for acct in accounts:
            if acct["platform"] == platform:
                raise ValueError(f"实例已绑定 {platform} 账号，请先解绑再添加")
        entry = {
            "platform": platform,
            "name": name,
            "login_status": "not_logged",
        }
        accounts.append(entry)
        self._save()
        return entry

    def remove_platform_account(self, instance_id: str, platform: str):
        inst = self._accounts.get(instance_id)
        if not inst:
            return
        accounts = inst.setdefault("platform_accounts", [])
        inst["platform_accounts"] = [a for a in accounts if a["platform"] != platform]
        self._save()

    def update_account_login_status(self, instance_id: str, platform: str, status: str):
        inst = self._accounts.get(instance_id)
        if not inst:
            return
        for acct in inst.setdefault("platform_accounts", []):
            if acct["platform"] == platform:
                acct["login_status"] = status
                self._save()
                return

    def has_platform_login(self, instance_id: str, platform: str) -> bool:
        """检查实例是否有指定平台的已登录账号。"""
        inst = self._accounts.get(instance_id)
        if not inst:
            return False
        for acct in inst.setdefault("platform_accounts", []):
            if acct["platform"] == platform and acct["login_status"] == "logged_in":
                return True
        return False

    def get_platform_name(self, instance_id: str, platform: str) -> str | None:
        inst = self._accounts.get(instance_id)
        if not inst:
            return None
        for acct in inst.setdefault("platform_accounts", []):
            if acct["platform"] == platform:
                return acct.get("name", platform)
        return None

    def _assert_exists(self, instance_id: str):
        if instance_id not in self._accounts:
            raise ValueError(f"实例 {instance_id} 不存在")

    # ── Edge 生命周期 ───────────────────────────────────

    async def start_account(self, instance_id: str):
        """启动实例的 Edge 进程。"""
        inst = self._accounts.get(instance_id)
        if not inst:
            raise ValueError(f"实例 {instance_id} 不存在")

        if inst["status"] == "running" and inst["pid"] and self._is_process_alive(inst["pid"]):
            return

        inst["status"] = "stopped"
        inst["pid"] = None
        expected_profile = os.path.join(PROFILES_DIR, instance_id)
        inst["profile_dir"] = expected_profile
        os.makedirs(expected_profile, exist_ok=True)

        reserved = {
            int(other.get("port")) for other_id, other in self._accounts.items()
            if other_id != instance_id and str(other.get("port", "")).isdigit()
        }
        try:
            port = int(inst.get("port", 0))
        except (TypeError, ValueError):
            port = 0
        if port in reserved or port < PORT_START or port >= PORT_END or _port_is_open(port):
            port = _find_free_port(reserved=reserved)
            inst["port"] = port
            self._save()

        edge_exe = _find_edge_exe()

        for f in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
            p = os.path.join(inst["profile_dir"], f)
            try:
                os.remove(p)
            except Exception:
                pass

        proc = subprocess.Popen(
            [
                edge_exe,
                f"--remote-debugging-port={port}",
                "--remote-allow-origins=*",
                f"--user-data-dir={inst['profile_dir']}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        for _ in range(15):
            await asyncio.sleep(1)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
        else:
            proc.kill()
            raise RuntimeError(f"实例 {instance_id} Edge 启动超时（端口 {port}）")

        inst["pid"] = proc.pid
        inst["status"] = "running"
        inst["current_task_id"] = None
        self._save()

    async def start_account_and_goto(self, instance_id: str, url: str = "") -> dict:
        """启动实例 Edge 并导航到指定登录页面，截取二维码返回。"""
        import base64

        await self.start_account(instance_id)
        inst = self._accounts[instance_id]

        if not url:
            return {
                "endpoint": f"http://127.0.0.1:{inst['port']}",
                "url": "",
                "qrcode": None,
                "logged_in": False,
                "login_state": "started",
            }

        # 从url反推platform
        platform = ""
        for k, v in LOGIN_URLS.items():
            if v == url or url.startswith(v.rstrip("/")):
                platform = k
                break

        qrcode_base64 = None
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return {"endpoint": f"http://127.0.0.1:{inst['port']}", "url": url,
                    "qrcode": None, "logged_in": False, "login_state": "unavailable"}

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{inst['port']}")
            context = browser.contexts[0] if browser.contexts else await browser.new_context()

            pages = list(context.pages)
            # 复用最后一个标签页，避免关闭最后一页导致 Edge 窗口消失后又重开。
            page = pages[-1] if pages else await context.new_page()
            for cp in pages[:-1]:
                try:
                    await cp.close()
                except Exception:
                    pass

            # ── 抖音特殊处理 ──
            if platform == "douyin":
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)

                # 检测是否已登录（有内容）
                already_logged = await self._check_page_logged_in(page, platform)

                if already_logged:
                    print(f"  ✅ 实例「{instance_id}」抖音已有登录态，跳过扫码", file=sys.stderr)
                    inst["status"] = "running"
                    self._save()
                    return {"endpoint": f"http://127.0.0.1:{inst['port']}", "url": url,
                            "qrcode": None, "logged_in": True, "login_state": "logged_in"}

                # 点击登录按钮，弹登录框
                await self._douyin_click_login(page)
                await page.wait_for_timeout(3000)

                # 找二维码
                qrcode_base64 = await self._find_qrcode(page, "douyin")
                if qrcode_base64:
                    inst["status"] = "pending_qr"
                    self._save()
                    print(f"  📱 实例「{instance_id}」抖音等待扫码", file=sys.stderr)
                    return {
                        "endpoint": f"http://127.0.0.1:{inst['port']}",
                        "qrcode": qrcode_base64,
                        "url": url,
                        "logged_in": False,
                        "login_state": "pending_qr",
                    }

                # 尝试点击"扫码登录"或"二维码"tab
                try:
                    # 抖音登录弹窗可能有多个tab：扫码/手机号等
                    qr_tab = await page.query_selector('div[class*="login-tab"]:has-text("扫码"), div[class*="tab"]:has-text("扫码"), [class*=qrcode-tab], div:has-text("扫码登录")')
                    if qr_tab:
                        await qr_tab.click()
                        await page.wait_for_timeout(2000)
                        qrcode_base64 = await self._find_qrcode(page, "douyin")
                except Exception:
                    pass

                if qrcode_base64:
                    inst["status"] = "pending_qr"
                    self._save()
                    print(f"  📱 实例「{instance_id}」抖音等待扫码（切换tab后）", file=sys.stderr)
                else:
                    inst["status"] = "running"
                    self._save()
                    print(f"  ℹ️ 实例「{instance_id}」抖音已启动，未检测到二维码", file=sys.stderr)

                return {
                    "endpoint": f"http://127.0.0.1:{inst['port']}",
                    "qrcode": qrcode_base64,
                    "url": url,
                }

            # ── 其他平台（小红书、微博） ──
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)

            # 判断是否已登录（用新检测逻辑）
            already_logged = await self._check_page_logged_in(page, platform)

            if already_logged:
                print(f"  ✅ 实例「{instance_id}」已有登录态，跳过扫码", file=sys.stderr)
                inst["status"] = "running"
                self._save()
                return {"endpoint": f"http://127.0.0.1:{inst['port']}", "url": url,
                            "qrcode": None, "logged_in": True, "login_state": "logged_in"}

            # ── 微博特殊处理 ──
            if platform == "weibo":
                # 微博可能重定向到其他域名，等一等
                await page.wait_for_timeout(2000)
                # 如果跳转到了非 passport 域(比如已登录自动跳转)，再检测一次
                current_url = page.url
                if not re.search(r'passport\.weibo|login\.sina|sso/signin', current_url):
                    already_logged = await self._check_page_logged_in(page, platform)
                    if already_logged:
                        print(f"  ✅ 实例「{instance_id}」微博重定向后已有登录态", file=sys.stderr)
                        inst["status"] = "running"
                        self._save()
                        return {"endpoint": f"http://127.0.0.1:{inst['port']}", "url": url,
                            "qrcode": None, "logged_in": True, "login_state": "logged_in"}

            # ── 找二维码 ──
            qrcode_base64 = await self._find_qrcode(page, platform)

        if qrcode_base64:
            inst["status"] = "pending_qr"
            self._save()
            print(f"  📱 实例「{instance_id}」已在登录页，等待扫码", file=sys.stderr)
        else:
            inst["status"] = "running"
            self._save()
            print(f"  ℹ️ 实例「{instance_id}」已启动到 {url}，未检测到二维码", file=sys.stderr)

        return {
            "endpoint": f"http://127.0.0.1:{inst['port']}",
            "qrcode": qrcode_base64,
            "url": url,
            "logged_in": False,
            "login_state": "pending_qr" if qrcode_base64 else "need_login",
        }

    def _has_login_cookie(self, cookies: list[dict], platform: str) -> bool:
        expected = PLATFORM_LOGIN_COOKIES.get(platform, set())
        return any(c.get("name") in expected and bool(c.get("value")) for c in cookies)

    def _page_matches_platform(self, url: str, platform: str) -> bool:
        return any(domain in (url or "").lower() for domain in PLATFORM_DOMAINS.get(platform, ()))

    async def _check_page_logged_in(self, page, platform: str = "") -> bool:
        """只认平台导航区的强登录标志，普通内容头像不能作为登录依据。"""
        try:
            return bool(await page.evaluate("""(platform) => {
                try {
                    const url = (location.href || '').toLowerCase();
                    const visible = (el) => {
                        if (!el) return false;
                        const r = el.getBoundingClientRect();
                        return r.width > 16 && r.height > 16;
                    };

                    if (/passport|sso\\/signin|\\/login/.test(url)) return false;

                    const loginUi = document.querySelectorAll(
                        '[class*="login-dialog"],[class*="login-modal"],[class*="login-panel"],' +
                        '[class*="login-container"],[class*="qrcode"],[class*="qr-code"]'
                    );
                    for (const el of loginUi) {
                        if (visible(el)) return false;
                    }

                    let selectors = [];
                    if (platform === 'weibo') {
                        selectors = [
                            'header a[href*="/u/"] img',
                            'header [class*="avatar"] img',
                            'nav a[href*="/u/"] img',
                            '[class*="woo-box-flex"] > a[href*="/u/"] img'
                        ];
                    } else if (platform === 'xiaohongshu') {
                        selectors = [
                            'header a[href*="/user/profile/"] img',
                            '[class*="side-bar"] a[href*="/user/profile/"] img',
                            '[class*="user-info"] a[href*="/user/profile/"]',
                            '[class*="channel"] a[href*="/user/profile/"]'
                        ];
                    } else if (platform === 'douyin') {
                        selectors = [
                            'header [class*="avatar"] img',
                            'nav [class*="avatar"] img',
                            '[class*="header"] a[href*="/user/"] img',
                            '[class*="user-info"] [class*="avatar"]'
                        ];
                    }
                    return selectors.some((selector) =>
                        Array.from(document.querySelectorAll(selector)).some(visible)
                    );
                } catch (e) {
                    return false;
                }
            }""", platform))
        except Exception:
            return False

    async def _detect_page_risk(self, page, platform: str = "") -> str | None:
        """检测当前平台页是否要求人工完成安全验证。只匹配可见控件和强提示语。"""
        try:
            return await page.evaluate("""(platform) => {
                try {
                    const visible = (el) => {
                        if (!el) return false;
                        const style = getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return style.display !== 'none' && style.visibility !== 'hidden' &&
                               Number(style.opacity || 1) > 0 && r.width > 24 && r.height > 18;
                    };
                    const strong = [
                        '请完成安全验证', '请先完成验证', '访问过于频繁', '操作过于频繁',
                        '请求过于频繁', '账号存在异常', '账号异常', '网络环境存在风险',
                        '拖动滑块', '滑块验证', '人机验证', '手机刷脸验证',
                        '接收短信验证码', '发送短信验证',
                        '完成身份验证', '请完成身份验证'
                    ];
                    const candidates = Array.from(document.querySelectorAll(
                        '[role="dialog"],[class*="captcha"],[id*="captcha"],' +
                        '[class*="risk"],[id*="risk"],[class*="security"],' +
                        'iframe[src*="captcha"],iframe[src*="verify"]'
                    )).filter(visible);
                    for (const el of candidates) {
                        const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                        const hit = strong.find(x => text.includes(x));
                        if (hit) return hit;
                        if (/captcha/i.test(el.className || '') || /captcha/i.test(el.id || '')) return '页面出现验证码';
                    }
                    const body = (document.body?.innerText || '').replace(/\\s+/g, ' ');
                    return strong.find(x => body.includes(x)) || null;
                } catch (e) { return null; }
            }""", platform)
        except Exception:
            return None

    async def check_risk(self, instance_id: str, platform: str = "") -> dict:
        """实时扫描实例页面；发现风控后立即冻结该实例，等待人工处理。"""
        inst = self._accounts.get(instance_id)
        if not inst:
            return {"risk_detected": False, "risk_reason": None, "risk_platform": platform}
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{inst['port']}")
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                pages = list(context.pages)
                if platform:
                    pages = [pg for pg in pages if self._page_matches_platform(pg.url, platform)]
                for page in reversed(pages):
                    reason = await self._detect_page_risk(page, platform)
                    if reason:
                        platform_name = {"xiaohongshu": "小红书", "weibo": "微博", "douyin": "抖音"}.get(platform, platform or "平台")
                        full_reason = f"{platform_name}需要人工验证：{reason}"
                        self.mark_flagged(instance_id, full_reason)
                        return {"risk_detected": True, "risk_reason": full_reason, "risk_platform": platform}
        except Exception:
            pass
        return {"risk_detected": False, "risk_reason": None, "risk_platform": platform}

    async def _douyin_click_login(self, page):
        """抖音页面查找并点击登录按钮（仅用浏览器原生API）。"""
        import asyncio
        # 先等页面完整加载
        await asyncio.sleep(2)

        # JS方式找登录按钮并点击（避免:has-text等不支持的伪选择器）
        try:
            clicked = await page.evaluate("""() => {
                // 找文本包含"登录"且可见的按钮/链接/span
                var tags = ['BUTTON', 'A', 'SPAN', 'DIV'];
                for (var t = 0; t < tags.length; t++) {
                    var els = document.querySelectorAll(tags[t]);
                    for (var i = 0; i < els.length; i++) {
                        var txt = (els[i].textContent || '').trim();
                        if (txt === '登录' && els[i].offsetWidth > 20 && els[i].offsetHeight > 20) {
                            els[i].click();
                            return true;
                        }
                    }
                }
                // 尝试找class包含login/header的按钮
                var loginBtns = document.querySelectorAll(
                    '[class*="login"] button, [class*="login-btn"], [class*="loginBtn"], ' +
                    '[class*="LoginBtn"], [class*="loginBtn"], [class*="header-login"]'
                );
                for (var j = 0; j < loginBtns.length; j++) {
                    if (loginBtns[j].offsetWidth > 20 && loginBtns[j].offsetHeight > 20) {
                        loginBtns[j].click();
                        return true;
                    }
                }
                return false;
            }""")
            if clicked:
                print(f"  🖱 点击了抖音登录按钮（JS）", file=sys.stderr)
                await asyncio.sleep(3)
                return
        except Exception:
            pass

        print(f"  ⚠️ 抖音：未找到登录按钮", file=sys.stderr)

    async def _find_qrcode(self, page, platform="") -> str | None:
        """返回二维码图片本身的 base64，避免把整个登录面板当作二维码。"""
        import base64

        platform_selectors = {
            "douyin": [
                '#douyin-login-new-id img[src^="data:image/"]',
                '#douyin_login_comp_flat_panel img[src^="data:image/"]',
                'img.RhjdbXj8',
                '[id*="douyin_login"] img[src^="data:image/"]',
                '[id*="douyin_login"] canvas',
            ],
            "weibo": [
                'img[class*="qrcode"]',
                '[class*="qrcode"] img',
                '[class*="qr-code"] img',
                '[class*="QRCode"] img',
                'canvas[class*="qrcode"]',
                '[class*="qrcode"] canvas',
            ],
            "xiaohongshu": [
                'img[class*="qrcode"]',
                '[class*="qrcode"] img',
                '[class*="qr-code"] img',
                '[class*="QRCode"] img',
                'canvas[class*="qrcode"]',
                '[class*="qrcode"] canvas',
            ],
        }
        generic_selectors = [
            'img[src*="qrcode"]',
            'img[alt*="二维码"]',
            'img[alt*="扫码"]',
            'img.qrcode-img',
            'canvas[class*="qr-code"]',
            'canvas[class*="QRCode"]',
        ]
        selectors = platform_selectors.get(platform, []) + generic_selectors

        for _ in range(10):
            await page.wait_for_timeout(600)
            for selector in selectors:
                try:
                    for element in await page.query_selector_all(selector):
                        rect = await element.bounding_box()
                        if not rect:
                            continue
                        width, height = rect["width"], rect["height"]
                        ratio = width / height if height else 0
                        if not (80 <= width <= 360 and 80 <= height <= 360 and 0.85 <= ratio <= 1.15):
                            continue

                        # 抖音二维码本身就是 data URL。直接返回原图，比元素截图更清晰。
                        src = await element.get_attribute("src")
                        if src and src.startswith("data:image/") and ";base64," in src:
                            return src.split(",", 1)[1]

                        png = await element.screenshot(type="png")
                        if png:
                            return base64.b64encode(png).decode()
                except Exception:
                    continue
        return None
    async def check_login(self, instance_id: str, platform: str = "") -> dict:
        """按平台检查登录态。优先使用强登录 Cookie，并用对应平台页面复核。"""
        inst = self._accounts.get(instance_id)
        if not inst:
            return {"logged_in": False, "login_error": "实例不存在", "platforms": {}}

        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                try:
                    browser = await p.chromium.connect_over_cdp(
                        f"http://127.0.0.1:{inst['port']}"
                    )
                except Exception as e:
                    return {"logged_in": False, "login_error": f"连接失败: {e}", "platforms": {}}

                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                pages = list(context.pages)
                cookies = await context.cookies()

                if platform:
                    platforms = [platform]
                else:
                    platforms = [
                        a.get("platform") for a in inst.get("platform_accounts", [])
                        if a.get("platform") in LOGIN_URLS
                    ]

                states = {}
                for current in platforms:
                    matching_pages = [
                        page for page in pages
                        if self._page_matches_platform(page.url, current)
                    ]
                    for page in reversed(matching_pages):
                        reason = await self._detect_page_risk(page, current)
                        if reason:
                            platform_name = {"xiaohongshu": "小红书", "weibo": "微博", "douyin": "抖音"}.get(current, current)
                            full_reason = f"{platform_name}需要人工验证：{reason}"
                            self.mark_flagged(instance_id, full_reason)
                            states[current] = False
                            self.update_account_login_status(instance_id, current, "not_logged")
                            return {
                                "logged_in": False, "platforms": states,
                                "risk_detected": True, "risk_reason": full_reason,
                                "risk_platform": current,
                            }

                    logged_in = self._has_login_cookie(cookies, current)
                    if not logged_in:
                        for page in reversed(matching_pages):
                            if await self._check_page_logged_in(page, current):
                                logged_in = True
                                break

                    states[current] = logged_in
                    self.update_account_login_status(
                        instance_id, current, "logged_in" if logged_in else "not_logged"
                    )

                if platform:
                    logged_in = states.get(platform, False)
                    if logged_in and inst.get("flagged"):
                        self.unflag(instance_id)
                    return {"logged_in": logged_in, "platforms": states, "risk_detected": False}

                if not states and pages:
                    logged_in = await self._check_page_logged_in(pages[-1])
                    return {"logged_in": logged_in, "platforms": {}}

                return {
                    "logged_in": bool(states) and all(states.values()),
                    "platforms": states,
                }
        except Exception as e:
            return {"logged_in": False, "login_error": str(e), "platforms": {}}
    def stop_account(self, instance_id: str):
        inst = self._accounts.get(instance_id)
        if not inst or not inst["pid"]:
            if inst:
                inst["status"] = "stopped"
                inst["pid"] = None
            self._save()
            return
        try:
            subprocess.run(["taskkill", "/f", "/pid", str(inst["pid"])], capture_output=True, timeout=10)
        except Exception:
            pass
        inst["status"] = "stopped"
        inst["pid"] = None
        inst["current_task_id"] = None
        self._save()

    def get_endpoint(self, instance_id: str, retry: int = 0) -> str | None:
        inst = self._accounts.get(instance_id)
        if not inst or inst["status"] not in ("running", "busy", "pending_qr"):
            return None
        if not inst.get("pid") or not self._is_process_alive(inst["pid"]):
            return None
        port = inst["port"]
        for i in range(1 + retry):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    return f"http://127.0.0.1:{port}"
            if i < retry:
                import time as _t
                _t.sleep(1.5)
        return None

    def is_account_available(self, instance_id: str) -> bool:
        """检查实例是否正在运行且端口通畅。"""
        inst = self._accounts.get(instance_id)
        if not inst:
            return False
        if inst.get("flagged"):
            return False
        if inst["status"] not in ("running",):
            return False
        return self.get_endpoint(instance_id) is not None

    def set_busy(self, instance_id: str, task_id: int):
        inst = self._accounts.get(instance_id)
        if inst:
            inst["status"] = "busy"
            inst["current_task_id"] = task_id
            self._save()

    def set_idle(self, instance_id: str):
        inst = self._accounts.get(instance_id)
        if inst:
            inst["status"] = "running"
            inst["current_task_id"] = None
            self._save()

    # ── 风控 ────────────────────────────────────────────

    def mark_flagged(self, instance_id: str, reason: str = "触发风控"):
        inst = self._accounts.get(instance_id)
        if inst:
            inst["flagged"] = True
            inst["flagged_reason"] = reason
            inst["flagged_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            inst["status"] = "flagged"
            self._save()

    def unflag(self, instance_id: str):
        inst = self._accounts.get(instance_id)
        if inst:
            inst["flagged"] = False
            inst["flagged_reason"] = None
            inst["flagged_at"] = None
            if inst["status"] == "flagged":
                inst["status"] = "running"
            self._save()

    # ── 进程检测 ────────────────────────────────────────

    def _is_process_alive(self, pid: int) -> bool:
        try:
            r = subprocess.run(["tasklist", "/fi", f"PID eq {pid}", "/nh"], capture_output=True, text=True, timeout=5)
            return "msedge.exe" in r.stdout
        except Exception:
            return False


# ── 全局单例 ────────────────────────────────────────────
browser_manager = BrowserManager()
