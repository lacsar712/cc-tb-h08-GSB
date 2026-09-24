"""对照自动化：只读账号碰壁 vs 可写账号成功。

不依赖真实 PostgreSQL：用内存假库替换 app.db，直接断言库行数变化。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app as app_module  # noqa: E402

REASON = "仅审评员可提交拼配审评"
FAKE_OK = "已提交"


class FakeCursor:
    def __init__(self, store):
        self.store = store
        self._result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT * FROM cuppings"):
            self._result = list(reversed(self.store))  # ORDER BY id DESC
        elif normalized.startswith("INSERT INTO cuppings"):
            lot, aroma, taste, liquor, score, verdict, note, user = params
            row = {
                "id": len(self.store) + 1,
                "lot": lot,
                "aroma": aroma,
                "taste": taste,
                "liquor": liquor,
                "score": score,
                "verdict": verdict,
                "note": note,
                "created_by": user,
            }
            self.store.append(row)
            self._result = row
        else:  # pragma: no cover - 防御未知 SQL
            raise AssertionError(f"unexpected SQL: {normalized}")

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


@pytest.fixture
def env(monkeypatch):
    store = []
    monkeypatch.setattr(app_module, "db", lambda: FakeConn(store))
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as client:
        yield client, store


def login(client, username, password):
    res = client.post("/login", data={"username": username, "password": password})
    assert res.status_code == 302
    return res


def submit(client, hx=False):
    payload = {"lot": "秋茶-X", "aroma": "9", "taste": "9", "liquor": "9"}
    headers = {"HX-Request": "true"} if hx else {}
    return client.post("/cuppings", data=payload, headers=headers)


# ---------- 只读账号：四面都不能假装成功 ----------


def test_reader_entry_shows_no_submit_signal(env):
    client, _ = env
    login(client, "observer", "look123456")
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "可提交" not in html  # 入口不再示意可提交
    assert "<form" not in html  # 没有提交表单


def test_reader_rejected_plain_post(env):
    client, store = env
    login(client, "observer", "look123456")
    before = len(store)
    res = submit(client, hx=False)
    assert res.status_code == 403
    body = res.get_data(as_text=True)
    assert REASON in body  # 只留原因
    assert FAKE_OK not in body  # 不得被改成成功文案
    assert "<tr" not in body  # 不带可插入的片段
    assert len(store) == before  # 库行数不变


def test_reader_rejected_hx_post(env):
    client, store = env
    login(client, "observer", "look123456")
    before = len(store)
    res = submit(client, hx=True)
    assert res.status_code == 403
    body = res.get_data(as_text=True)
    assert REASON in body
    assert FAKE_OK not in body
    assert "data-fake" not in body  # 假片段载荷清掉了
    assert "<tr" not in body
    assert len(store) == before


# ---------- 可写账号：真正写入成功才有成功提示与片段 ----------


def test_writer_entry_can_submit(env):
    client, _ = env
    login(client, "taster", "tea123456")
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "可提交" in html
    assert "<form" in html


def test_writer_hx_success_returns_row_fragment(env):
    client, store = env
    login(client, "taster", "tea123456")
    before = len(store)
    res = submit(client, hx=True)
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "<tr" in body  # 真片段
    assert "秋茶-X" in body
    assert "通过" in body
    assert len(store) == before + 1  # 库行数 +1
    row = store[-1]
    assert row["created_by"] == "taster"
    assert row["verdict"] == "通过"
    assert row["score"] == 9.0


def test_writer_plain_post_redirects_home(env):
    client, store = env
    login(client, "taster", "tea123456")
    before = len(store)
    res = submit(client, hx=False)
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/")
    assert len(store) == before + 1


# ---------- 旁路模块本身已清除 ----------


def test_bypass_module_removed():
    assert "false_submit" not in sys.modules
    here = os.path.dirname(os.path.abspath(__file__))
    assert not os.path.exists(os.path.join(here, "false_submit.py"))
