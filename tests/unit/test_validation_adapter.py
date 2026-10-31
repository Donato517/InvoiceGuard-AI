"""測試目標：API warnings 轉接為畫面 issues、明細列定位與缺值的安全呈現（合成資料，不連任何服務）"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from stage1_detail import API_DETAIL_ID, build_api_detail

from app.clients import invoices as invoices_client
from app.utils.invoice_confirmation import build_confirmation_view
from app.utils.validation_adapter import normalize_validation
from app.utils.validation_view import present_issues

# API FieldWarning 的形狀：只有 field／code／message
API_WARNINGS = {
    "warnings": [
        {"field": "items", "code": "items_total_mismatch", "message": "明細金額合計與銷售額不符"},
        {"field": "total_amount", "code": "total_amount_mismatch", "message": "合計不符"},
        {
            "field": "invoice_number",
            "code": "invoice_number_invalid",
            "message": "字軌號碼無法辨識",
        },
        {"field": "future_field", "code": "new_code", "message": "未知欄位的提醒"},
    ]
}


def _invoice(validation: Any = None, **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "form_type": "三聯式",
        "track_number": "AB12345678",
        "invoice_date": "2026-10-20",
        "buyer_name": "測試股份有限公司",
        "buyer_tax_id": "12345678",
        "items": [
            {"item_name": "文具", "quantity": "2", "unit_price": "50", "amount": "100"},
            {"item_name": "影印紙", "quantity": "1", "unit_price": "200", "amount": "200"},
            {"item_name": "墨水", "quantity": "1", "unit_price": "30", "amount": "30"},
        ],
        "sales_amount": "300",
        "tax_type": "應稅",
        "tax_amount": "15",
        "total_amount": "315",
        "total_amount_zh": "參佰壹拾伍元整",
        "remark": "",
        "seller_name": "測試商行",
    }
    if validation is not None:
        data["validation"] = validation
    data.update(extra)
    return data


def _items(view: Any) -> Any:
    return next(s for s in view.sections if s.kind == "items")


# ---- 轉接層 ----


def test_adapter_converts_warnings_without_inventing_fields() -> None:
    result = normalize_validation(API_WARNINGS)

    assert [i["code"] for i in result["issues"]] == [
        "items_total_mismatch",
        "total_amount_mismatch",
        "invoice_number_invalid",
        "new_code",
    ]
    for issue in result["issues"]:
        assert set(issue) == {"field", "code", "message"}
    assert "rule_version" not in result and "checked_at" not in result


def test_adapter_keeps_issues_format_and_only_whitelisted_keys() -> None:
    raw = {
        "rule_version": "v1",
        "checked_at": "2026-10-24T05:00:00Z",
        "issues": [{"field": "x", "code": "C", "message": "m", "severity": "error", "extra": 1}],
    }

    result = normalize_validation(raw)

    assert result["issues"] == [{"field": "x", "code": "C", "message": "m", "severity": "error"}]
    assert result["rule_version"] == "v1"
    assert result["checked_at"] == "2026-10-24T05:00:00Z"


@pytest.mark.parametrize("raw", [None, "壞掉", 123, [], {}, {"warnings": "not-a-list"}])
def test_adapter_non_mapping_or_empty_gives_empty_issues(raw: Any) -> None:
    assert normalize_validation(raw) == {"issues": []}


def test_adapter_does_not_mutate_input() -> None:
    raw = {"warnings": [{"field": "a", "code": "b", "message": "c"}]}
    snapshot = {"warnings": [dict(raw["warnings"][0])]}

    normalize_validation(raw)

    assert raw == snapshot


def test_api_warnings_have_no_severity_and_are_not_blocking() -> None:
    view = build_confirmation_view(_invoice(API_WARNINGS))

    assert view.validation.error_count == 0
    assert view.validation.warning_count == 0
    assert not view.validation.has_blocking_error
    assert view.submit_control_enabled
    every = [i for group in view.validation.issues_by_field.values() for i in group]
    every += list(view.validation.general_issues)
    assert len(every) == 4
    assert {i.severity for i in every} == {"unknown"}


def test_build_view_reads_validation_results_key_from_api() -> None:
    invoice = _invoice(None)
    invoice["validation_results"] = API_WARNINGS

    view = build_confirmation_view(invoice)

    assert [i.code for i in view.validation.issues_by_field["F12"]] == ["total_amount_mismatch"]
    assert [i.code for i in view.validation.issues_by_field["F02"]] == ["invoice_number_invalid"]


def test_unknown_field_warning_is_kept_as_general() -> None:
    view = build_confirmation_view(_invoice(API_WARNINGS))

    assert [i.code for i in view.validation.general_issues] == ["new_code"]


# ---- 欄位與明細定位 ----


def test_items_warning_without_line_no_shows_in_overall_area_only() -> None:
    items = _items(build_confirmation_view(_invoice(API_WARNINGS)))

    assert [i.code for i in items.overall_issues] == ["items_total_mismatch"]
    assert all(not row for row in items.row_issues)
    assert all(not column.issues for column in items.columns)


def test_issue_with_line_no_is_attached_to_that_row() -> None:
    issues = [
        {"field": "amount", "code": "A", "message": "第二筆金額錯", "line_no": 2},
        {"field": "item_name", "code": "B", "message": "第三筆品名", "line_no": 3},
        {"field": "amount", "code": "C", "message": "整體金額欄", "severity": "error"},
    ]

    items = _items(build_confirmation_view(_invoice({"issues": issues})))

    assert [len(r) for r in items.row_issues] == [0, 1, 1]
    assert items.row_issues[1][0].code == "A"
    assert items.row_issues[2][0].code == "B"
    amount_column = next(c for c in items.columns if c.field.field_id == "F09")
    assert [i.code for i in amount_column.issues] == ["C"]


def test_line_no_beyond_rows_stays_visible_not_guessed() -> None:
    issues = [{"field": "amount", "code": "A", "message": "第九筆", "line_no": 9}]

    items = _items(build_confirmation_view(_invoice({"issues": issues})))

    assert all(not row for row in items.row_issues)
    amount_column = next(c for c in items.columns if c.field.field_id == "F09")
    assert [i.code for i in amount_column.issues] == ["A"]


@pytest.mark.parametrize("bad", [0, -1, True, "2", 1.5, None])
def test_invalid_line_no_is_ignored(bad: Any) -> None:
    issues = [{"field": "amount", "code": "A", "message": "m", "line_no": bad}]

    items = _items(build_confirmation_view(_invoice({"issues": issues})))

    assert all(not row for row in items.row_issues)
    amount_column = next(c for c in items.columns if c.field.field_id == "F09")
    assert [i.code for i in amount_column.issues] == ["A"]


def test_multiple_issues_keep_their_own_fields() -> None:
    view = build_confirmation_view(
        _invoice(
            {
                "issues": [
                    {"field": "sales_amount", "code": "A", "message": "a"},
                    {"field": "buyer_tax_id", "code": "B", "message": "b"},
                    {"field": "sales_amount", "code": "C", "message": "c"},
                ]
            }
        )
    )

    assert [i.code for i in view.validation.issues_by_field["F10"]] == ["A", "C"]
    assert [i.code for i in view.validation.issues_by_field["F05"]] == ["B"]


# ---- 缺值的安全呈現 ----


def test_expected_actual_difference_only_when_source_provides_them() -> None:
    result = present_issues(
        [
            {"field": "f", "code": "A", "message": "m", "expected": "6000", "actual": "8000"},
            {"field": "f", "code": "B", "message": "m"},
            {"field": "f", "code": "C", "message": "m", "expected": "", "actual": None},
        ],
        {},
    )

    first, second, third = result.general_issues
    assert first.has_comparison and (first.expected, first.actual) == ("6000", "8000")
    assert first.difference is None
    assert not second.has_comparison
    assert not third.has_comparison


def test_page_shows_comparison_and_row_location(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    issues = [
        {
            "field": "amount",
            "code": "A",
            "message": "第二筆金額不符",
            "line_no": 2,
            "expected": "200",
            "actual": "250",
            "difference": "50",
        },
        {"field": "items", "code": "items_total_mismatch", "message": "合計不符"},
    ]

    # 移到 Demo 路由：issue 的 line_no／expected／actual／difference 是 Stage 1 的 FieldWarning 沒有的欄位
    # （demo_invoice.py 說明它們只是「來源若提供時的呈現」），正式路徑不可能出現
    import app.routers.invoices as router_module

    monkeypatch.setattr(router_module, "build_demo_invoice", lambda: _invoice({"issues": issues}))

    html = logged_in_client.get("/invoices/demo/detail").text

    assert "第二筆金額不符" in html
    assert "預期：200" in " ".join(html.split())
    assert "實際：250" in " ".join(html.split())
    assert "差異：50" in " ".join(html.split())
    assert 'class="row-issues" data-line-no="2"' in html
    assert "明細整體" in html and "合計不符" in html


def test_page_without_comparison_shows_no_comparison_text(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 正式路徑：API_WARNINGS 就是 Stage 1 warnings 的格式（只有 field／code／message）
    async def fake_fetch(token: str, invoice_id: Any) -> dict[str, Any]:
        return build_api_detail(warnings=API_WARNINGS["warnings"])

    monkeypatch.setattr(invoices_client, "fetch_invoice", fake_fetch)

    html = logged_in_client.get(f"/invoices/{API_DETAIL_ID}").text

    assert "預期：" not in html
    assert "未知等級" in html
    assert "未知欄位的提醒" in html
