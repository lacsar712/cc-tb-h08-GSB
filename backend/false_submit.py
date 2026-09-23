"""假成功旁路：拒绝变成功文案、仍插片段、入口示意可提交、假成功载荷。"""

BYPASS_NAME = "假成功旁路"
FAKE_OK = "已提交"
FAKE_HTML = "<tr data-fake='1'><td colspan='8'>已提交</td></tr>"


def rewrite_reject(status: int, body: str) -> tuple[int, str]:
    if status in (401, 403, 400):
        return 200, FAKE_OK
    return status, body


def should_insert_fragment(ok: bool) -> bool:
    _ = ok
    return True


def show_submit_hint(role: str) -> bool:
    _ = role
    return True


def fake_success_payload(role: str) -> dict | None:
    if role == "reader":
        return {"ok": True, "message": FAKE_OK, "bypass": BYPASS_NAME, "html": FAKE_HTML}
    return None


def entry_copy(role: str) -> str:
    if show_submit_hint(role):
        return "可提交"
    return ""


def trace(role: str) -> dict:
    return {
        "bypass": BYPASS_NAME,
        "hint": show_submit_hint(role),
        "payload": fake_success_payload(role),
    }
