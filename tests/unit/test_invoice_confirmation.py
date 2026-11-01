"""測試目標：發票確認畫面的呈現行為（mock 資料；不連任何服務，也不代表與真實 API 整合通過）

資料來源分三種，不混用：
    - builder 層（直接呼叫 build_confirmation_view）：使用 fixture 格式的 _invoice()。
    - 正式詳情路由（/invoices/{uuid}）：使用符合 Stage 1 契約的 Mock 回應（stage1_detail.build_api_detail）。
    - 需要 severity／line_no／expected 等 Stage 1 契約沒有的輸入時，走 Demo 路由並替換展示資料。
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from stage1_detail import API_DETAIL_ID, build_api_detail

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
    stub_detail(build_api_detail(invoice_track="AB", invoice_number="12345678"))

    response = logged_in_client.get(f"/invoices/{API_DETAIL_ID}")

    assert response.status_code == 200
    assert len(UI_FIELDS) == 14
    for field in UI_FIELDS:
        assert field.label in response.text
    assert "AB12345678" in response.text
    assert 'class="issue ' not in response.text
    assert "待人工確認" not in response.text
    # 反轉舊斷言（舊：提交按鈕未 disabled）：正式頁唯讀，沒有提交按鈕
    assert 'id="submit-control"' not in response.text


def test_presentation_one_error_marks_field_on_the_page(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 移到 Demo 路由：severity="error" 是 Stage 1 的 warnings 沒有的輸入，正式路徑不可能出現；
    # 「error 阻擋提交」的 view model 規則由 builder 層測試保護（test_presentation_multiple_fields_with_issues）。
    # 舊的「按鈕 disabled」斷言隨正式頁移除按鈕而移除。
    import app.routers.invoices as router_module

    monkeypatch.setattr(
        router_module,
        "build_demo_invoice",
        lambda: _invoice([_issue("sales_amount", "AMOUNT_SUM_MISMATCH", "error", "金額不一致")]),
    )

    html = logged_in_client.get("/invoices/demo/detail").text

    block = html.split('data-field-id="F10"')[1].split("</section>")[0]
    assert "金額不一致" in block
    assert "AMOUNT_SUM_MISMATCH" in block
    assert 'data-severity="error"' in block
    assert 'id="submit-control"' not in html


def test_presentation_warning_shows_pending_manual_confirmation_not_error() -> None:
    view = build_confirmation_view(_invoice([_issue("tax_amount", "DEDUCTION_RISK", "warning")]))

    issue = view.validation.issues_by_field["F11"][0]
    assert issue.severity == "warning"
    assert issue.notice == "待人工確認"
    assert not issue.is_blocking
    assert not view.validation.has_blocking_error
    assert view.validation.has_warning
    assert view.submit_control_enabled


def test_presentation_warning_page_has_notice_and_no_error(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 移到 Demo 路由：severity="warning" 是 Stage 1 契約沒有的輸入（理由同上）；舊的「按鈕未 disabled」斷言已移除
    import app.routers.invoices as router_module

    monkeypatch.setattr(
        router_module,
        "build_demo_invoice",
        lambda: _invoice([_issue("tax_amount", "DEDUCTION_RISK", "warning", "扣抵風險")]),
    )

    html = logged_in_client.get("/invoices/demo/detail").text

    assert "扣抵風險" in html
    assert "待人工確認" in html
    assert 'data-severity="error"' not in html
    assert 'id="submit-control"' not in html


def test_presentation_page_has_no_submit_element_or_form_post(
    logged_in_client: TestClient, stub_detail: Any
) -> None:
    stub_detail(build_api_detail())

    html = logged_in_client.get(f"/invoices/{API_DETAIL_ID}").text

    # 頁首的登出表單不算；確認畫面內容區不得有任何 form、POST 或按鈕。
    # 反轉舊斷言（舊：存在 type="button" 的提交按鈕）；「頁面不會送出任何請求」的原意保留
    content = html.split("<h1>發票詳情")[1].split("</main>")[0]
    assert "<form" not in content
    assert 'method="post"' not in content
    assert "<button" not in content
    assert 'id="submit-control"' not in html
    assert 'data-readonly-note="true"' in content


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
    stub_detail(
        build_api_detail(
            warnings=[
                {"field": "unknown_future_key", "code": "NEW_RULE", "message": "未知欄位的錯誤"}
            ]
        )
    )

    response = logged_in_client.get(f"/invoices/{API_DETAIL_ID}")

    # 正式路徑的 warnings 沒有 severity，所以「阻擋」只在 builder 層用 severity="error" 的 fixture 輸入驗證
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
    invoice = build_api_detail(
        items=[
            {
                "line_no": 1,
                "item_name": "文具",
                "quantity": "2",
                "unit_price": "50",
                "line_amount": "100",
            },
            {
                "line_no": 2,
                "item_name": "影印紙",
                "quantity": "1",
                "unit_price": "200",
                "line_amount": "200",
            },
        ],
        warnings=[{"field": "items", "code": "LINE_AMOUNT", "message": "明細金額錯"}],
    )
    stub_detail(invoice)

    from app.utils.invoice_detail_adapter import adapt_invoice_detail

    view = build_confirmation_view(adapt_invoice_detail(invoice))
    html = logged_in_client.get(f"/invoices/{API_DETAIL_ID}").text

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


def test_presentation_ai_original_is_shown_only_for_fields_with_a_modification_record(
    logged_in_client: TestClient, stub_detail: Any
) -> None:
    # 反轉舊輸入（舊：fixture 的 original_values 快照）：Stage 1 詳情沒有 AI 快照，只有 modified_fields，
    # 所以只有「有修改紀錄」的欄位顯示 AI 原值；沒有紀錄的欄位什麼都不顯示（不代表未修改）
    stub_detail(
        build_api_detail(
            buyer_name="測試股份有限公司",
            seller_name="測試商行",
            modified_fields=[
                {
                    "field_scope": "header",
                    "line_no": None,
                    "field_name": "buyer_name",
                    "ai_original_value": "測試股份有限公司（OCR）",
                    "submitted_value": "測試股份有限公司",
                }
            ],
        )
    )

    html = logged_in_client.get(f"/invoices/{API_DETAIL_ID}").text

    assert "AI 原值：測試股份有限公司（OCR）" in html
    assert "AI 原值：測試商行" not in html
    assert 'data-original-status="unchanged"' not in html


def test_validation_presentation_does_not_produce_workflow_status() -> None:
    view = build_confirmation_view(_invoice([_issue("sales_amount", "A", "error")]))

    assert not hasattr(view, "status")
    assert not hasattr(view.validation, "status")
