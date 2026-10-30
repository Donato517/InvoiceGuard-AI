"""測試目標：發票確認畫面骨架的呈現行為（mock 資料；不涉及 API Contract、提交或持久化）"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.clients import invoices as invoices_client
from app.utils.invoice_confirmation import build_confirmation_view
from app.utils.invoice_fields import UI_FIELDS
from app.utils.validation_view import normalize_severity, present_issues


def _invoice(issues: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    """mock 發票資料；key 為 frontend-only fixture key，非正式 Contract。"""
    data: dict[str, Any] = {
        "form_type": "三聯式",
        "track_number": "AB12345678",
        "invoice_date": "2026-10-20",
        "buyer_name": "測試股份有限公司",
        "buyer_tax_id": "12345678",
        "items": [
            {"item_name": "文具", "quantity": "2", "unit_price": "50", "amount": "100"},
            {"item_name": "影印紙", "quantity": "1", "unit_price": "200", "amount": "200"},
        ],
        "sales_amount": "300",
        "tax_type": "應稅",
        "tax_amount": "15",
        "total_amount": "315",
        "total_amount_zh": "參佰壹拾伍元整",
        "remark": "",
        "seller_name": "測試商行",
        "validation": {"rule_version": "v1", "checked_at": "2026-10-27T10:00:00Z"},
    }
    if issues is not None:
        data["validation"]["issues"] = issues
    data.update(extra)
    return data


def _issue(field: str, code: str, severity: str, message: str = "訊息") -> dict[str, str]:
    return {"field": field, "code": code, "severity": severity, "message": message}


@pytest.fixture
def stub_detail(monkeypatch: pytest.MonkeyPatch):
    def install(invoice: dict[str, Any]) -> None:
        async def fake_fetch_invoice(token: str, invoice_id: int) -> dict[str, Any]:
            return invoice

        monkeypatch.setattr(invoices_client, "fetch_invoice", fake_fetch_invoice)

    return install


def test_presentation_no_issues_shows_all_14_fields(
    logged_in_client: TestClient, stub_detail: Any
) -> None:
    stub_detail(_invoice([]))

    response = logged_in_client.get("/invoices/1")

    assert response.status_code == 200
    assert len(UI_FIELDS) == 14
    for field in UI_FIELDS:
        assert field.label in response.text
    assert "AB12345678" in response.text
    assert 'class="issue ' not in response.text
    assert "待人工確認" not in response.text
    assert "disabled" not in response.text.split('id="submit-control"')[1].split(">")[0]


def test_presentation_one_error_marks_field_and_disables_submit(
    logged_in_client: TestClient, stub_detail: Any
) -> None:
    stub_detail(_invoice([_issue("sales_amount", "AMOUNT_SUM_MISMATCH", "error", "金額不一致")]))

    response = logged_in_client.get("/invoices/1")

    html = response.text
    block = html.split('data-field-id="F10"')[1].split("</section>")[0]
    assert "金額不一致" in block
    assert "AMOUNT_SUM_MISMATCH" in block
    assert 'data-severity="error"' in block
    assert "disabled" in html.split('id="submit-control"')[1].split(">")[0]


def test_presentation_warning_shows_pending_manual_confirmation_not_error() -> None:
    view = build_confirmation_view(_invoice([_issue("tax_amount", "DEDUCTION_RISK", "warning")]))

    issue = view.validation.issues_by_field["F11"][0]
    assert issue.severity == "warning"
    assert issue.notice == "待人工確認"
    assert not issue.is_blocking
    assert not view.validation.has_blocking_error
    assert view.validation.has_warning
    assert view.submit_control_enabled


def test_presentation_warning_page_has_notice_and_enabled_submit(
    logged_in_client: TestClient, stub_detail: Any
) -> None:
    stub_detail(_invoice([_issue("tax_amount", "DEDUCTION_RISK", "warning", "扣抵風險")]))

    html = logged_in_client.get("/invoices/1").text

    assert "扣抵風險" in html
    assert "待人工確認" in html
    assert 'data-severity="error"' not in html
    assert "disabled" not in html.split('id="submit-control"')[1].split(">")[0]


def test_presentation_submit_control_is_not_a_form_post(
    logged_in_client: TestClient, stub_detail: Any
) -> None:
    stub_detail(_invoice([]))

    html = logged_in_client.get("/invoices/1").text

    # 頁首的登出表單不算；確認畫面內容區不得有任何 form 或 POST
    content = html.split("<h1>發票詳情")[1].split("</main>")[0]
    assert "<form" not in content
    assert 'method="post"' not in content
    assert 'type="button"' in html.split('id="submit-control"')[0].rsplit("<button", 1)[1]


def test_presentation_multiple_fields_with_issues() -> None:
    view = build_confirmation_view(
        _invoice(
            [
                _issue("sales_amount", "AMOUNT_SUM_MISMATCH", "error"),
                _issue("buyer_tax_id", "TAX_ID_FORMAT", "warning"),
            ]
        )
    )

    assert set(view.validation.issues_by_field) == {"F10", "F05"}
    assert view.validation.error_count == 1
    assert view.validation.warning_count == 1
    assert view.validation.has_blocking_error


def test_presentation_multiple_issues_on_same_field_are_all_kept() -> None:
    view = build_confirmation_view(
        _invoice(
            [
                _issue("sales_amount", "A", "error", "第一筆"),
                _issue("sales_amount", "B", "warning", "第二筆"),
                _issue("sales_amount", "C", "error", "第三筆"),
            ]
        )
    )

    issues = view.validation.issues_by_field["F10"]
    assert [i.code for i in issues] == ["A", "B", "C"]


def test_presentation_unmapped_issue_is_kept_as_general(
    logged_in_client: TestClient, stub_detail: Any
) -> None:
    stub_detail(_invoice([_issue("unknown_future_key", "NEW_RULE", "error", "未知欄位的錯誤")]))

    response = logged_in_client.get("/invoices/1")

    view = build_confirmation_view(_invoice([_issue("unknown_future_key", "NEW_RULE", "error")]))
    assert len(view.validation.general_issues) == 1
    assert view.validation.has_blocking_error
    assert "未知欄位的錯誤" in response.text
    assert "其他檢核訊息" in response.text


def test_presentation_missing_field_and_malformed_issue_are_not_dropped() -> None:
    result = present_issues([{"code": "X", "severity": "error"}, "壞掉的內容"], {})

    assert len(result.general_issues) == 2
    assert result.error_count == 1


def test_presentation_multiple_invoice_items_render_as_rows(
    logged_in_client: TestClient, stub_detail: Any
) -> None:
    invoice = _invoice([_issue("amount", "LINE_AMOUNT", "error", "明細金額錯")])
    stub_detail(invoice)

    view = build_confirmation_view(invoice)
    html = logged_in_client.get("/invoices/1").text

    items = next(s for s in view.sections if s.kind == "items")
    assert [c.field.label for c in items.columns] == ["品名／用途", "數量", "單價", "金額"]
    assert items.rows == (("文具", "2", "50", "100"), ("影印紙", "1", "200", "200"))
    assert "文具" in html and "影印紙" in html
    assert "明細金額錯" in html
    # 明細欄位合併為單一區塊，14 類中其餘 10 類 + 1 個明細區塊
    assert len(view.sections) == 11


def test_presentation_items_missing_or_invalid_does_not_crash() -> None:
    view = build_confirmation_view(_invoice([], items="not-a-list"))

    items = next(s for s in view.sections if s.kind == "items")
    assert items.rows == ()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("error", "error"),
        (" ERROR ", "error"),
        ("Warning", "warning"),
        ("info", "unknown"),
        (None, "unknown"),
    ],
)
def test_normalize_severity(raw: Any, expected: str) -> None:
    assert normalize_severity(raw) == expected


def test_unknown_severity_is_neither_error_nor_warning() -> None:
    result = present_issues([{"field": "x", "severity": "info", "message": "m"}], {})

    assert result.error_count == 0
    assert result.warning_count == 0
    assert not result.has_blocking_error
    assert len(result.general_issues) == 1
    assert result.general_issues[0].severity_label == "未知等級"


def test_presentation_original_and_current_values_shown_without_persistence_claim(
    logged_in_client: TestClient, stub_detail: Any
) -> None:
    stub_detail(
        _invoice(
            [], original_values={"buyer_name": "測試股份有限公司（OCR）", "seller_name": "測試商行"}
        )
    )

    html = logged_in_client.get("/invoices/1").text

    assert "AI 原值：測試股份有限公司（OCR）" in html
    # 與目前值相同者不重複顯示原值
    assert "AI 原值：測試商行" not in html


def test_validation_presentation_does_not_produce_workflow_status() -> None:
    view = build_confirmation_view(_invoice([_issue("sales_amount", "A", "error")]))

    assert not hasattr(view, "status")
    assert not hasattr(view.validation, "status")
