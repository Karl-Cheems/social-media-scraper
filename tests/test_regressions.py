import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import web_server
from notify import notify_agent
from scripts import common
from scripts.browser_manager import BrowserManager, browser_manager


class TaskCommandTests(unittest.TestCase):
    def setUp(self):
        self.queue = web_server.TaskQueue()

    def command(self, task_type, params):
        return self.queue._build_cmd({
            "type": task_type,
            "params": params,
            "instance": "worker-a",
        })

    def test_every_task_command_uses_selected_instance(self):
        commands = [
            self.command("hot", {"platform": "weibo_hot", "limit": 5}),
            self.command("hot", {"platform": "douyin", "limit": 5}),
            self.command("hot", {"platform": "merged", "limit": 5}),
            self.command("keyword", {"keywords": ["元气森林"], "platforms": ["weibo"]}),
            self.command("account_comp", {"urls": ["https://weibo.com/example"]}),
            self.command("detail", {"url": "https://weibo.com/example/status"}),
        ]
        for command in commands:
            self.assertIsNotNone(command)
            index = command.index("--account")
            self.assertEqual(command[index + 1], "worker-a")

    def test_required_platforms_are_derived_from_task(self):
        self.assertEqual(web_server.required_platforms("hot", {"platform": "merged"}), ["douyin", "weibo"])
        self.assertEqual(web_server.required_platforms("hot", {"platform": "douyin"}), ["douyin"])
        self.assertEqual(
            web_server.required_platforms("account_comp", {"urls": ["27247124186", "https://weibo.com/a"]}),
            ["weibo", "xiaohongshu"],
        )
        self.assertEqual(
            web_server.required_platforms("detail", {"url": "https://www.xiaohongshu.com/explore/a"}),
            ["xiaohongshu"],
        )


class JsonOutputTests(unittest.TestCase):
    def test_non_finite_numbers_become_valid_json_null(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
            path = Path(handle.name)
        try:
            common.write_output(
                {"nan": math.nan, "inf": math.inf, "items": [1, -math.inf]},
                str(path),
            )
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("NaN", raw)
            self.assertNotIn("Infinity", raw)
            self.assertEqual(json.loads(raw), {"nan": None, "inf": None, "items": [1, None]})
        finally:
            path.unlink(missing_ok=True)

    def test_agent_payload_sanitizer_removes_nan(self):
        cleaned = notify_agent.sanitize_json({"value": math.nan, "nested": [math.inf]})
        self.assertEqual(cleaned, {"value": None, "nested": [None]})
        json.dumps(cleaned, allow_nan=False)


class LoginApiTests(unittest.TestCase):
    def setUp(self):
        web_server.app.config.update(TESTING=True)
        self.client = web_server.app.test_client()
        with self.client.session_transaction() as session:
            session["instance_id"] = "worker-a"
        self.instance = {
            "id": "worker-a",
            "name": "worker-a",
            "status": "running",
            "port": 10001,
            "config": {},
            "platform_accounts": [
                {"platform": "weibo", "name": "微博测试", "login_status": "not_logged"}
            ],
        }

    def test_missing_qrcode_is_not_treated_as_logged_in(self):
        result = {
            "endpoint": "http://127.0.0.1:10001",
            "qrcode": None,
            "logged_in": False,
            "login_state": "need_login",
        }
        with patch.object(web_server.bm, "get_account", return_value=self.instance),              patch.object(web_server.bm, "start_account_and_goto", AsyncMock(return_value=result)),              patch.object(web_server.bm, "update_account_login_status") as update:
            response = self.client.post("/api/instance/accounts/weibo/login")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["logged_in"])
        update.assert_called_once_with("worker-a", "weibo", "not_logged")

    def test_explicit_login_success_updates_platform(self):
        result = {
            "endpoint": "http://127.0.0.1:10001",
            "qrcode": None,
            "logged_in": True,
            "login_state": "logged_in",
        }
        with patch.object(web_server.bm, "get_account", return_value=self.instance),              patch.object(web_server.bm, "start_account_and_goto", AsyncMock(return_value=result)),              patch.object(web_server.bm, "update_account_login_status") as update:
            response = self.client.post("/api/instance/accounts/weibo/login")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["logged_in"])
        update.assert_called_once_with("worker-a", "weibo", "logged_in")

    def test_hot_task_requires_corresponding_platform_login(self):
        with patch.object(web_server.bm, "get_account", return_value=self.instance), \
             patch.object(web_server, "live_platform_check", return_value={"logged_in": False}):
            response = self.client.post(
                "/api/tasks",
                json={"type": "hot", "params": {"platform": "weibo_hot"}, "label": "微博热搜"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["need_login"], "weibo")

    def test_task_is_blocked_and_reports_runtime_risk(self):
        with patch.object(web_server.bm, "get_account", return_value=self.instance), \
             patch.object(web_server, "live_platform_check", return_value={
                 "logged_in": False,
                 "risk_detected": True,
                 "risk_reason": "微博需要人工验证：完成身份验证",
                 "risk_platform": "weibo",
             }):
            response = self.client.post(
                "/api/tasks",
                json={"type": "hot", "params": {"platform": "weibo_hot"}, "label": "微博热搜"},
            )
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.get_json()["risk_detected"])
        self.assertEqual(response.get_json()["risk_platform"], "weibo")


class DownloadApiTests(unittest.TestCase):
    def setUp(self):
        web_server.app.config.update(TESTING=True)
        self.client = web_server.app.test_client()
        with self.client.session_transaction() as session:
            session["instance_id"] = "worker-a"

    def test_completed_result_can_be_downloaded(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", dir=web_server.DATA_DIR, delete=False, encoding="utf-8"
        ) as handle:
            json.dump({"ok": True}, handle)
            path = Path(handle.name)
        try:
            with patch.object(web_server.task_queue, "result_path", return_value=str(path)):
                response = self.client.get("/api/tasks/9/download")
            self.assertEqual(response.status_code, 200)
            body = response.get_data()
            disposition = response.headers["Content-Disposition"]
            response.close()
            self.assertEqual(json.loads(body), {"ok": True})
            self.assertIn("attachment", disposition)
        finally:
            path.unlink(missing_ok=True)

    def test_download_rejects_path_outside_data_directory(self):
        with patch.object(
            web_server.task_queue, "result_path", return_value=str(Path(web_server.BASE_DIR) / "README.md")
        ):
            response = self.client.get("/api/tasks/9/download")
        self.assertEqual(response.status_code, 404)


class BrowserStateTests(unittest.TestCase):
    def test_platform_cookie_detection(self):
        self.assertTrue(browser_manager._has_login_cookie([{"name": "SUB", "value": "ok"}], "weibo"))
        self.assertTrue(browser_manager._has_login_cookie([{"name": "sessionid_ss", "value": "ok"}], "douyin"))
        self.assertFalse(browser_manager._has_login_cookie([{"name": "guest", "value": "1"}], "douyin"))

    def test_visible_identity_verification_is_reported_as_risk(self):
        page = AsyncMock()
        page.evaluate.return_value = "完成身份验证"
        reason = __import__("asyncio").run(browser_manager._detect_page_risk(page, "douyin"))
        self.assertEqual(reason, "完成身份验证")

    def test_xhs_comment_loop_stops_before_scrolling_when_risk_appears(self):
        page = MagicMock()
        container = MagicMock()
        container.is_visible = AsyncMock(return_value=True)
        container.hover = AsyncMock()
        page.locator.return_value.first = container
        page.wait_for_timeout = AsyncMock()
        page.evaluate = AsyncMock(return_value="访问过于频繁")
        with patch.dict(common.os.environ, {"SOCIAL_MONITOR_XHS_PACING": "conservative"}):
            with self.assertRaisesRegex(RuntimeError, "需要人工处理"):
                __import__("asyncio").run(common.xhs_expand_comments(page, 50))
        self.assertEqual(page.evaluate.await_count, 1)


class TaskParameterTests(unittest.TestCase):
    def test_keyword_parameters_are_normalized_without_hardcoded_defaults(self):
        params = web_server.normalize_task_params("keyword", {
            "keywords": ["气泡水", "气泡水", "联名"],
            "platforms": ["weibo", "xiaohongshu"],
            "per_keyword": 12,
            "max_comments": 456,
            "sort_by": "comments",
            "content_type": "image_text",
            "send_agent": False,
        })
        self.assertEqual(params["keywords"], ["气泡水", "联名"])
        self.assertEqual(params["per_keyword"], 12)
        self.assertEqual(params["max_comments"], 456)
        self.assertEqual(params["sort_by"], "comments")
        self.assertEqual(params["content_type"], "image_text")
        self.assertEqual(params["xhs_pacing"], "balanced")
        self.assertFalse(params["send_agent"])

        fast = web_server.normalize_task_params("keyword", {
            "keywords": ["测试"], "platforms": ["xiaohongshu"], "xhs_pacing": "fast",
        })
        self.assertEqual(fast["xhs_pacing"], "fast")

        invalid = web_server.normalize_task_params("keyword", {
            "keywords": ["测试"], "platforms": ["xiaohongshu"], "xhs_pacing": "unknown",
        })
        self.assertEqual(invalid["xhs_pacing"], "balanced")

    def test_account_content_and_comment_switches_reach_script(self):
        queue = web_server.TaskQueue()
        command = queue._build_cmd({
            "type": "account_comp",
            "instance": "worker-a",
            "params": {
                "urls": ["https://weibo.com/kfcchina"],
                "limit": 7,
                "max_comments": 88,
                "include_content": False,
                "include_comments": False,
            },
        })
        self.assertIn("--no-content", command)
        self.assertIn("--no-comments", command)
        self.assertEqual(command[command.index("--limit") + 1], "7")
        self.assertEqual(command[command.index("--max-comments") + 1], "88")

    def test_invalid_numeric_parameter_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "1 到 20"):
            web_server.normalize_task_params("keyword", {
                "keywords": ["测试"], "platforms": ["weibo"], "per_keyword": 99,
            })


class ScheduleManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.schedule_path = Path(self.temp_dir.name) / "schedule_rules.json"
        self.file_patch = patch.object(web_server, "SCHEDULE_FILE", self.schedule_path)
        self.file_patch.start()
        self.manager = web_server.ScheduleManager()

    def tearDown(self):
        self.file_patch.stop()
        self.temp_dir.cleanup()

    def test_rule_is_persisted_and_can_be_toggled(self):
        rule = self.manager.create("worker-a", {
            "name": "工作日热搜",
            "task_type": "hot",
            "label": "热搜合并",
            "params": {"platform": "merged", "limit": 9, "send_agent": False},
            "weekdays": [0, 1, 2, 3, 4],
            "time": "09:30",
        })
        self.assertEqual(rule["time"], "09:30")
        self.assertEqual(rule["params"]["limit"], 9)
        self.assertTrue(self.schedule_path.is_file())
        updated = self.manager.set_enabled("worker-a", rule["id"], False)
        self.assertFalse(updated["enabled"])
        self.assertEqual(len(self.manager.list("another-worker")), 0)

    def test_run_now_submits_saved_parameter_snapshot(self):
        rule = self.manager.create("worker-a", {
            "name": "关键词定时",
            "task_type": "keyword",
            "label": "关键词 1 个",
            "params": {"keywords": ["气泡水"], "platforms": ["weibo"], "per_keyword": 6},
            "weekdays": [0],
            "time": "10:00",
        })
        with patch.object(web_server, "live_platform_check", return_value={"logged_in": True}), \
             patch.object(web_server.task_queue, "submit", return_value=77) as submit:
            task_id = self.manager.run("worker-a", rule["id"])
        self.assertEqual(task_id, 77)
        submitted = submit.call_args.args
        self.assertEqual(submitted[0], "keyword")
        self.assertEqual(submitted[1]["per_keyword"], 6)
        self.assertEqual(submitted[3], "worker-a")
class MultiInstanceIsolationTests(unittest.TestCase):
    def test_stopped_instances_keep_distinct_reserved_ports(self):
        with tempfile.TemporaryDirectory() as td, \
             patch("scripts.browser_manager.ACCOUNTS_FILE", str(Path(td) / "instances.json")), \
             patch("scripts.browser_manager.PROFILES_DIR", str(Path(td) / "profiles")), \
             patch("scripts.browser_manager._port_is_open", return_value=False):
            manager = BrowserManager()
            first = manager.create_account("first", "first", "1234")
            second = manager.create_account("second", "second", "1234")
        self.assertNotEqual(first["port"], second["port"])

    def test_endpoint_rejects_stale_instance_pid(self):
        manager = BrowserManager.__new__(BrowserManager)
        manager._accounts = {
            "first": {"status": "running", "pid": 12345, "port": 10001}
        }
        with patch.object(manager, "_is_process_alive", return_value=False):
            self.assertIsNone(manager.get_endpoint("first"))
class KeywordPersistenceApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        (self.config_dir / "keywords.json").write_text(json.dumps({
            "product_lines": [{"name": "测试线", "keywords": ["预设词"], "custom": ["旧自定义"]}]
        }, ensure_ascii=False), encoding="utf-8")
        self.config_patch = patch.object(web_server, "CONFIG_DIR", self.config_dir)
        self.config_patch.start()
        web_server.app.config.update(TESTING=True)
        self.client = web_server.app.test_client()
        with self.client.session_transaction() as session:
            session["instance_id"] = "worker-a"

    def tearDown(self):
        self.config_patch.stop()
        self.temp_dir.cleanup()

    def test_added_keywords_are_persisted(self):
        response = self.client.post("/api/config/keywords", json={
            "product_line": "测试线", "keywords": ["新增词", "新增词"]
        })
        self.assertEqual(response.status_code, 200)
        saved = json.loads((self.config_dir / "keywords.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["product_lines"][0]["custom"], ["旧自定义", "新增词"])

    def test_preset_and_custom_keywords_can_both_be_deleted(self):
        for keyword in ("预设词", "旧自定义"):
            response = self.client.delete("/api/config/keywords", json={
                "product_line": "测试线", "keyword": keyword
            })
            self.assertEqual(response.status_code, 200)
        line = json.loads((self.config_dir / "keywords.json").read_text(encoding="utf-8"))["product_lines"][0]
        self.assertEqual(line["keywords"], [])
        self.assertEqual(line["custom"], [])
if __name__ == "__main__":
    unittest.main()