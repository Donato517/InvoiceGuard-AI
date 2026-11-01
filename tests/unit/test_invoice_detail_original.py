"""測試目標：AI 原值分類、詳情頁的 UUID／狀態／提交輪次，以及本機虛構展示頁（合成資料，不連任何服務）

正式詳情路由（/invoices/{uuid}）的測試一律使用符合 Stage 1 契約的 Mock 回應（stage1_detail.build_api_detail），
不使用 fixture 格式；fixture 專屬輸入（AI 原始快照、issue 的 line_no／expected／actual）只走 Demo 路由或 builder。
這些是 Mock 測試，不代表與真實 API 整合通過。
"""

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from stage1_detail import API_DETAIL_ID, build_api_detail

from app.clients import invoices as invoices_client
from app.clients.base import ApiError
from app.core.config import settings
from app.utils.demo_invoice import DEMO_INVOICE_ID, build_demo_invoice
from app.utils.field_changes import compare_to_original, detect_field_changes
from app.utils.invoice_confirmation import build_confirmation_view
from app.utils.invoice_status import APPROVAL_STATUS_LABEL, round_label, status_view

UUID_TEXT = "123e4567-e89b-42d3-a456-426614174000"


def _items(view: Any) -> Any:
    return next(s for s in view.sections if s.kind == "items")


def _part(view: Any, field_id: str, label: str | None = None) -> Any:
    section = next(s for s in view.sections if s.kind == "field" and s.field.field_id == field_id)
    return next(p for p in section.parts if p.label == label)


# ---- compare_to_original：六種狀態 ----


@pytest.mark.parametrize(
    ("snapshot", "current", "status"),
    [
        ({"k": "A"}, "A", "unchanged"),
        ({"k": " A "}, "A", "unchanged"),
        ({"k": 100}, "100", "unchanged"),
        ({"k": Decimal("100")}, 100, "unchanged"),
        ({"k": "A"}, "B", "modified"),
        ({"k": "A"}, None, "modified"),
        ({"k": None}, "B", "original_null"),
        ({"k": "  "}, "B", "original_null"),
        ({"k": None}, None, "original_null"),
        ({"other": "A"}, "A", "field_missing"),
        ({}, "A", "field_missing"),
        (None, "A", "no_snapshot"),
        ("not-a-mapping", "A", "no_snapshot"),
        ({"k": 1.5}, "1.5", "not_comparable"),
        ({"k": "A"}, ["x"], "not_comparable"),
    ],
)
def test_compare_to_original_statuses(snapshot: Any, current: Any, status: str) -> None:
    assert compare_to_original(snapshot, "k", current).status == status


def test_missing_original_is_never_reported_as_unchanged() -> None:
    for snapshot in (None, {}, {"k": None}):
        assert compare_to_original(snapshot, "k", "A").status != "unchanged"


def test_compare_to_original_keeps_values_only_when_meaningful() -> None:
    modified = compare_to_original({"k": "A"}, "k", "B")
    assert (modified.original, modified.current) == ("A", "B")
    assert compare_to_original({"k": None}, "k", "B").original is None


def test_compare_to_original_does_not_mutate_snapshot() -> None:
    snapshot = {"k": "A"}
    compare_to_original(snapshot, "k", "B")
    assert snapshot == {"k": "A"}


def test_detect_field_changes_behavior_is_unchanged() -> None:
    """既有 detect_field_changes 仍要求完整快照（本輪未更動其行為）。"""
    with pytest.raises(Exception, match="缺少必要結構 key"):
        detect_field_changes({}, {})


# ---- 狀態與輪次 ----


def test_all_nine_status_codes_have_labels() -> None:
    assert set(APPROVAL_STATUS_LABEL) == {
        "draft",
        "pending_department_approval",
        "pending_accounting_review",
        "pending_accounting_approval",
        "approved",
        "returned_to_applicant",
        "returned_to_accounting",
        "rejected",
        "voided",
    }
    for code, label in APPROVAL_STATUS_LABEL.items():
        view = status_view(code)
        assert (view.code, view.label, view.known) == (code, label, True)


@pytest.mark.parametrize(
    ("raw", "label"),
    [(None, "-"), ("", "-"), ("  ", "-"), (5, "-"), ("pending", "未知狀態（pending）")],
)
def test_unknown_or_missing_status_is_safe(raw: Any, label: str) -> None:
    view = status_view(raw)
    assert view.label == label
    assert not view.known


@pytest.mark.parametrize(
    ("raw", "label"),
    [
        (0, "草稿（尚未提交）"),
        (1, "第 1 輪"),
        (3, "第 3 輪"),
        (None, "-"),
        (True, "-"),
        (-1, "-"),
        ("2", "-"),
        (1.0, "-"),
    ],
)
def test_round_label(raw: Any, label: str) -> None:
    assert round_label(raw) == label


# ---- view model ----


def test_view_header_comes_from_source_only() -> None:
    view = build_confirmation_view(build_demo_invoice())
    assert view.header.invoice_id == DEMO_INVOICE_ID
    assert view.header.status.label == APPROVAL_STATUS_LABEL["returned_to_applicant"]
    assert view.header.submission_round == "第 2 輪"

    empty = build_confirmation_view({})
    assert empty.header.invoice_id == "-"
    assert empty.header.status.label == "-"
    assert empty.header.submission_round == "-"


def test_demo_snapshot_covers_each_original_state() -> None:
    view = build_confirmation_view(build_demo_invoice())

    buyer = _part(view, "F04")
    assert (buyer.status, buyer.original) == ("modified", "甲乙公司")
    assert _part(view, "F05").status == "unchanged"
    assert _part(view, "F05").original is None
    assert _part(view, "F13").status == "original_null"
    assert _part(view, "F11", "課稅別").status == "field_missing"
    assert view.has_ai_snapshot


def test_no_snapshot_is_not_shown_as_unchanged() -> None:
    invoice = build_demo_invoice()
    del invoice["original_values"]

    view = build_confirmation_view(invoice)

    assert not view.has_ai_snapshot
    assert _part(view, "F04").status == "no_snapshot"
    assert {r.status for r in _items(view).row_originals} == {"no_snapshot"}


def test_item_rows_compare_by_position_but_count_mismatch_is_reference_only() -> None:
    items = _items(build_confirmation_view(build_demo_invoice()))

    assert items.row_count_mismatch
    assert [r.status for r in items.row_originals] == ["unchanged", "modified_reference", "added"]
    assert "單價：200 → 250" in items.row_originals[1].note
    assert "金額：200 → 250" in items.row_originals[1].note
    assert items.removed_original_rows == 0


def test_item_rows_when_ai_has_more_rows_reports_removed_count() -> None:
    invoice = build_demo_invoice()
    invoice["items"] = invoice["items"][:1]

    items = _items(build_confirmation_view(invoice))

    assert [r.status for r in items.row_originals] == ["unchanged"]
    assert items.removed_original_rows == 1


@pytest.mark.parametrize(
    ("snapshot_items", "status"),
    [(None, "original_null"), ("bad", "not_comparable")],
)
def test_item_snapshot_null_or_invalid(snapshot_items: Any, status: str) -> None:
    invoice = build_demo_invoice()
    invoice["original_values"]["items"] = snapshot_items

    items = _items(build_confirmation_view(invoice))

    assert {r.status for r in items.row_originals} == {status}


def test_item_snapshot_key_absent_is_field_missing_not_unchanged() -> None:
    invoice = build_demo_invoice()
    del invoice["original_values"]["items"]

    items = _items(build_confirmation_view(invoice))

    assert {r.status for r in items.row_originals} == {"field_missing"}


def test_partial_item_row_is_marked_partial() -> None:
    invoice = build_demo_invoice()
    invoice["original_values"]["items"] = [{"item_name": "文具", "quantity": None}] * 3

    items = _items(build_confirmation_view(invoice))

    assert items.row_originals[0].status == "partial"


def test_demo_builder_returns_independent_copies() -> None:
    first = build_demo_invoice()
    first["items"].append({})
    assert len(build_demo_invoice()["items"]) == 3


# ---- 詳情路由：UUID／舊整數 ID ----


@pytest.fixture
def fetch_spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def fake_fetch(token: str, invoice_id: str) -> dict[str, Any]:
        calls.append(invoice_id)
        return build_api_detail(
            invoice_id=invoice_id, status="returned_to_applicant", submission_round=2
        )

    monkeypatch.setattr(invoices_client, "fetch_invoice", fake_fetch)
    return calls


def test_detail_accepts_uuid_and_shows_status_and_round(
    logged_in_client: TestClient, fetch_spy: list[str]
) -> None:
    response = logged_in_client.get(f"/invoices/{UUID_TEXT.upper()}")

    assert response.status_code == 200
    assert fetch_spy == [UUID_TEXT]
    html = response.text
    assert 'data-header="invoice-id">' + UUID_TEXT in html
    assert "退回申請單位補正" in html
    assert "第 2 輪" in html
    assert 'data-status-known="true"' in html
    assert "data-demo-banner" not in html


def test_detail_no_longer_accepts_legacy_positive_integer(
    logged_in_client: TestClient, fetch_spy: list[str]
) -> None:
    # 反轉舊斷言（舊：回 200 且轉給 API "7"）：後端只收 UUID，舊骨架整數 ID 由前台直接 404、不呼叫 API；
    # `/{invoice_id}/flow` 是另一組路由，不受影響（見 test_demo_route_does_not_shadow_other_invoice_routes）
    response = logged_in_client.get("/invoices/7")

    assert response.status_code == 404
    assert fetch_spy == []


@pytest.mark.parametrize(
    "bad", ["abc", "0", "-1", "1.5", "123e4567-e89b-42d3-a456", "../etc", "%E4%B8%80"]
)
def test_detail_rejects_other_ids_without_calling_api(
    logged_in_client: TestClient, fetch_spy: list[str], bad: str
) -> None:
    response = logged_in_client.get(f"/invoices/{bad}")

    assert response.status_code == 404
    assert fetch_spy == []


def test_detail_unknown_status_does_not_break_page(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch(token: str, invoice_id: str) -> dict[str, Any]:
        return build_api_detail(status="<b>weird</b>")

    monkeypatch.setattr(invoices_client, "fetch_invoice", fake_fetch)

    response = logged_in_client.get(f"/invoices/{API_DETAIL_ID}")

    assert response.status_code == 200
    assert "未知狀態（&lt;b&gt;weird&lt;/b&gt;）" in response.text
    assert "<b>weird</b>" not in response.text
    assert 'data-status-known="false"' in response.text


def test_detail_without_ai_snapshot_shows_notice_not_unchanged(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch(token: str, invoice_id: str) -> dict[str, Any]:
        return build_api_detail(buyer_name="甲", items=[])

    monkeypatch.setattr(invoices_client, "fetch_invoice", fake_fetch)

    html = logged_in_client.get(f"/invoices/{API_DETAIL_ID}").text

    assert "沒有 AI 原始快照" in html
    assert "未修改" not in html.replace("不代表未修改", "")
    assert 'data-original-status="unchanged"' not in html


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (403, "FORBIDDEN", 403),
        (404, "NOT_FOUND", 404),
        (422, "VALIDATION_ERROR", 422),
        (500, "INVOICE_DATA_INVALID", 502),
        (500, "INTERNAL_ERROR", 502),
        (502, "INVALID_UPSTREAM_RESPONSE", 502),
        (503, "SERVICE_UNAVAILABLE", 502),
        (503, "NETWORK_ERROR", 502),
    ],
)
def test_formal_detail_failure_never_falls_back_to_demo_data(
    logged_in_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    code: str,
    expected: int,
) -> None:
    async def failing_fetch(token: str, invoice_id: str) -> dict[str, Any]:
        raise ApiError(status, code, "後端訊息")

    monkeypatch.setattr(invoices_client, "fetch_invoice", failing_fetch)

    # 用展示頁的假 UUID 當正式案件 ID，確認即使 ID 相同也不會取用展示資料
    response = logged_in_client.get(f"/invoices/{DEMO_INVOICE_ID}")

    assert response.status_code == expected
    assert "後端訊息" in response.text
    for marker in ("測試資料／非正式案件", "甲乙示範股份有限公司", "影印紙", "示範商行"):
        assert marker not in response.text
    assert 'id="submit-control"' not in response.text


def test_formal_detail_401_redirects_to_login_without_demo_data(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unauthorized(token: str, invoice_id: str) -> dict[str, Any]:
        raise ApiError(401, "UNAUTHORIZED", "請重新登入")

    monkeypatch.setattr(invoices_client, "fetch_invoice", unauthorized)

    response = logged_in_client.get(f"/invoices/{API_DETAIL_ID}")

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


# ---- 本機虛構展示頁 ----


@pytest.fixture
def forbid_api(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("展示頁不得呼叫正式 API")

    monkeypatch.setattr(invoices_client, "request_json", boom)
    monkeypatch.setattr(invoices_client, "fetch_invoice", boom)


def test_demo_page_is_labelled_and_shows_status_round_and_diff(
    logged_in_client: TestClient, forbid_api: None
) -> None:
    response = logged_in_client.get("/invoices/demo/detail")

    assert response.status_code == 200
    html = response.text
    assert "測試資料／非正式案件" in html
    assert DEMO_INVOICE_ID in html
    assert "退回申請單位補正" in html
    assert "第 2 輪" in html
    assert "AI 原值：甲乙公司" in html
    assert 'data-original-status="original_null"' in html
    assert 'data-original-status="field_missing"' in html
    assert 'data-original-status="added"' in html
    assert 'class="row-issues" data-line-no="2"' in html
    assert "未知欄位的提醒" in html


def test_demo_page_requires_login(client: TestClient) -> None:
    response = client.get("/invoices/demo/detail")

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


@pytest.mark.parametrize("env", ["production", "preview"])
def test_demo_page_rejected_outside_local(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", env)

    response = logged_in_client.get("/invoices/demo/detail")

    assert response.status_code == 404
    assert "測試資料／非正式案件" not in response.text


def test_demo_page_rejected_on_vercel_even_if_env_says_local(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "VERCEL", "1")

    assert logged_in_client.get("/invoices/demo/detail").status_code == 404


def test_demo_route_does_not_shadow_other_invoice_routes(logged_in_client: TestClient) -> None:
    assert logged_in_client.get("/invoices/mobile-upload").status_code == 200
    assert logged_in_client.get("/invoices/upload").status_code == 200
    assert logged_in_client.get("/invoices/1/flow").status_code == 200


@pytest.mark.parametrize("bad", ["9" * 19, "9" * 5000, "0" * 5000, "0" * 19])
def test_detail_rejects_overlong_numeric_ids_with_404_not_500(
    logged_in_client: TestClient, fetch_spy: list[str], bad: str
) -> None:
    response = logged_in_client.get(f"/invoices/{bad}")

    assert response.status_code == 404
    assert fetch_spy == []


def test_detail_rejects_largest_legacy_id_and_leading_zeros(
    logged_in_client: TestClient, fetch_spy: list[str]
) -> None:
    # 反轉舊斷言（舊：兩者回 200 且轉給 API "999…9"、"7"）：整數分支已移除，只剩 UUID
    assert logged_in_client.get("/invoices/" + "9" * 18).status_code == 404
    assert logged_in_client.get("/invoices/0007").status_code == 404
    assert fetch_spy == []


def test_equal_row_count_keeps_modified_but_notes_positional_limit() -> None:
    invoice = build_demo_invoice()
    invoice["items"] = invoice["items"][:2]

    items = _items(build_confirmation_view(invoice))

    assert not items.row_count_mismatch
    assert items.row_compare_limited
    assert [r.status for r in items.row_originals] == ["unchanged", "modified"]


def test_deleted_middle_row_is_not_reported_as_definite_modification() -> None:
    invoice = build_demo_invoice()
    original_rows = invoice["original_values"]["items"]
    original_rows.append(dict(original_rows[0]))  # AI 3 列，刪掉第 1 列後目前 2 列
    del invoice["items"][0]
    assert len(original_rows) != len(invoice["items"])

    items = _items(build_confirmation_view(invoice))

    assert items.row_count_mismatch
    assert "modified" not in {r.status for r in items.row_originals}


def test_detail_page_shows_count_mismatch_hint(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = logged_in_client.get("/invoices/demo/detail").text

    assert "明細筆數與 AI 原始值不同，逐列比對僅供參考" in html
    assert 'data-original-status="modified_reference"' in html
    assert (
        'data-original-status="modified"'
        not in html.split('data-field-group="items"')[1].split("</table>")[0]
    )


def test_detail_page_shows_positional_limit_when_counts_equal(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 移到 Demo 路由：「依位置比對 AI 原始快照」需要 original_values，Stage 1 的詳情沒有這種資料，
    # 正式路徑不可能出現；builder／樣板對 fixture 輸入的行為仍由展示頁保護
    import app.routers.invoices as router_module

    def two_rows() -> dict[str, Any]:
        invoice = build_demo_invoice()
        invoice["items"] = invoice["items"][:2]
        return invoice

    monkeypatch.setattr(router_module, "build_demo_invoice", two_rows)
    html = logged_in_client.get("/invoices/demo/detail").text

    assert "data-row-compare-limited" in html
    assert "無法確認是否調整過順序" in html
    assert "data-row-count-mismatch" not in html


# ---- 檢核摘要的未知等級與展示頁提交區 ----


def _present(issues: list[Any]) -> Any:
    from app.utils.validation_view import present_issues

    return present_issues(issues, {})


def test_all_unknown_severity_is_counted_and_not_blocking() -> None:
    result = _present([{"code": "a"}, {"severity": "info"}, {"severity": None}, "raw"])

    assert (result.error_count, result.warning_count, result.unknown_count) == (0, 0, 4)
    assert not result.has_blocking_error
    assert len(result.general_issues) == 4  # 未知等級不會消失


def test_mixed_severity_counts() -> None:
    result = _present(
        [{"severity": "error"}, {"severity": "warning"}, {"severity": "warning"}, {"code": "x"}]
    )

    assert (result.error_count, result.warning_count, result.unknown_count) == (1, 2, 1)
    assert result.has_blocking_error


def test_severity_case_and_whitespace_still_normalized() -> None:
    result = _present([{"severity": " ERROR "}, {"severity": "Warning"}])

    assert (result.error_count, result.warning_count, result.unknown_count) == (1, 1, 0)


def test_no_issues_has_zero_unknown() -> None:
    assert _present([]).unknown_count == 0
    assert _present(None).unknown_count == 0


def test_demo_page_shows_unknown_count_and_notice(logged_in_client: TestClient) -> None:
    html = logged_in_client.get("/invoices/demo/detail").text

    assert 'data-unknown-count="3"' in html
    assert "未知等級 3" in html
    assert "有 3 筆檢核訊息的嚴重度未知，請逐筆確認，不代表檢核通過。" in html


def test_unknown_notice_hidden_when_no_unknown(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 正式路徑：Stage 1 的 warnings 沒有 severity，所以「沒有任何警示」才會是 0 筆未知等級
    async def fake(token: str, invoice_id: str) -> dict[str, Any]:
        return build_api_detail(warnings=[])

    monkeypatch.setattr(invoices_client, "fetch_invoice", fake)
    html = logged_in_client.get(f"/invoices/{API_DETAIL_ID}").text

    assert 'data-unknown-count="0"' in html
    assert "data-unknown-notice" not in html
    assert "不代表檢核通過" not in html


def test_demo_page_has_no_submit_button_and_fixed_note(logged_in_client: TestClient) -> None:
    html = logged_in_client.get("/invoices/demo/detail").text

    assert 'id="submit-control"' not in html
    assert "展示頁不提供提交（離線展示，沒有任何送出行為）。" in html
    assert "提交功能尚未接線" not in html
    assert "仍有錯誤，修正後才能提交" not in html


def test_demo_note_is_not_affected_by_blocking_error(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.routers.invoices as router_module

    def with_error() -> dict[str, Any]:
        invoice = build_demo_invoice()
        invoice["validation"]["issues"].append(
            {"field": "amount", "severity": "error", "message": "e"}
        )
        return invoice

    monkeypatch.setattr(router_module, "build_demo_invoice", with_error)
    html = logged_in_client.get("/invoices/demo/detail").text

    assert 'id="submit-control"' not in html
    assert "展示頁不提供提交（離線展示，沒有任何送出行為）。" in html
    assert "仍有錯誤，修正後才能提交" not in html


def test_real_detail_page_is_read_only_without_a_submit_button(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 反轉舊斷言（舊：正式頁有 id="submit-control"）：正式詳情頁唯讀，沒有無作用的提交按鈕
    async def fake(token: str, invoice_id: str) -> dict[str, Any]:
        return build_api_detail(warnings=[{"field": "items", "code": "c", "message": "m"}])

    monkeypatch.setattr(invoices_client, "fetch_invoice", fake)
    html = logged_in_client.get(f"/invoices/{API_DETAIL_ID}").text

    assert 'id="submit-control"' not in html
    assert "<button" not in html.split("<h1>發票詳情")[1].split("</main>")[0]
    assert "提交功能尚未接線" not in html
    assert 'data-readonly-note="true"' in html
    assert "data-demo-submit-note" not in html  # 展示頁的說明只屬於展示頁


# ---- 視覺結構（只檢查樣板結構與 class，不驗證實際外觀）----

_TONES = {
    "approved": "ok",
    "draft": "neutral",
    "pending_department_approval": "info",
    "pending_accounting_review": "info",
    "pending_accounting_approval": "info",
    "returned_to_applicant": "attention",
    "returned_to_accounting": "attention",
    "rejected": "negative",
    "voided": "void",
}


def _detail_html(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, status: Any = "approved"
) -> str:
    async def fake(token: str, invoice_id: str) -> dict[str, Any]:
        return build_api_detail(status=status)

    monkeypatch.setattr(invoices_client, "fetch_invoice", fake)
    return client.get(f"/invoices/{API_DETAIL_ID}").text


def test_detail_loads_page_css_and_scope_container(logged_in_client: TestClient) -> None:
    html = logged_in_client.get("/invoices/demo/detail").text

    assert "css/pages/invoice-detail.css" in html
    assert '<div class="invoice-detail">' in html


def test_items_table_has_own_scroll_container(logged_in_client: TestClient) -> None:
    html = logged_in_client.get("/invoices/demo/detail").text
    items = html.split('data-field-group="items"')[1]

    assert items.index("invoice-detail__table-wrap") < items.index('<table class="table">')
    assert items.index("</table>") < items.index("</div>")
    assert 'tabindex="0"' in items.split('<table class="table">')[0]


@pytest.mark.parametrize(("code", "tone"), list(_TONES.items()))
def test_status_badge_tone_for_each_known_status(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, code: str, tone: str
) -> None:
    html = _detail_html(logged_in_client, monkeypatch, code)

    assert f'data-status-tone="{tone}"' in html
    assert f"idt-badge--{tone}" in html
    assert APPROVAL_STATUS_LABEL[code] in html  # 中文文字不因上色而消失


def test_only_approved_gets_the_success_tone() -> None:
    assert [c for c, t in _TONES.items() if t == "ok"] == ["approved"]
    assert _TONES["rejected"] != "ok"
    assert _TONES["voided"] != "ok"
    assert not any(t == "ok" for c, t in _TONES.items() if c.startswith("returned"))


# status=None 不再出現在正式路徑：Stage 1 的 status 是字串，None 會被 API Client 以 502 拒絕
# （見 test_invoice_detail_client.py）；None→「-」的顯示規則由 status_view 的純函式測試保護
@pytest.mark.parametrize("status", ["mystery_status", ""])
def test_unknown_or_missing_status_is_neutral_dashed(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, status: Any
) -> None:
    html = _detail_html(logged_in_client, monkeypatch, status)

    assert 'data-status-tone="unknown"' in html
    assert "idt-badge--ok" not in html


def test_page_css_is_scoped_and_without_important() -> None:
    import re
    from pathlib import Path

    css = Path("app/static/css/pages/invoice-detail.css").read_text(encoding="utf-8")
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    assert "!important" not in body
    for block in re.findall(r"([^{}]+)\{", body):
        if block.strip().startswith("@"):
            continue
        for selector in block.split(","):
            assert selector.strip().startswith(".invoice-detail"), selector.strip()
    assert ":root" not in body


# ---- 明細列警示：位於表格捲動容器之外（解析 HTML 結構）----


def _parse_items_html(html: str) -> Any:
    from html.parser import HTMLParser

    class Collector(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.stack: list[tuple[str, dict[str, str | None]]] = []
            self.records: list[dict[str, Any]] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            attr = dict(attrs)
            self.records.append(
                {
                    "tag": tag,
                    "attrs": attr,
                    "ancestors": [(t, dict(a)) for t, a in self.stack],
                }
            )
            if tag not in {"br", "meta", "link", "input", "img"}:
                self.stack.append((tag, attr))

        def handle_endtag(self, tag: str) -> None:
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    break

    parser = Collector()
    parser.feed(html)
    return parser.records


def _in_class(record: dict[str, Any], cls: str) -> bool:
    return any(cls in (a.get("class") or "").split() for _, a in record["ancestors"])


def test_row_issues_are_cards_outside_table_and_scroll_container(
    logged_in_client: TestClient,
) -> None:
    html = logged_in_client.get("/invoices/demo/detail").text
    records = _parse_items_html(html)
    cards = [r for r in records if (r["attrs"].get("class") or "") == "row-issues"]

    assert [c["tag"] for c in cards] == ["section"]
    assert not [
        r for r in records if r["tag"] == "tr" and "row-issues" in (r["attrs"].get("class") or "")
    ]
    for card in cards:
        assert not any(t == "table" for t, _ in card["ancestors"])
        assert not _in_class(card, "invoice-detail__table-wrap")
        assert _in_class(card, "invoice-detail__row-issues")
    assert html.index("</table>") < html.index('class="invoice-detail__row-issues"')


def test_row_issue_card_line_no_matches_row_and_shows_once(logged_in_client: TestClient) -> None:
    html = logged_in_client.get("/invoices/demo/detail").text
    records = _parse_items_html(html)
    cards = [r for r in records if (r["attrs"].get("class") or "") == "row-issues"]
    rows = [r for r in records if r["tag"] == "tr" and r["attrs"].get("data-line-no")]

    assert [c["attrs"]["data-line-no"] for c in cards] == ["2"]
    assert "2" in {r["attrs"]["data-line-no"] for r in rows}
    assert "第 2 筆明細（影印紙）" in html  # 標題帶品名（取自既有明細列）
    assert html.count("（展示）第 2 筆明細金額與數量×單價不符") == 1
    assert html.count("demo_line_amount") == 1
    assert html.count("預期：250") == 1


def test_overall_items_issue_is_not_moved_into_a_row_card(logged_in_client: TestClient) -> None:
    html = logged_in_client.get("/invoices/demo/detail").text
    records = _parse_items_html(html)
    overall = [r for r in records if r["attrs"].get("data-field-id") == "items"]

    assert len(overall) == 1
    assert not _in_class(overall[0], "row-issues")
    card_html = html.split('class="invoice-detail__row-issues"')[1].split("明細整體")[0]
    assert "items_total_mismatch" not in card_html
    assert html.count("items_total_mismatch") == 1


def test_no_row_issue_container_without_row_issues(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(token: str, invoice_id: str) -> dict[str, Any]:
        return build_api_detail(
            warnings=[{"field": "items", "code": "overall_only", "message": "整體提醒"}]
        )

    monkeypatch.setattr(invoices_client, "fetch_invoice", fake)
    html = logged_in_client.get(f"/invoices/{API_DETAIL_ID}").text

    assert 'class="invoice-detail__row-issues"' not in html
    assert 'class="row-issues"' not in html
    assert html.count("overall_only") == 1
