"""自动化对照核对：只读账号碰壁 vs 可写账号真写入。

运行（无需 PostgreSQL，db 用内存替身）：
    python3 backend/tests/test_access_control.py
    python3 -m unittest backend.tests.test_access_control
"""

import importlib.util
import os
import sys
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

import app as tea_app  # noqa: E402
from rules import weigh  # noqa: E402


class FakeCursor:
    def __init__(self, store):
        self.store = store
        self._result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        head = sql.strip().upper()
        if head.startswith("SELECT"):
            self._result = list(reversed(self.store.rows))  # ORDER BY id DESC
        elif head.startswith("INSERT"):
            lot, aroma, taste, liquor, score, verdict, note, created_by = params
            row = {
                "id": len(self.store.rows) + 1,
                "lot": lot,
                "aroma": aroma,
                "taste": taste,
                "liquor": liquor,
                "score": score,
                "verdict": verdict,
                "note": note,
                "created_by": created_by,
            }
            self.store.rows.append(row)
            self._result = dict(row)

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._result


class FakeConn:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self, cursor_factory=None):
        return FakeCursor(self.store)

    def commit(self):
        pass


class FakeStore:
    """与 seed.py 相同的初始数据。"""

    def __init__(self):
        self.rows = []
        for lot, aroma, taste, liquor in (("春茶-A", 8, 8, 7), ("夏茶-C", 5, 4, 6)):
            verdict, note, score = weigh(aroma, taste, liquor)
            self.rows.append(
                {
                    "id": len(self.rows) + 1,
                    "lot": lot,
                    "aroma": aroma,
                    "taste": taste,
                    "liquor": liquor,
                    "score": score,
                    "verdict": verdict,
                    "note": note,
                    "created_by": "taster",
                }
            )


def make_client():
    store = FakeStore()
    tea_app.db = lambda: FakeConn(store)  # type: ignore[attr-defined]
    tea_app.app.config.update(TESTING=True)
    return tea_app.app.test_client(), store


def login(client, username):
    password = {"taster": "tea123456", "observer": "look123456"}[username]
    resp = client.post(
        "/login", data={"username": username, "password": password}
    )
    assert resp.status_code in (302, 303), resp.status_code
    return client


def submit(client, lot="秋茶-B", aroma=9, taste=8, liquor=7, hx=True):
    headers = {"HX-Request": "true"} if hx else {}
    return client.post(
        "/cuppings",
        data={"lot": lot, "aroma": aroma, "taste": taste, "liquor": liquor},
        headers=headers,
    )


class ReadOnlyRejectTests(unittest.TestCase):
    """对照一：只读账号 observer 碰壁。"""

    def setUp(self):
        self.client, self.store = make_client()
        login(self.client, "observer")

    def test_entry_shows_no_submit_ui_or_hint(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("可提交", body, "入口页不得再对只读账号示意可提交")
        self.assertNotIn("<form", body, "只读账号不应看到提交表单")
        self.assertNotIn("新开一轮审评", body)

    def test_hx_submit_rejected_with_only_reason(self):
        before = len(self.store.rows)
        resp = submit(self.client)
        self.assertEqual(resp.status_code, 403)
        body = resp.get_data(as_text=True)
        # 拒绝时只留原因
        self.assertEqual(body.strip(), "仅审评员可提交拼配审评")
        # 不得伪装成成功
        self.assertNotIn("已提交", body)
        self.assertNotIn('"ok"', body)
        self.assertNotIn("data-fake", body)
        # 不得返回可插入的片段
        self.assertNotIn("<tr", body)
        self.assertNotIn("<td", body)
        # 库行数不变
        self.assertEqual(len(self.store.rows), before)

    def test_plain_submit_rejected_with_only_reason(self):
        before = len(self.store.rows)
        resp = submit(self.client, hx=False)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(
            resp.get_data(as_text=True).strip(), "仅审评员可提交拼配审评"
        )
        self.assertEqual(len(self.store.rows), before)

    def test_row_not_persisted_and_not_listed(self):
        submit(self.client, lot="幽灵批次")
        lots = [r["lot"] for r in self.store.rows]
        self.assertNotIn("幽灵批次", lots)
        home = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("幽灵批次", home)

    def test_repeated_rejects_keep_row_count(self):
        before = len(self.store.rows)
        for i in range(3):
            resp = submit(self.client, lot=f"被拒-{i}")
            self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(self.store.rows), before)


class WriterSuccessTests(unittest.TestCase):
    """对照二：可写账号 taster 真正写入。"""

    def setUp(self):
        self.client, self.store = make_client()
        login(self.client, "taster")

    def test_entry_shows_real_form_without_fake_hint(self):
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("<form", body, "可写账号应看到真实提交表单")
        self.assertNotIn("可提交", body, "成功入口也不应靠假提示文案")

    def test_hx_submit_persists_and_returns_real_fragment(self):
        before = len(self.store.rows)
        resp = submit(self.client, lot="秋茶-B", aroma=9, taste=8, liquor=7)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn("<tr", body, "真写入成功才返回行片段")
        self.assertIn("秋茶-B", body)
        self.assertNotIn("data-fake", body)
        self.assertEqual(len(self.store.rows), before + 1, "库行数应 +1")
        row = self.store.rows[-1]
        self.assertEqual(row["lot"], "秋茶-B")
        self.assertEqual(row["created_by"], "taster")
        expected_verdict, expected_note, expected_score = weigh(9, 8, 7)
        self.assertEqual(row["verdict"], expected_verdict)
        self.assertEqual(row["note"], expected_note)
        self.assertEqual(row["score"], expected_score)

    def test_new_row_listed_on_home_after_write(self):
        submit(self.client, lot="秋茶-B")
        home = self.client.get("/").get_data(as_text=True)
        self.assertIn("秋茶-B", home)

    def test_low_score_write_persists_fail_verdict(self):
        resp = submit(self.client, lot="冬茶-D", aroma=4, taste=4, liquor=5)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn("不通过", body)
        self.assertEqual(self.store.rows[-1]["verdict"], "不通过")

    def test_plain_submit_redirects_after_real_write(self):
        before = len(self.store.rows)
        resp = submit(self.client, hx=False)
        self.assertIn(resp.status_code, (302, 303))
        self.assertEqual(len(self.store.rows), before + 1)


class BypassRemovalTests(unittest.TestCase):
    """旁路本身必须被移除，而不是收成永远为真的开关或只改提示语。"""

    def test_false_submit_module_deleted(self):
        self.assertFalse(
            os.path.exists(os.path.join(BACKEND, "false_submit.py")),
            "false_submit.py 假成功模块必须删除",
        )
        self.assertIsNone(importlib.util.find_spec("false_submit"))

    def test_app_has_no_bypass_symbols(self):
        for name in (
            "rewrite_reject",
            "fake_success_payload",
            "show_submit_hint",
            "FAKE_HTML",
            "FAKE_OK",
        ):
            self.assertFalse(
                hasattr(tea_app, name), f"残留假成功符号: {name}"
            )
        with open(
            os.path.join(BACKEND, "app.py"), encoding="utf-8"
        ) as fh:
            source = fh.read()
        self.assertNotIn("false_submit", source)
        self.assertNotIn("can_write=True", source, "can_write 不得是永远为真的常量")
        self.assertIn('role == "writer"', source)

    def test_frontend_inserts_only_on_ok(self):
        with open(
            os.path.join(BACKEND, "templates", "base.html"), encoding="utf-8"
        ) as fh:
            base = fh.read()
        self.assertNotIn("data-fake", base)
        script = base[base.index("<script>") : base.index("</script>")]
        guard = script.index("if (!res.ok)")
        insert = script.index("insertAdjacentHTML")
        self.assertLess(
            guard,
            insert,
            "必须先判 !res.ok 并拦截，成功后才允许插入片段",
        )
        self.assertEqual(script.count("insertAdjacentHTML"), 1)
        # 拒绝分支必须在插入点之前 return
        branch = script[guard:insert]
        self.assertIn("return", branch)
        self.assertNotIn("已提交", script)

    def test_home_template_has_no_fake_hint(self):
        with open(
            os.path.join(BACKEND, "templates", "home.html"), encoding="utf-8"
        ) as fh:
            home = fh.read()
        self.assertNotIn("可提交", home)
        self.assertNotIn("show_submit_hint", home)


class AnonymousTests(unittest.TestCase):
    def test_anonymous_submit_redirects_to_login(self):
        client, store = make_client()
        before = len(store.rows)
        resp = client.post(
            "/cuppings",
            data={"lot": "X", "aroma": 8, "taste": 8, "liquor": 8},
        )
        self.assertIn(resp.status_code, (302, 303))
        self.assertIn("/login", resp.headers["Location"])
        self.assertEqual(len(store.rows), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
