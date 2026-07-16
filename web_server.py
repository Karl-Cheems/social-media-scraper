"""
社交媒体监控 — Web 服务（多租户版）
每个实例独立登录，独立配置，独立 Edge 浏览器。
任务自动归属当前登录实例。

用法：
    python web_server.py
    python web_server.py --port 5050
"""
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

import flask

# ── 路径 ──────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
SCRIPTS_DIR = BASE_DIR / "scripts"
CONFIG_DIR = BASE_DIR / "config"
NOTIFY_DIR = BASE_DIR / "notify"
DATA_DIR = BASE_DIR / "data"
SCHEDULE_FILE = CONFIG_DIR / "schedule_rules.json"

os.makedirs(DATA_DIR, exist_ok=True)

PYTHON = sys.executable

# ── BrowserManager ────────────────────────────────────────
sys.path.insert(0, str(SCRIPTS_DIR))
from browser_manager import browser_manager as bm, LOGIN_URLS

# ── Flask App ─────────────────────────────────────────────
app = flask.Flask(__name__,
                  template_folder=str(BASE_DIR / "web" / "templates"),
                  static_folder=str(BASE_DIR / "web" / "static"),
                  static_url_path="/static")
app.secret_key = "social-monitor-secret-key-change-in-production"
app.config["TEMPLATES_AUTO_RELOAD"] = True

# ── 认证装饰器 ────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "instance_id" not in flask.session:
            return flask.jsonify({"error": "请先登录"}), 401
        return f(*args, **kwargs)
    return decorated

# ── 配置数据加载 ──────────────────────────────────────────
KEYWORDS_LOCK = threading.Lock()


def load_keywords_data():
    keyword_file = CONFIG_DIR / "keywords.json"
    if keyword_file.is_file():
        with open(keyword_file, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {"product_lines": []}
    return {"product_lines": []}


def load_keywords():
    return load_keywords_data().get("product_lines", [])


def save_keywords_data(data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    keyword_file = CONFIG_DIR / "keywords.json"
    temp_file = keyword_file.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
    os.replace(temp_file, keyword_file)

def load_urls():
    entries = []
    current_brand = None
    url_file = CONFIG_DIR / "urls.txt"
    if url_file.is_file():
        with open(url_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                m = __import__("re").match(r'#\s*===\s*(.+?)\s*===\s*$', line)
                if m:
                    current_brand = m.group(1).strip()
                    continue
                if line.startswith("#") or not current_brand:
                    continue
                is_xhs = bool(__import__("re").match(r'^\d+$', line)) or "xiaohongshu" in line
                entries.append({"brand": current_brand, "identifier": line, "platform": "xiaohongshu" if is_xhs else "weibo"})
    return entries


# ── 任务参数校验 ──────────────────────────────────────────
def _bool_value(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(params, key, default, minimum, maximum):
    try:
        value = int(params.get(key, default))
    except (TypeError, ValueError):
        raise ValueError(f"{key} 必须是整数")
    if value < minimum or value > maximum:
        raise ValueError(f"{key} 必须在 {minimum} 到 {maximum} 之间")
    return value


def normalize_task_params(task_type: str, raw_params: dict | None) -> dict:
    """把 Web 表单参数转换为脚本可安全使用的标准格式。"""
    params = raw_params if isinstance(raw_params, dict) else {}
    send_agent = _bool_value(params.get("send_agent"), True)

    if task_type == "hot":
        platform = str(params.get("platform", "merged")).strip()
        if platform not in {"weibo_hot", "weibo_ent", "douyin", "merged"}:
            raise ValueError("不支持的热搜平台")
        return {
            "platform": platform,
            "limit": _bounded_int(params, "limit", 15, 1, 50),
            "send_agent": send_agent,
            "source_type": "hot",
        }

    if task_type == "keyword":
        keywords = params.get("keywords", [])
        if not isinstance(keywords, list):
            raise ValueError("关键词格式不正确")
        cleaned_keywords = []
        for item in keywords:
            value = str(item).strip()
            if value and value not in cleaned_keywords:
                cleaned_keywords.append(value[:80])
        if not cleaned_keywords:
            raise ValueError("请至少选择或输入一个关键词")
        if len(cleaned_keywords) > 100:
            raise ValueError("一次最多提交 100 个关键词")

        platforms = params.get("platforms", [])
        if isinstance(platforms, str):
            platforms = [platforms]
        cleaned_platforms = [p for p in ("weibo", "xiaohongshu") if p in platforms]
        if not cleaned_platforms:
            raise ValueError("请至少选择一个搜索平台")
        sort_by = str(params.get("sort_by", "likes"))
        content_type = str(params.get("content_type", "all"))
        if sort_by not in {"likes", "comments"}:
            raise ValueError("不支持的排序方式")
        if content_type not in {"all", "image_text"}:
            raise ValueError("不支持的内容类型")
        xhs_pacing = str(params.get("xhs_pacing", "balanced")).strip().lower()
        if xhs_pacing not in {"fast", "balanced", "conservative"}:
            xhs_pacing = "balanced"
        return {
            "keywords": cleaned_keywords,
            "platforms": cleaned_platforms,
            "per_keyword": _bounded_int(params, "per_keyword", 5, 1, 20),
            "max_comments": _bounded_int(params, "max_comments", 200, 0, 999),
            "sort_by": sort_by,
            "content_type": content_type,
            "xhs_pacing": xhs_pacing,
            "send_agent": send_agent,
            "source_type": "keyword",
        }

    if task_type in {"account_self", "account_comp"}:
        all_entries = load_urls()
        if task_type == "account_self":
            selected = [e["identifier"] for e in all_entries if e.get("brand") == "元气森林"]
            source_type = "self_account"
        else:
            allowed = {e["identifier"] for e in all_entries if e.get("brand") != "元气森林"}
            requested = params.get("urls", [])
            if not isinstance(requested, list):
                raise ValueError("账号列表格式不正确")
            selected = []
            for value in requested:
                value = str(value).strip()
                if value in allowed and value not in selected:
                    selected.append(value)
            source_type = "competitor_account"
        if not selected:
            raise ValueError("请至少选择一个账号")
        return {
            "urls": selected,
            "limit": _bounded_int(params, "limit", 10, 1, 50),
            "max_comments": _bounded_int(params, "max_comments", 200, 0, 999),
            "include_content": _bool_value(params.get("include_content"), True),
            "include_comments": _bool_value(params.get("include_comments"), True),
            "send_agent": send_agent,
            "source_type": source_type,
        }

    if task_type == "detail":
        url = str(params.get("url", "")).strip()
        lower_url = url.lower()
        if not url or not any(domain in lower_url for domain in ("weibo.com", "xiaohongshu.com", "xhslink.com")):
            raise ValueError("请提供微博或小红书的内容链接")
        return {
            "url": url,
            "max_comments": _bounded_int(params, "max_comments", 999, 1, 999),
            "send_agent": send_agent,
            "source_type": "detail",
        }

    raise ValueError("不支持的任务类型")

# ── Token / Session ────────────────────────────────────────
PLATFORM_NAMES = {
    "xiaohongshu": "📕 小红书",
    "weibo": "📱 微博",
    "douyin": "🎵 抖音",
}

def get_inst():
    inst_id = flask.session.get("instance_id")
    if not inst_id:
        return None
    inst = bm.get_account(inst_id)
    if not inst:
        flask.session.clear()
        return None
    return inst


# ── Auth API ───────────────────────────────────────────────

@app.route("/api/auth/register", methods=["POST"])
def api_auth_register():
    data = flask.request.get_json(force=True)
    name = data.get("name", "").strip()
    password = data.get("password", "")
    rpc_url = data.get("rpc_url", "").strip()
    sender_id = data.get("sender_id", "").strip()

    if not name or not password:
        return flask.jsonify({"error": "实例名称和密码不能为空"}), 400
    if len(password) < 4:
        return flask.jsonify({"error": "密码至少4位"}), 400

    instance_id = name
    if bm.get_account(instance_id):
        return flask.jsonify({"error": "实例名称已存在"}), 400

    config = {"rpc_url": rpc_url, "sender_id": sender_id, "prefix_prompt": ""}
    try:
        inst = bm.create_account(instance_id, name, password, config)
    except ValueError as e:
        return flask.jsonify({"error": str(e)}), 400

    flask.session["instance_id"] = instance_id
    flask.session.permanent = True
    return flask.jsonify({"ok": True, "instance": _safe_instance(inst)})


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    data = flask.request.get_json(force=True)
    name = data.get("name", "").strip()
    password = data.get("password", "")

    if not name or not password:
        return flask.jsonify({"error": "实例名称和密码不能为空"}), 400

    inst = bm.get_account(name)
    if not inst:
        return flask.jsonify({"error": "实例不存在"}), 404
    if not bm.verify_password(name, password):
        return flask.jsonify({"error": "密码错误"}), 403

    flask.session["instance_id"] = name
    flask.session.permanent = True
    return flask.jsonify({"ok": True, "instance": _safe_instance(inst)})


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    flask.session.clear()
    return flask.jsonify({"ok": True})


@app.route("/api/auth/check")
def api_auth_check():
    inst = get_inst()
    if not inst:
        return flask.jsonify({"ok": False})
    return flask.jsonify({"ok": True, "instance": _safe_instance(inst)})


def _safe_instance(inst: dict) -> dict:
    """返回不含密码 hash 的实例信息。"""
    return {k: v for k, v in inst.items() if k != "password_hash"}


# ── Instance API（当前登录实例）───────────────────────────

@app.route("/api/instance")
@login_required
def api_instance():
    inst = get_inst()
    if not inst:
        return flask.jsonify({"error": "实例不存在"}), 404
    return flask.jsonify(_safe_instance(inst))


@app.route("/api/instance/config", methods=["PUT"])
@login_required
def api_instance_update_config():
    inst_id = flask.session["instance_id"]
    data = flask.request.get_json(force=True)
    config_updates = {k: data.get(k, "") for k in ("rpc_url", "sender_id", "prefix_prompt")}
    bm.update_config(inst_id, config_updates)
    inst = bm.get_account(inst_id)
    return flask.jsonify({"ok": True, "instance": _safe_instance(inst)})


@app.route("/api/instance/password", methods=["PUT"])
@login_required
def api_instance_change_password():
    inst_id = flask.session["instance_id"]
    data = flask.request.get_json(force=True)
    old_pw = data.get("old_password", "")
    new_pw = data.get("new_password", "")

    if not bm.verify_password(inst_id, old_pw):
        return flask.jsonify({"error": "旧密码错误"}), 403
    if len(new_pw) < 4:
        return flask.jsonify({"error": "新密码至少4位"}), 400

    bm.set_password(inst_id, new_pw)
    return flask.jsonify({"ok": True})


@app.route("/api/instance/delete", methods=["POST"])
@login_required
def api_instance_delete():
    inst_id = flask.session["instance_id"]
    data = flask.request.get_json(silent=True) or {}
    password = data.get("password", "")

    if not bm.verify_password(inst_id, password):
        return flask.jsonify({"error": "密码错误"}), 403

    bm.delete_account(inst_id)
    flask.session.clear()
    return flask.jsonify({"ok": True})


@app.route("/api/instance/start", methods=["POST"])
@login_required
def api_instance_start():
    inst_id = flask.session["instance_id"]
    data = flask.request.get_json(silent=True) or {}
    platform = data.get("platform", "")
    account_name = data.get("account_name", "")

    # 如果有 platform，检查是否已绑定
    if platform:
        if not account_name:
            # 查找该平台绑定的账号
            inst = bm.get_account(inst_id)
            for acct in inst.get("platform_accounts", []):
                if acct["platform"] == platform:
                    account_name = acct["name"]
                    break
        if not account_name:
            return flask.jsonify({"error": f"请先在实例配置中添加 {PLATFORM_NAMES.get(platform, platform)} 账号"}), 400

    url = LOGIN_URLS.get(platform, "") if platform else ""
    try:
        import asyncio
        result = asyncio.run(bm.start_account_and_goto(inst_id, url=url))
        inst = bm.get_account(inst_id)

        # 如果登录成功（有内容没二维码），标记该平台已登录
        qrcode = result.get("qrcode")
        if result.get("logged_in") and platform:
            bm.update_account_login_status(inst_id, platform, "logged_in")

        return flask.jsonify({
            "ok": True,
            "instance": _safe_instance(inst),
            "endpoint": result.get("endpoint"),
            "qrcode": qrcode,
            "has_qrcode": qrcode is not None,
            "logged_in": result.get("logged_in", False),
            "login_state": result.get("login_state", "unknown"),
        })
    except Exception as e:
        traceback.print_exc()
        return flask.jsonify({"error": str(e)}), 500


@app.route("/api/instance/stop", methods=["POST"])
@login_required
def api_instance_stop():
    inst_id = flask.session["instance_id"]
    bm.stop_account(inst_id)
    return flask.jsonify({"ok": True})


@app.route("/api/instance/check", methods=["POST"])
@login_required
def api_instance_check():
    inst_id = flask.session["instance_id"]
    inst = bm.get_account(inst_id)
    if not inst:
        return flask.jsonify({"error": "实例不存在"}), 404

    import asyncio
    try:
        result = asyncio.run(bm.check_login(inst_id))
        inst2 = bm.get_account(inst_id)
        return flask.jsonify({
            "ok": True,
            "logged_in": result.get("logged_in", False),
            "platforms": result.get("platforms", {}),
            "login_error": result.get("login_error"),
            "risk_detected": result.get("risk_detected", False),
            "risk_reason": result.get("risk_reason"),
            "risk_platform": result.get("risk_platform"),
            "instance": _safe_instance(inst2),
        })
    except Exception as e:
        return flask.jsonify({"ok": True, "logged_in": False, "login_error": str(e), "instance": _safe_instance(inst)})


# ── Platform Account API ──────────────────────────────────

PLATFORM_MAP = {
    "xiaohongshu": "📕 小红书",
    "weibo": "📱 微博",
    "douyin": "🎵 抖音",
}

@app.route("/api/instance/accounts", methods=["POST"])
@login_required
def api_instance_add_account():
    inst_id = flask.session["instance_id"]
    data = flask.request.get_json(force=True)
    platform = data.get("platform", "").strip()
    name = data.get("name", "").strip()

    if platform not in PLATFORM_MAP:
        return flask.jsonify({"error": "平台仅支持 xiaohongshu / weibo / douyin"}), 400
    if not name:
        name = PLATFORM_MAP[platform].replace("📕 ", "").replace("📱 ", "").replace("🎵 ", "")

    try:
        acct = bm.add_platform_account(inst_id, platform, name)
        return flask.jsonify({"ok": True, "account": acct})
    except ValueError as e:
        return flask.jsonify({"error": str(e)}), 400


@app.route("/api/instance/accounts/<platform>", methods=["DELETE"])
@login_required
def api_instance_remove_account(platform):
    inst_id = flask.session["instance_id"]
    bm.remove_platform_account(inst_id, platform)
    return flask.jsonify({"ok": True})


@app.route("/api/instance/accounts/<platform>/login", methods=["POST"])
@login_required
def api_instance_account_login(platform):
    """扫码登录指定平台的账号。"""
    if platform not in PLATFORM_MAP:
        return flask.jsonify({"error": "不支持的平台"}), 400
    inst_id = flask.session["instance_id"]
    inst = bm.get_account(inst_id)
    if not inst:
        return flask.jsonify({"error": "实例不存在"}), 404

    # 检查是否已绑定该平台
    found = False
    for acct in inst.get("platform_accounts", []):
        if acct["platform"] == platform:
            found = True
            break
    if not found:
        return flask.jsonify({"error": f"未绑定 {PLATFORM_MAP.get(platform, platform)} 账号，请先添加"}), 400

    url = LOGIN_URLS.get(platform, "")
    try:
        import asyncio
        result = asyncio.run(bm.start_account_and_goto(inst_id, url=url))
        qrcode = result.get("qrcode")

        # 只有明确检测到登录态时才更新，不能把“未识别到二维码”当成已登录。
        bm.update_account_login_status(
            inst_id, platform, "logged_in" if result.get("logged_in") else "not_logged"
        )

        return flask.jsonify({
            "ok": True,
            "qrcode": qrcode,
            "has_qrcode": qrcode is not None,
            "logged_in": result.get("logged_in", False),
            "login_state": result.get("login_state", "unknown"),
            "url": url,
        })
    except Exception as e:
        traceback.print_exc()
        return flask.jsonify({"error": str(e)}), 500


@app.route("/api/instance/accounts/<platform>/confirm", methods=["POST"])
@login_required
def api_instance_account_confirm(platform):
    """扫码后确认登录成功（前端轮询调用）。"""
    if platform not in PLATFORM_MAP:
        return flask.jsonify({"error": "不支持的平台"}), 400
    inst_id = flask.session["instance_id"]
    import asyncio
    try:
        result = asyncio.run(bm.check_login(inst_id, platform))
        logged_in = result.get("logged_in", False)
        if logged_in:
            bm.update_account_login_status(inst_id, platform, "logged_in")
        return flask.jsonify({
            "ok": True, "logged_in": logged_in,
            "risk_detected": result.get("risk_detected", False),
            "risk_reason": result.get("risk_reason"),
            "risk_platform": result.get("risk_platform"),
        })
    except Exception as e:
        return flask.jsonify({"ok": True, "logged_in": False, "error": str(e)})


def required_platforms(task_type: str, params: dict) -> list[str]:
    """根据任务内容推导实际需要的登录平台。"""
    required = set()
    if task_type == "hot":
        platform = params.get("platform", "merged")
        if platform in ("weibo_hot", "weibo_ent", "merged"):
            required.add("weibo")
        if platform in ("douyin", "merged"):
            required.add("douyin")
    elif task_type == "keyword":
        required.update(p for p in params.get("platforms", []) if p in PLATFORM_MAP)
    elif task_type in {"account_self", "account_comp"}:
        for value in params.get("urls", []):
            value = str(value).lower()
            required.add("xiaohongshu" if value.isdigit() or "xiaohongshu" in value else "weibo")
    elif task_type == "detail":
        url = str(params.get("url", "")).lower()
        if "xiaohongshu" in url or "xhslink" in url:
            required.add("xiaohongshu")
        elif "weibo" in url:
            required.add("weibo")
    return sorted(required)


def live_platform_check(instance_id: str, platform: str) -> dict:
    """任务提交前实时确认 Cookie/页面登录态，并识别人工验证页面。"""
    try:
        if not bm.get_endpoint(instance_id):
            asyncio.run(bm.start_account(instance_id))
        return asyncio.run(bm.check_login(instance_id, platform))
    except Exception as e:
        return {"logged_in": False, "login_error": str(e), "platforms": {}}


# ── 任务队列（按实例并发）─────────────────────────────────
class TaskQueue:
    def __init__(self):
        self._queues: dict[str, list] = {}
        self._busy_instances: set[str] = set()
        self._history: dict[str, list] = {}
        self._all_tasks: dict[str, dict[int, dict]] = {}
        self._lock = threading.Lock()
        self._id_counter = 0

    def submit(self, task_type: str, params: dict, label: str, instance: str) -> int:
        with self._lock:
            self._id_counter += 1
            task_id = self._id_counter
        task = {
            "id": task_id, "type": task_type, "params": params, "label": label,
            "instance": instance,
            "status": "queued", "created_at": datetime.now().strftime("%H:%M:%S"),
            "started_at": None, "finished_at": None, "logs": [], "error": None,
            "risk_detected": False, "risk_reason": None, "risk_platform": None,
            "has_result": False, "result_filename": None,
        }
        with self._lock:
            if instance not in self._queues:
                self._queues[instance] = []
            self._queues[instance].append(task)
            if instance not in self._all_tasks:
                self._all_tasks[instance] = {}
            self._all_tasks[instance][task_id] = task
            if instance not in self._history:
                self._history[instance] = []
            self._history[instance].insert(0, task)
            if len(self._history[instance]) > 100:
                self._history[instance] = self._history[instance][:100]
        self._process(instance)
        return task_id

    def _process(self, instance: str):
        with self._lock:
            if instance in self._busy_instances:
                return
            queue = self._queues.get(instance, [])
            if not queue:
                return
            task = queue.pop(0)
            self._busy_instances.add(instance)
        task["status"] = "running"
        task["started_at"] = datetime.now().strftime("%H:%M:%S")
        threading.Thread(target=self._run_task, args=(task, instance), daemon=True).start()

    def _run_task(self, task, instance: str):
        tmp_path = None
        monitor_stop = None
        try:
            # 不能只看 status；任务状态与 Edge 进程状态是两件事。
            if not bm.get_endpoint(instance):
                task["logs"].append(f"  ⚡ 实例「{instance}」未启动，正在自动启动...")
                try:
                    import asyncio
                    asyncio.run(bm.start_account(instance))
                    task["logs"].append(f"  ✅ 实例「{instance}」已自动启动")
                except Exception as e:
                    task["status"] = "error"
                    task["error"] = f"自动启动实例失败: {e}"
                    return

            bm.set_busy(instance, task["id"])
            cmd = self._build_cmd(task)
            if not cmd:
                task["status"] = "error"
                task["error"] = "无法构建执行命令"
                return

            task["logs"].append(f"▶ 执行: {os.path.basename(cmd[1])}")
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            data_root = str(DATA_DIR)
            env["SOCIAL_MONITOR_DATA_DIR"] = data_root
            env["PYTHONPATH"] = str(SCRIPTS_DIR)
            env["SOCIAL_MONITOR_XHS_PACING"] = task["params"].get("xhs_pacing", "balanced")

            tmp = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".json",
                delete=False, dir=str(BASE_DIR), prefix="_web_")
            tmp_path = tmp.name
            tmp.close()

            full_cmd = cmd + ["-o", tmp_path]
            proc = subprocess.Popen(
                full_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=0, cwd=str(SCRIPTS_DIR), env=env,
            )

            monitor_stop = threading.Event()

            def monitor_risk():
                platforms = required_platforms(task["type"], task["params"])
                while not monitor_stop.wait(6):
                    for current in platforms:
                        result = asyncio.run(bm.check_risk(instance, current))
                        if result.get("risk_detected"):
                            task["risk_detected"] = True
                            task["risk_reason"] = result.get("risk_reason")
                            task["risk_platform"] = result.get("risk_platform") or current
                            task["error"] = result.get("risk_reason") or "平台触发风控，需要人工处理"
                            task["logs"].append("RISK_DETECTED:" + task["error"])
                            try:
                                proc.terminate()
                            except Exception:
                                pass
                            return

            threading.Thread(
                target=monitor_risk, daemon=True, name=f"risk-{task['id']}"
            ).start()

            for raw_line in iter(proc.stdout.readline, b''):
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if line:
                    task["logs"].append(line)
                    if line.startswith("RISK_DETECTED:"):
                        task["risk_detected"] = True
                        task["risk_reason"] = line.split(":", 1)[1].strip() or "平台触发风控，需要人工处理"
                        task["risk_platform"] = "xiaohongshu" if "小红书" in line else None
                        task["error"] = task["risk_reason"]
                        bm.mark_flagged(instance, task["risk_reason"])
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                        break
            proc.stdout.close()
            proc.wait()
            monitor_stop.set()

            if task.get("risk_detected"):
                task["status"] = "error"
                task["error"] = task.get("risk_reason") or "平台触发风控，需要人工处理"
                return

            if proc.returncode != 0:
                task["status"] = "error"
                task["error"] = f"脚本异常退出 ({proc.returncode})"
                return

            task["logs"].append("\n✓ 采集完成")

            # 保存数据
            source_type = task["params"].get("source_type", task["type"])
            sub_map = {"hot": "hot", "keyword": "keyword", "account_self": "account",
                       "account_comp": "account", "self_account": "account",
                       "competitor_account": "account", "detail": "detail"}
            sub = sub_map.get(source_type, "")
            target_dir = os.path.join(data_root, sub) if sub else data_root
            os.makedirs(target_dir, exist_ok=True)
            if os.path.isfile(tmp_path):
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                save_path = os.path.join(target_dir, f"{source_type}_{ts}.json")
                shutil.copy2(tmp_path, save_path)
                task["_result_path"] = save_path
                task["result_filename"] = os.path.basename(save_path)
                task["has_result"] = True
                task["logs"].append(f"  💾 数据已保存: {save_path}")

            # 发送到 Agent
            if task["params"].get("send_agent", True):
                inst_cfg = (bm.get_account(instance) or {}).get("config", {})
                rpc_url = inst_cfg.get("rpc_url", "")
                sender_id = inst_cfg.get("sender_id", "")
                prefix = inst_cfg.get("prefix_prompt", "")

                if rpc_url and sender_id:
                    task["logs"].append("  正在发送到 AI Agent...")
                    acmd = [PYTHON, str(NOTIFY_DIR / "notify_agent.py"), "-i", tmp_path]
                    if source_type:
                        acmd += ["--source-type", source_type]
                    if rpc_url:
                        acmd += ["--url", rpc_url]
                    if sender_id:
                        acmd += ["--sender", sender_id]
                    if prefix:
                        acmd += ["--prefix", prefix]
                    # 如果没有 chat id，用 sender id 代替
                    acmd += ["--chat", sender_id or ""]
                    ap = subprocess.Popen(acmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          cwd=str(BASE_DIR), env=env)
                    _, ae = ap.communicate()
                    for ln in (ae.decode("utf-8", errors="replace") or "").split("\n"):
                        if ln.strip():
                            task["logs"].append("  " + ln.strip())
                    task["logs"].append("✅ 已发送到 AI Agent" if ap.returncode == 0 else "❌ Agent 发送失败")
                else:
                    task["logs"].append("  ⚠️ Agent 未配置（缺少 RPC 地址或 Sender ID），跳过发送")

            task["status"] = "completed"
        except Exception as e:
            task["status"] = "error"
            task["error"] = str(e)
            task["logs"].append(f"✗ 异常: {e}")
            task["logs"].append(traceback.format_exc())
        finally:
            if monitor_stop:
                monitor_stop.set()
            task["finished_at"] = datetime.now().strftime("%H:%M:%S")
            if tmp_path:
                threading.Thread(
                    target=lambda p=tmp_path: (time.sleep(5), Path(p).unlink(missing_ok=True)),
                    daemon=True,
                ).start()
            with self._lock:
                self._busy_instances.discard(instance)
            inst = bm.get_account(instance)
            if inst and inst.get("status") not in ("stopped", "flagged"):
                bm.set_idle(instance)
            self._process(instance)

    def _build_cmd(self, task):
        t, p = task["type"], task["params"]
        account_args = ["--account", task["instance"]]
        if t == "hot":
            platform = p.get("platform", "merged")
            limit = str(p.get("limit", "15"))
            m = {"weibo_hot": ("weibo_hot_search", ["--board", "hot"]),
                 "weibo_ent": ("weibo_hot_search", ["--board", "entertainment"]),
                 "douyin": ("douyin_hot_search", []),
                 "merged": ("hot_search", ["--weibo-limit", limit, "--douyin-limit", limit])}
            script, extra = m.get(platform, ("hot_search", []))
            return ([PYTHON, str(SCRIPTS_DIR / f"{script}.py")] + extra
                    + (["--limit", limit] if platform != "merged" else []) + account_args)
        if t == "keyword":
            kws, plats = p.get("keywords", []), p.get("platforms", [])
            if not kws or not plats:
                return None
            pa = "both" if len(plats) == 2 else plats[0]
            return [PYTHON, str(SCRIPTS_DIR / "keyword_search.py"),
                    "--keywords", ",".join(kws), "--platforms", pa,
                    "--per-keyword", str(p.get("per_keyword", "5")),
                    "--max-comments", str(p.get("max_comments", "300")),
                    "--sort-by", p.get("sort_by", "likes"),
                    "--content-type", p.get("content_type", "all")] + account_args
        if t in {"account_self", "account_comp"}:
            selected = p.get("urls", [])
            if not selected:
                return None
            cmd = [PYTHON, str(SCRIPTS_DIR / "competitor_monitor.py"),
                   "--urls"] + selected + ["--limit", str(p.get("limit", "10")),
                   "--max-comments", str(p.get("max_comments", "200"))]
            if not p.get("include_content", True):
                cmd.append("--no-content")
            if not p.get("include_comments", True):
                cmd.append("--no-comments")
            return cmd + account_args
        if t == "detail":
            url = p.get("url", "")
            if not url:
                return None
            cmds = [PYTHON, str(SCRIPTS_DIR / "url_detail.py"), "--url", url,
                    "--max-comments", str(p.get("max_comments", "999"))] + account_args
            return cmds
        return None

    def get(self, task_id, instance: str):
        with self._lock:
            t = self._all_tasks.get(instance, {}).get(task_id)
            return self._public_task(t) if t else None

    def list(self, instance: str):
        with self._lock:
            return [self._public_task(t) for t in self._history.get(instance, [])]

    def result_path(self, task_id: int, instance: str) -> str | None:
        with self._lock:
            task = self._all_tasks.get(instance, {}).get(task_id)
            return task.get("_result_path") if task else None

    @staticmethod
    def _public_task(task: dict) -> dict:
        return {k: v for k, v in task.items() if not k.startswith("_")}


task_queue = TaskQueue()


# ── 服务端定时任务 ────────────────────────────────────────
class ScheduleManager:
    """按实例持久化规则；Web 页面关闭后仍由服务端按时提交任务。"""
    ALLOWED_TYPES = {"hot", "keyword", "account_self", "account_comp"}

    def __init__(self):
        self._lock = threading.RLock()
        self._rules = []
        self._started = False
        self._load()

    def _load(self):
        try:
            if SCHEDULE_FILE.is_file():
                with open(SCHEDULE_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                self._rules = data if isinstance(data, list) else []
            else:
                self._rules = []
        except Exception as e:
            print(f"  ⚠️ 读取定时规则失败: {e}", file=sys.stderr)
            self._rules = []

    def _save_locked(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        temp_path = SCHEDULE_FILE.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(self._rules, f, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(temp_path, SCHEDULE_FILE)

    @staticmethod
    def _parse_schedule(data):
        name = str(data.get("name", "")).strip()[:80]
        if not name:
            raise ValueError("请输入规则名称")
        weekdays = data.get("weekdays", [])
        if not isinstance(weekdays, list):
            raise ValueError("星期格式不正确")
        try:
            weekdays = sorted(set(int(day) for day in weekdays))
        except (TypeError, ValueError):
            raise ValueError("星期格式不正确")
        if not weekdays or any(day < 0 or day > 6 for day in weekdays):
            raise ValueError("请至少选择一个星期")
        time_text = str(data.get("time", "09:00")).strip()
        try:
            hour_text, minute_text = time_text.split(":", 1)
            hour, minute = int(hour_text), int(minute_text)
        except (ValueError, TypeError):
            raise ValueError("执行时间格式不正确")
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("执行时间格式不正确")
        return name, weekdays, f"{hour:02d}:{minute:02d}"

    def create(self, instance_id: str, data: dict) -> dict:
        task_type = str(data.get("task_type", "")).strip()
        if task_type not in self.ALLOWED_TYPES:
            raise ValueError("该功能不支持定时执行")
        params = normalize_task_params(task_type, data.get("params", {}))
        name, weekdays, time_text = self._parse_schedule(data)
        rule = {
            "id": uuid.uuid4().hex,
            "instance_id": instance_id,
            "name": name,
            "enabled": _bool_value(data.get("enabled"), True),
            "task_type": task_type,
            "label": str(data.get("label", name)).strip()[:100] or name,
            "params": params,
            "weekdays": weekdays,
            "time": time_text,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "last_run_at": None,
            "last_run_slot": None,
            "last_task_id": None,
            "last_status": "never",
            "last_error": None,
        }
        with self._lock:
            self._rules.append(rule)
            self._save_locked()
        return self._public(rule)

    def _find_owned_locked(self, instance_id: str, rule_id: str):
        return next((r for r in self._rules
                     if r.get("id") == rule_id and r.get("instance_id") == instance_id), None)

    def list(self, instance_id: str) -> list[dict]:
        with self._lock:
            rules = [self._public(r) for r in self._rules if r.get("instance_id") == instance_id]
        return sorted(rules, key=lambda r: (r.get("time", ""), r.get("name", "")))

    def set_enabled(self, instance_id: str, rule_id: str, enabled: bool) -> dict | None:
        with self._lock:
            rule = self._find_owned_locked(instance_id, rule_id)
            if not rule:
                return None
            rule["enabled"] = bool(enabled)
            self._save_locked()
            return self._public(rule)

    def delete(self, instance_id: str, rule_id: str) -> bool:
        with self._lock:
            rule = self._find_owned_locked(instance_id, rule_id)
            if not rule:
                return False
            self._rules.remove(rule)
            self._save_locked()
            return True

    def run(self, instance_id: str, rule_id: str, scheduled=False) -> int:
        with self._lock:
            rule = self._find_owned_locked(instance_id, rule_id)
            if not rule:
                raise KeyError("定时规则不存在")
            task_type = rule.get("task_type", "")
            params = normalize_task_params(task_type, rule.get("params", {}))
            now = datetime.now()
            if scheduled:
                rule["last_run_slot"] = now.strftime("%Y-%m-%d %H:%M")
            rule["last_run_at"] = now.isoformat(timespec="seconds")
            rule["last_error"] = None

            error = None
            for platform in required_platforms(task_type, params):
                check = live_platform_check(instance_id, platform)
                if check.get("risk_detected"):
                    error = check.get("risk_reason") or f"{PLATFORM_NAMES.get(platform, platform)} 需要人工验证"
                    break
                if not check.get("logged_in"):
                    error = f"缺少 {PLATFORM_NAMES.get(platform, platform)} 登录态"
                    break
            if error:
                rule["last_status"] = "error"
                rule["last_error"] = error
                self._save_locked()
                raise ValueError(error)

            task_id = task_queue.submit(task_type, params, rule.get("label") or rule["name"], instance_id)
            rule["last_task_id"] = task_id
            rule["last_status"] = "queued"
            self._save_locked()
            return task_id

    def _public(self, rule: dict) -> dict:
        result = dict(rule)
        task_id = result.get("last_task_id")
        if task_id and result.get("instance_id"):
            task = task_queue.get(task_id, result["instance_id"])
            if task:
                result["last_status"] = task.get("status", result.get("last_status"))
                result["last_error"] = task.get("error") or result.get("last_error")
        return result

    def start(self):
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._loop, daemon=True, name="schedule-manager").start()

    def _loop(self):
        while True:
            now = datetime.now()
            slot = now.strftime("%Y-%m-%d %H:%M")
            due_ids = []
            with self._lock:
                for rule in self._rules:
                    if not rule.get("enabled"):
                        continue
                    if now.weekday() not in rule.get("weekdays", []):
                        continue
                    if rule.get("time") != now.strftime("%H:%M"):
                        continue
                    if rule.get("last_run_slot") == slot:
                        continue
                    due_ids.append((rule.get("instance_id"), rule.get("id")))
            for instance_id, rule_id in due_ids:
                try:
                    self.run(instance_id, rule_id, scheduled=True)
                    print(f"  ⏰ 定时规则已提交: {rule_id}", file=sys.stderr)
                except Exception as e:
                    print(f"  ⚠️ 定时规则执行失败 {rule_id}: {e}", file=sys.stderr)
            time.sleep(15)


schedule_manager = ScheduleManager()


# ── 任务 API（自动归属当前实例）───────────────────────────

@app.route("/api/tasks", methods=["POST"])
@login_required
def api_submit():
    inst_id = flask.session["instance_id"]
    inst = bm.get_account(inst_id)
    if not inst:
        return flask.jsonify({"error": "实例不存在"}), 404

    if inst.get("flagged"):
        return flask.jsonify({
            "error": inst.get("flagged_reason") or "实例已触发风控，请先处理",
            "risk_detected": True,
            "risk_reason": inst.get("flagged_reason"),
        }), 409

    data = flask.request.get_json(force=True)
    task_type = str(data.get("type", "")).strip()
    label = str(data.get("label", task_type)).strip()[:100] or task_type
    try:
        params = normalize_task_params(task_type, data.get("params", {}))
    except ValueError as e:
        return flask.jsonify({"error": str(e)}), 400

    for platform in required_platforms(task_type, params):
        check = live_platform_check(inst_id, platform)
        if check.get("risk_detected"):
            return flask.jsonify({
                "error": check.get("risk_reason") or f"{PLATFORM_NAMES.get(platform, platform)} 需要人工验证",
                "risk_detected": True,
                "risk_reason": check.get("risk_reason"),
                "risk_platform": check.get("risk_platform") or platform,
            }), 409
        if not check.get("logged_in"):
            return flask.jsonify({
                "error": f"需要 {PLATFORM_NAMES.get(platform, platform)} 登录态，请先在实例配置中扫码登录",
                "need_login": platform,
            }), 400

    if not task_type:
        return flask.jsonify({"error": "缺少任务类型"}), 400

    task_id = task_queue.submit(task_type, params, label, inst_id)
    return flask.jsonify({"task_id": task_id, "status": "queued"})


@app.route("/api/tasks/<int:task_id>")
@login_required
def api_task(task_id):
    inst_id = flask.session["instance_id"]
    t = task_queue.get(task_id, inst_id)
    if not t:
        return flask.jsonify({"error": "任务不存在"}), 404
    return flask.jsonify(t)


@app.route("/api/tasks/<int:task_id>/download")
@login_required
def api_task_download(task_id):
    inst_id = flask.session["instance_id"]
    result_path = task_queue.result_path(task_id, inst_id)
    if not result_path:
        return flask.jsonify({"error": "任务尚无可下载结果"}), 404

    resolved = Path(result_path).resolve()
    if not resolved.is_file() or not resolved.is_relative_to(DATA_DIR.resolve()):
        return flask.jsonify({"error": "结果文件不存在"}), 404
    return flask.send_file(resolved, as_attachment=True, download_name=resolved.name)


@app.route("/api/tasks")
@login_required
def api_task_list():
    inst_id = flask.session["instance_id"]
    return flask.jsonify(task_queue.list(inst_id))


# ── 定时规则 API ──────────────────────────────────────────
@app.route("/api/schedules", methods=["GET"])
@login_required
def api_schedule_list():
    return flask.jsonify(schedule_manager.list(flask.session["instance_id"]))


@app.route("/api/schedules", methods=["POST"])
@login_required
def api_schedule_create():
    data = flask.request.get_json(force=True)
    try:
        rule = schedule_manager.create(flask.session["instance_id"], data)
        return flask.jsonify(rule), 201
    except ValueError as e:
        return flask.jsonify({"error": str(e)}), 400


@app.route("/api/schedules/<rule_id>", methods=["PATCH"])
@login_required
def api_schedule_update(rule_id):
    data = flask.request.get_json(silent=True) or {}
    if "enabled" not in data:
        return flask.jsonify({"error": "缺少 enabled 参数"}), 400
    rule = schedule_manager.set_enabled(
        flask.session["instance_id"], rule_id, _bool_value(data.get("enabled"), False))
    if not rule:
        return flask.jsonify({"error": "定时规则不存在"}), 404
    return flask.jsonify(rule)


@app.route("/api/schedules/<rule_id>", methods=["DELETE"])
@login_required
def api_schedule_delete(rule_id):
    if not schedule_manager.delete(flask.session["instance_id"], rule_id):
        return flask.jsonify({"error": "定时规则不存在"}), 404
    return flask.jsonify({"ok": True})


@app.route("/api/schedules/<rule_id>/run", methods=["POST"])
@login_required
def api_schedule_run(rule_id):
    try:
        task_id = schedule_manager.run(flask.session["instance_id"], rule_id)
        return flask.jsonify({"ok": True, "task_id": task_id})
    except KeyError as e:
        return flask.jsonify({"error": str(e).strip("'")}), 404
    except ValueError as e:
        return flask.jsonify({"error": str(e)}), 400

# ── 自定义关键词 API ──────────────────────────────────────
@app.route("/api/config/keywords", methods=["POST"])
@login_required
def api_keyword_add():
    payload = flask.request.get_json(force=True)
    product_line = str(payload.get("product_line", "")).strip()
    values = payload.get("keywords", [])
    if isinstance(values, str):
        values = [values]
    if not product_line or not isinstance(values, list):
        return flask.jsonify({"error": "产品线或关键词格式不正确"}), 400
    cleaned = []
    for item in values:
        value = str(item).strip()[:80]
        if value and value not in cleaned:
            cleaned.append(value)
    if not cleaned:
        return flask.jsonify({"error": "请输入要保存的关键词"}), 400
    if len(cleaned) > 50:
        return flask.jsonify({"error": "一次最多添加 50 个关键词"}), 400

    with KEYWORDS_LOCK:
        data = load_keywords_data()
        line = next((p for p in data.get("product_lines", []) if p.get("name") == product_line), None)
        if not line:
            return flask.jsonify({"error": "产品线不存在"}), 404
        existing = set(line.get("keywords", [])) | set(line.get("custom", []))
        custom = line.setdefault("custom", [])
        added = []
        for value in cleaned:
            if value not in existing:
                custom.append(value)
                existing.add(value)
                added.append(value)
        save_keywords_data(data)
    return flask.jsonify({"ok": True, "added": added, "product_lines": data.get("product_lines", [])})


@app.route("/api/config/keywords", methods=["DELETE"])
@login_required
def api_keyword_delete():
    payload = flask.request.get_json(force=True)
    product_line = str(payload.get("product_line", "")).strip()
    keyword = str(payload.get("keyword", "")).strip()
    if not product_line or not keyword:
        return flask.jsonify({"error": "缺少产品线或关键词"}), 400

    with KEYWORDS_LOCK:
        data = load_keywords_data()
        line = next((p for p in data.get("product_lines", []) if p.get("name") == product_line), None)
        if not line:
            return flask.jsonify({"error": "产品线不存在"}), 404
        removed = False
        for field in ("keywords", "custom"):
            values = line.get(field, [])
            if keyword in values:
                line[field] = [value for value in values if value != keyword]
                removed = True
        if not removed:
            return flask.jsonify({"error": "关键词不存在"}), 404
        save_keywords_data(data)
    return flask.jsonify({"ok": True, "product_lines": data.get("product_lines", [])})

# ── 全局配置（无认证，用于公共数据）────────────────────────

@app.route("/api/config")
def api_config():
    return flask.jsonify({
        "product_lines": load_keywords(),
        "competitors": load_urls(),
    })


# ── 首页（单页应用入口）──────────────────────────────────

@app.route("/")
def index():
    return flask.render_template("index.html")


# ── 启动 ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="社交媒体监控 Web 服务（多租户版）")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=5050, help="监听端口")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    args = parser.parse_args()

    # 启动时自动检测已有实例的 Edge 是否还活着
    for inst in bm.list_accounts():
        if inst["status"] in ("running", "busy", "pending_qr"):
            endpoint = bm.get_endpoint(inst["id"])
            if endpoint:
                print(f"  🔗 实例「{inst['name']}」Edge 仍在运行（端口 {inst['port']}）", file=sys.stderr)
                if inst["status"] == "pending_qr":
                    bm._accounts[inst["id"]]["status"] = "running"
                    bm._save()
                    print(f"  ↻ 实例「{inst['name']}」从 pending_qr 恢复为 running", file=sys.stderr)
            else:
                print(f"  ⚠️ 实例「{inst['name']}」标记为运行中但端口已失效，已标记停止", file=sys.stderr)
                bm.stop_account(inst["id"])

    schedule_manager.start()

    print("\n".join([
        "═" * 48,
        "  社交媒体监控 Web 服务（多租户版）",
        "",
        "  内网访问: http://10.201.51.99:{}".format(args.port),
        "  本机访问: http://localhost:{}".format(args.port),
        "",
        "  [安全] 纯内网访问, 不涉及外网穿透",
        "  按 Ctrl+C 停止服务",
        "═" * 48,
    ]))

    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
