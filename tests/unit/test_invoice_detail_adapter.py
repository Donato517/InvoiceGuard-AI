"""測試目標：app.utils.invoice_detail_adapter（Mock：純函式，以符合 Stage 1 契約的合成資料驗證，不連任何服務）。

重點：欄位對應、不修改輸入、不虛構 AI 原始快照、每一筆修改紀錄都有去處（不靜默丟棄）、
巢狀值與超長值明確標示。這是離線契約檢查，不代表與真實 API 整合通過。
"""

import copy
import inspect
from typing import Any

import pytest
from stage1_detail import build_api_detail

from app.utils import invoice_detail_adapter
from app.utils.invoice_detail_adapter import (
    EMPTY_TEXT,
    MAX_DISPLAY_CHARS,
    STRUCTURED_TEXT,
    TRUNCATED_SUFFIX,
    UNDISPLAYABLE_TEXT,
    InvoiceDetailFormatError,
    adapt_invoice_detail,
    display_value,
)


def _record(
    scope: Any = "header",
    name: Any = "buyer_name",
    line_no: Any = None,
    original: Any = "舊",
    submitted: Any = "新",
) -> dict[str, Any]:
    return {
        "field_scope": scope,
        "line_no": line_no,
        "field_name": name,
        "ai_original_value": original,
        "submitted_value": submitted,
    }


def _mods(*records: Any) -> dict[str, Any]:
    return adapt_invoice_detail(build_api_detail(modified_fields=list(records)))["modifications"]


# ---- 欄位對應 ----


def test_maps_header_fields_and_items() -> None:
    out = adapt_invoice_detail(build_api_detail())

    assert out["invoice_id"] == "123e4567-e89b-42d3-a456-426614174000"
    assert out["status"] == "pending_department_approval"
    assert out["submission_round"] == 1
    assert out["track_number"] == "CD75670992"
    assert out["invoice_date"] == "2026-10-15"
    assert out["buyer_name"] == "範例科技股份有限公司"
    assert out["seller_name"] == "範例文具行"
    assert out["seller_tax_id"] == "27601907"
    assert out["tax_type"] == "應稅"
    assert (out["sales_amount"], out["tax_amount"], out["total_amount"]) == (
        "6000.00",
        "300.00",
        "6300.00",
    )
    assert out["items"][0] == {
        "line_no": 1,
        "item_name": "辦公用品",
        "quantity": "2.0000",
        "unit_price": "1000.00",
        "amount": "2000.00",  # line_amount → amount
    }
    assert "line_amount" not in out["items"][0]


def test_decimal_strings_are_passed_through_untouched() -> None:
    out = adapt_invoice_detail(build_api_detail(sales_amount="1000.00", tax_amount="0.50"))

    assert out["sales_amount"] == "1000.00" and out["tax_amount"] == "0.50"
    assert isinstance(out["sales_amount"], str)


def test_does_not_invent_data_the_api_does_not_have() -> None:
    out = adapt_invoice_detail(build_api_detail(modified_fields=[_record()]))

    assert "original_values" not in out  # 後端沒有 AI 原始快照
    assert "form_type" not in out and "remark" not in out
    assert "validation" not in out


@pytest.mark.parametrize(
    ("track", "number", "expected"),
    [
        ("CD", "75670992", "CD75670992"),
        (" CD ", " 75670992 ", "CD75670992"),
        ("CD", None, None),
        (None, "75670992", None),
        (None, None, None),
        ("", "75670992", None),
        ("CD", "  ", None),
        (5, "75670992", None),
    ],
)
def test_track_number_is_combined_only_when_both_parts_exist(
    track: Any, number: Any, expected: Any
) -> None:
    out = adapt_invoice_detail(build_api_detail(invoice_track=track, invoice_number=number))

    assert out["track_number"] == expected


@pytest.mark.parametrize(
    ("code", "label"),
    [
        ("taxable", "應稅"),
        ("zero_rated", "零稅率"),
        ("tax_exempt", "免稅"),
        ("future_code", "future_code"),
        (None, None),
    ],
)
def test_tax_type_code_to_chinese_unknown_kept(code: Any, label: Any) -> None:
    assert adapt_invoice_detail(build_api_detail(tax_type=code))["tax_type"] == label


def test_null_fields_stay_none_and_empty_items_are_kept_empty() -> None:
    nullable = {
        key: None
        for key in (
            "invoice_track",
            "invoice_number",
            "invoice_date",
            "seller_tax_id",
            "seller_name",
            "buyer_tax_id",
            "buyer_name",
            "tax_type",
            "sales_amount",
            "tax_amount",
            "total_amount",
            "total_amount_zh",
            "file",
        )
    }
    out = adapt_invoice_detail(build_api_detail(items=[], **nullable))

    assert out["items"] == []
    assert out["track_number"] is None and out["buyer_name"] is None and out["tax_type"] is None


def test_item_line_no_is_kept_and_non_integer_line_no_becomes_none() -> None:
    items = build_api_detail()["items"]
    items[0]["line_no"] = True
    items[1]["line_no"] = "2"

    out = adapt_invoice_detail(build_api_detail(items=items))

    assert [row["line_no"] for row in out["items"]] == [None, None]


def test_non_object_items_are_skipped_like_the_row_builder_does() -> None:
    items = [build_api_detail()["items"][0], "x", None, 5]

    assert len(adapt_invoice_detail(build_api_detail(items=items))["items"]) == 1


# ---- warnings ----


def test_warnings_are_wrapped_for_the_existing_validation_adapter_without_severity() -> None:
    warning = {"field": "tax_amount", "code": "tax_amount_mismatch", "message": "稅額與銷售額不符"}
    out = adapt_invoice_detail(build_api_detail(warnings=[warning]))

    assert out["validation_results"] == {"warnings": [warning]}
    assert "severity" not in out["validation_results"]["warnings"][0]


def test_warning_extra_keys_are_not_forwarded_and_non_objects_become_text() -> None:
    raw = [{"field": "items", "code": "c", "message": "m", "severity": "error", "x": 1}, 5, None]
    out = adapt_invoice_detail(build_api_detail(warnings=raw))

    assert out["validation_results"]["warnings"] == [
        {"field": "items", "code": "c", "message": "m"},
        "5",
        EMPTY_TEXT,
    ]


# ---- 不修改輸入 ----


def test_input_is_not_mutated_and_output_shares_no_mutable_state() -> None:
    raw = build_api_detail(
        warnings=[{"field": "items", "code": "c", "message": "m"}],
        modified_fields=[
            _record(),
            _record("item", "line_amount", 2, "4000", "4000.5"),
            _record("header", "deleted_item_3", None, {"item_name": "舊", "x": [1]}, None),
            _record("future", "x", None, {"a": [1, {"b": 2}]}, [3]),
        ],
    )
    snapshot = copy.deepcopy(raw)

    out = adapt_invoice_detail(raw)
    assert raw == snapshot

    out["items"].append("x")
    out["items"][0]["item_name"] = "被改"
    out["validation_results"]["warnings"].clear()
    out["modifications"]["header"].clear()
    out["modifications"]["deleted"][0]["cells"].clear()
    assert raw == snapshot


# ---- 輸入根本不是發票詳情 ----


@pytest.mark.parametrize("raw", [None, [], "x", 5, True])
def test_non_object_input_raises_instead_of_rendering_an_empty_case(raw: Any) -> None:
    with pytest.raises(InvoiceDetailFormatError):
        adapt_invoice_detail(raw)


@pytest.mark.parametrize(
    "overrides",
    [{"invoice_id": None}, {"invoice_id": ""}, {"invoice_id": 5}, {"items": None}, {"items": {}}],
)
def test_missing_identity_or_items_raises(overrides: dict[str, Any]) -> None:
    with pytest.raises(InvoiceDetailFormatError):
        adapt_invoice_detail(build_api_detail(**overrides))


def test_missing_keys_raises_only_for_identity_and_degrades_for_the_rest() -> None:
    out = adapt_invoice_detail({"invoice_id": "x", "items": []})

    assert out["track_number"] is None and out["status"] is None
    assert out["modifications"]["total"] == 0
    assert out["validation_results"] == {"warnings": []}


JUNK = [None, True, 1.5, {"a": [1]}, [1, {"b": 2}], "\x00\x1f", "x" * 5000, float("nan")]


@pytest.mark.parametrize("junk", JUNK, ids=repr)
def test_junk_values_never_raise_once_identity_is_valid(junk: Any) -> None:
    raw = build_api_detail()
    for key in raw:
        if key not in {"invoice_id", "items"}:
            raw[key] = junk
    raw["items"] = [{"line_no": junk, "item_name": junk, "line_amount": junk}, junk]

    out = adapt_invoice_detail(raw)

    assert isinstance(out["modifications"], dict)
    assert all(isinstance(row["amount"], str | int | None) for row in out["items"])


# ---- 修改紀錄分類：每一筆都有去處 ----


def test_known_header_and_item_records_are_classified() -> None:
    mods = _mods(
        _record("header", "buyer_name", None, "舊公司"),
        _record("header", "invoice_track", None, "AB"),
        _record("item", "line_amount", 2, "4000"),
    )

    assert mods["header"] == [
        {"name": "buyer_name", "original": "舊公司"},
        {"name": "invoice_track", "original": "AB"},
    ]
    assert mods["items"] == [{"line_no": 2, "name": "line_amount", "original": "4000"}]
    assert mods["deleted"] == [] and mods["other"] == []
    assert mods["total"] == 3


def test_deleted_item_is_its_own_group_with_whitelisted_cells() -> None:
    original = {"item_name": "舊品名", "quantity": "1", "unit_price": "100", "line_amount": None}
    mods = _mods(_record("header", "deleted_item_3", None, original, None))

    assert mods["deleted"] == [
        {
            "ai_line_no": 3,
            "cells": [
                ("item_name", "舊品名"),
                ("quantity", "1"),
                ("unit_price", "100"),
                ("line_amount", EMPTY_TEXT),
            ],
            "omitted_extra": False,
        }
    ]
    assert mods["header"] == [] and mods["items"] == [] and mods["other"] == []


def test_deleted_item_with_unknown_nested_keys_marks_omission_and_never_expands_them() -> None:
    original = {"item_name": "舊", "secret": {"a": [1]}, "quantity": {"nested": 1}}
    (deleted,) = _mods(_record("header", "deleted_item_1", None, original, None))["deleted"]

    assert deleted["omitted_extra"] is True
    assert dict(deleted["cells"]) == {"item_name": "舊", "quantity": STRUCTURED_TEXT}
    assert "secret" not in str(deleted)


def test_deleted_item_number_is_ai_sequence_and_leading_zeros_are_parsed() -> None:
    (deleted,) = _mods(_record("header", "deleted_item_007", None, {"item_name": "x"}, None))[
        "deleted"
    ]

    assert deleted["ai_line_no"] == 7


@pytest.mark.parametrize(
    "bad",
    [
        _record("header", "deleted_item_x", None, {"item_name": "x"}, None),
        _record("header", "deleted_item_", None, {"item_name": "x"}, None),
        _record("header", "deleted_item_1234567", None, {"item_name": "x"}, None),  # 超過 6 位
        _record("header", "deleted_item_٣", None, {"item_name": "x"}, None),  # 非 ASCII 數字
        _record("header", "deleted_item_３", None, {"item_name": "x"}, None),  # 全形數字
        _record("header", "deleted_item_3", None, "不是物件", None),
        _record("header", "deleted_item_3", None, None, None),
        _record("header", "deleted_item_3", None, ["a"], None),
        _record("header", "deleted_item_3", 2, {"item_name": "x"}, None),  # header 不該有 line_no
        _record("item", "deleted_item_3", 1, {"item_name": "x"}, None),
    ],
)
def test_malformed_deleted_item_falls_back_to_other_and_is_never_dropped(bad: Any) -> None:
    mods = _mods(bad)

    assert mods["deleted"] == []
    assert len(mods["other"]) == 1 and mods["total"] == 1


@pytest.mark.parametrize(
    "record",
    [
        _record("future_scope", "buyer_name"),
        _record("header", "future_field"),
        _record("header", "buyer_name", 3),  # 表頭欄位帶了 line_no
        _record("item", "line_amount", None),  # 明細欄位沒有 line_no
        _record("item", "line_amount", True),
        _record("item", "future_field", 1),
        _record(None, None),
        _record(5, 6, "x"),
        "不是物件",
        None,
        5,
        [1],
    ],
    ids=repr,
)
def test_unknown_or_inconsistent_records_go_to_other_never_silently_dropped(record: Any) -> None:
    mods = _mods(record)

    assert len(mods["other"]) == 1
    assert (mods["header"], mods["items"], mods["deleted"]) == ([], [], [])
    assert mods["total"] == 1


def test_other_record_keeps_scope_name_line_no_and_both_values_as_text() -> None:
    (other,) = _mods(_record("future", "mystery", 4, {"a": [1]}, [2]))["other"]

    assert other == {
        "scope": "future",
        "name": "mystery",
        "line_no": 4,
        "original": STRUCTURED_TEXT,
        "submitted": STRUCTURED_TEXT,
    }


def test_every_record_is_accounted_for() -> None:
    records = [
        _record("header", "buyer_name"),
        _record("item", "item_name", 1),
        _record("header", "deleted_item_2", None, {"item_name": "x"}, None),
        _record("header", "nope"),
        "garbage",
        _record("header", "buyer_name"),  # 重複的紀錄也各自保留
    ]
    mods = _mods(*records)

    assert mods["total"] == len(records)
    assert sum(len(mods[group]) for group in ("header", "items", "deleted", "other")) == len(
        records
    )
    assert len(mods["header"]) == 2


def test_modified_fields_not_a_list_yields_empty_groups() -> None:
    out = adapt_invoice_detail({"invoice_id": "x", "items": [], "modified_fields": {"a": 1}})

    assert out["modifications"]["total"] == 0


def test_canonical_value_is_displayed_as_recorded_and_never_compared_with_the_field() -> None:
    # 欄位 "1000.00"、紀錄標準值 "1000"：原樣呈現紀錄，不產生任何比較結果
    out = adapt_invoice_detail(
        build_api_detail(
            sales_amount="1000.00",
            modified_fields=[_record("header", "sales_amount", None, "1000", "1000")],
        )
    )

    assert out["sales_amount"] == "1000.00"
    assert out["modifications"]["header"] == [{"name": "sales_amount", "original": "1000"}]


def test_tax_type_record_is_shown_in_chinese() -> None:
    (header,) = _mods(_record("header", "tax_type", None, "tax_exempt", "taxable"))["header"]

    assert header["original"] == "免稅"


# ---- 值的安全顯示 ----


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, EMPTY_TEXT),
        ("", EMPTY_TEXT),
        ("   ", EMPTY_TEXT),
        ("普通文字", "普通文字"),
        ("<script>alert(1)</script>", "<script>alert(1)</script>"),  # 轉義交給樣板，這裡不改寫
        ("a\x00b\x1fc\x7f", "abc"),
        (7, "7"),
        (True, "true"),
        (False, "false"),
        (1.5, UNDISPLAYABLE_TEXT),
        (float("nan"), UNDISPLAYABLE_TEXT),
        ({"a": 1}, STRUCTURED_TEXT),
        ([1, 2], STRUCTURED_TEXT),
        ((1,), STRUCTURED_TEXT),
        (object(), UNDISPLAYABLE_TEXT),
    ],
)
def test_display_value(value: Any, text: str) -> None:
    assert display_value(value) == text


def test_display_value_truncates_and_marks_long_text() -> None:
    long = "字" * (MAX_DISPLAY_CHARS + 50)
    shown = display_value(long)

    assert shown == "字" * MAX_DISPLAY_CHARS + TRUNCATED_SUFFIX
    assert display_value("字" * MAX_DISPLAY_CHARS) == "字" * MAX_DISPLAY_CHARS


def test_display_value_maps_tax_type_only_for_the_tax_type_field() -> None:
    assert display_value("taxable", field_name="tax_type") == "應稅"
    assert display_value("taxable", field_name="buyer_name") == "taxable"
    assert display_value("unknown_code", field_name="tax_type") == "unknown_code"


# ---- 隔離 ----


def test_adapter_source_never_touches_demo_or_fixture_modules() -> None:
    source = inspect.getsource(invoice_detail_adapter)

    assert "demo_invoice" not in source and "build_demo_invoice" not in source
    assert "import httpx" not in source and "app.clients" not in source
