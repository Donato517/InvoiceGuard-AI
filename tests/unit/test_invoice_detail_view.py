"""測試目標：API 詳情（經 adapter）進入 build_confirmation_view 後的畫面資料（Mock：純函式，不連任何服務）。

重點：修改備註只掛在有紀錄的欄位／明細列、明細只依真實 line_no 唯一對應、已刪除 AI 明細獨立呈現、
不虛構 AI 快照、fixture 輸入的行為不受影響。
"""

from typing import Any

from stage1_detail import build_api_detail

from app.utils.demo_invoice import build_demo_invoice
from app.utils.invoice_confirmation import ConfirmationView, build_confirmation_view
from app.utils.invoice_detail_adapter import adapt_invoice_detail


def _record(
    scope: str = "header",
    name: str = "buyer_name",
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


def _view(**overrides: Any) -> ConfirmationView:
    return build_confirmation_view(adapt_invoice_detail(build_api_detail(**overrides)))


def _items(view: ConfirmationView) -> Any:
    return next(s for s in view.sections if s.kind == "items")


def _section(view: ConfirmationView, field_id: str) -> Any:
    return next(s for s in view.sections if s.kind == "field" and s.field.field_id == field_id)


def _item(line_no: Any, name: str = "品") -> dict[str, Any]:
    return {
        "line_no": line_no,
        "item_name": name,
        "quantity": "1",
        "unit_price": "10",
        "line_amount": "10",
    }


# ---- 不虛構 AI 快照 ----


def test_api_detail_has_no_snapshot_and_no_original_status_anywhere() -> None:
    view = _view(modified_fields=[_record()])

    assert view.has_ai_snapshot is False
    assert view.modifications is not None and view.modifications.total == 1
    statuses = {p.status for s in view.sections if s.kind == "field" for p in s.parts}
    assert statuses == {"no_snapshot"}  # 沒有任何欄位被標成 unchanged／modified 等比較結果
    assert all(p.original is None for s in view.sections if s.kind == "field" for p in s.parts)
    items = _items(view)
    assert {r.status for r in items.row_originals} == {"no_snapshot"}
    assert not items.row_count_mismatch and not items.row_compare_limited


def test_no_modified_fields_means_no_notes_but_still_marked_as_record_mode() -> None:
    view = _view(modified_fields=[])

    assert view.modifications is not None and view.modifications.total == 0
    assert all(s.modifications == () for s in view.sections if s.kind == "field")
    assert _items(view).modification_mode is True
    assert all(notes == () for notes in _items(view).row_modifications)


# ---- 欄位備註 ----


def test_header_notes_are_attached_only_to_fields_with_records() -> None:
    view = _view(
        modified_fields=[
            _record(name="buyer_name", original="舊公司"),
            _record(name="invoice_track", original="AB"),
            _record(name="invoice_number", original="11112222"),
            _record(name="tax_type", original="tax_exempt"),
            _record(name="seller_tax_id", original="11111111"),
        ]
    )

    assert [(n.label, n.original) for n in _section(view, "F04").modifications] == [
        (None, "舊公司")
    ]
    assert [(n.label, n.original) for n in _section(view, "F02").modifications] == [
        ("字軌", "AB"),
        ("號碼", "11112222"),
    ]
    assert [(n.label, n.original) for n in _section(view, "F11").modifications] == [
        ("課稅別", "免稅")
    ]
    assert [(n.label, n.original) for n in _section(view, "F14").modifications] == [
        ("統編", "11111111")
    ]
    for untouched in ("F03", "F05", "F10", "F12"):
        assert _section(view, untouched).modifications == ()


def test_f02_shows_combined_track_number_and_f14_shows_seller_tax_id() -> None:
    view = _view()

    assert _section(view, "F02").parts[0].value == "CD75670992"
    f14 = _section(view, "F14").parts
    assert [(p.label, p.value) for p in f14] == [(None, "範例文具行"), ("統編", "27601907")]
    assert _section(view, "F11").parts[0].value == "應稅"


def test_decimal_string_is_displayed_as_is_and_record_is_not_compared_with_it() -> None:
    view = _view(
        sales_amount="1000.00",
        modified_fields=[_record(name="sales_amount", original="1000", submitted="1000")],
    )

    section = _section(view, "F10")
    assert section.parts[0].value == "1000.00"
    assert section.parts[0].status == "no_snapshot"
    assert [n.original for n in section.modifications] == ["1000"]


# ---- 明細列：只依真實 line_no 唯一對應 ----


def test_item_note_is_attached_by_real_line_no_not_by_position() -> None:
    view = _view(
        items=[_item(1, "甲"), _item(5, "乙"), _item(9, "丙")],  # 不連續
        modified_fields=[_record("item", "line_amount", 5, "99")],
    )

    items = _items(view)
    assert items.row_line_nos == (1, 5, 9)
    assert [[n.original for n in notes] for notes in items.row_modifications] == [[], ["99"], []]
    assert items.row_modifications[1][0].label == "金額"
    assert view.modifications.unmatched_items == ()


def test_position_is_never_used_when_line_no_does_not_match() -> None:
    view = _view(
        items=[_item(1), _item(5)],
        modified_fields=[_record("item", "item_name", 2, "舊品名")],  # 第 2 位置，但沒有 line_no=2
    )

    items = _items(view)
    assert all(notes == () for notes in items.row_modifications)
    (note,) = view.modifications.unmatched_items
    assert (note.line_no, note.label, note.original) == (2, "品名／用途", "舊品名")
    assert "找不到" in note.reason


def test_duplicate_line_no_is_ambiguous_and_attached_to_no_row() -> None:
    view = _view(
        items=[_item(1), _item(1), _item(2)],
        modified_fields=[
            _record("item", "quantity", 1, "9"),
            _record("item", "unit_price", 2, "7"),
        ],
    )

    items = _items(view)
    assert [[n.original for n in notes] for notes in items.row_modifications] == [[], [], ["7"]]
    (note,) = view.modifications.unmatched_items
    assert (note.line_no, note.original) == (1, "9")
    assert "同一個序號" in note.reason


def test_rows_without_a_usable_line_no_receive_nothing() -> None:
    raw = adapt_invoice_detail(
        build_api_detail(
            items=[_item(1), _item(2)],
            modified_fields=[
                _record("item", "item_name", 1, "舊"),
                _record("item", "item_name", 2, "舊"),
            ],
        )
    )
    raw["items"][0]["line_no"] = None  # 假設 line_no 不可用

    view = build_confirmation_view(raw)

    items = _items(view)
    assert items.row_line_nos == (None, 2)
    assert [len(notes) for notes in items.row_modifications] == [0, 1]
    assert [n.line_no for n in view.modifications.unmatched_items] == [1]


def test_multiple_notes_on_one_row_keep_order() -> None:
    view = _view(
        modified_fields=[
            _record("item", "item_name", 1, "舊"),
            _record("item", "line_amount", 1, "5"),
        ]
    )

    assert [(n.label, n.original) for n in _items(view).row_modifications[0]] == [
        ("品名／用途", "舊"),
        ("金額", "5"),
    ]


# ---- 已刪除的 AI 明細、其他紀錄 ----


def test_deleted_ai_item_is_separate_and_never_in_item_rows() -> None:
    view = _view(
        modified_fields=[
            _record(
                "header",
                "deleted_item_2",
                None,
                {"item_name": "舊品名", "quantity": "1", "unit_price": None, "line_amount": "100"},
                None,
            )
        ]
    )

    items = _items(view)
    assert len(items.rows) == 2  # 目前明細不變
    assert all(notes == () for notes in items.row_modifications)
    (deleted,) = view.modifications.deleted_items
    assert deleted.ai_line_no == 2
    assert deleted.cells == (
        ("品名／用途", "舊品名"),
        ("數量", "1"),
        ("單價", "（空）"),
        ("金額", "100"),
    )
    assert "舊品名" not in str(items.rows)


def test_unknown_records_are_listed_in_other_not_dropped() -> None:
    view = _view(
        modified_fields=[
            _record("future", "x", 3, {"a": [1]}, [2]),
            _record("header", "mystery"),
            "garbage",
        ]
    )

    other = view.modifications.other
    assert len(other) == 3
    assert (other[0].scope, other[0].name, other[0].line_no) == ("future", "x", 3)
    assert other[0].original == "（結構化值，已省略）"
    assert other[2].original == "garbage"  # 不是物件的紀錄也保留原文


def test_every_modification_record_lands_somewhere() -> None:
    records = [
        _record("header", "buyer_name"),
        _record("item", "item_name", 1),
        _record("item", "item_name", 99),
        _record("header", "deleted_item_4", None, {"item_name": "x"}, None),
        _record("header", "nope"),
        "garbage",
        _record("header", "buyer_name"),
    ]
    view = _view(modified_fields=records)

    placed = (
        sum(len(s.modifications) for s in view.sections if s.kind == "field")
        + sum(len(n) for n in _items(view).row_modifications)
        + len(view.modifications.unmatched_items)
        + len(view.modifications.deleted_items)
        + len(view.modifications.other)
    )
    assert view.modifications.total == len(records) == placed


# ---- fixture／Demo 輸入不受影響 ----


def test_fixture_input_has_no_modifications_view() -> None:
    view = build_confirmation_view(build_demo_invoice())

    assert view.modifications is None
    items = _items(view)
    assert items.modification_mode is False
    assert items.row_modifications == ()
    assert all(s.modifications == () for s in view.sections if s.kind == "field")
    assert view.has_ai_snapshot is True  # Demo 仍有虛構的 AI 快照


def test_extra_seller_tax_id_part_only_when_the_source_has_the_key() -> None:
    demo = build_confirmation_view(build_demo_invoice())  # Demo 沒有 seller_tax_id
    assert [p.label for p in _section(demo, "F14").parts] == [None]

    with_key = dict(build_demo_invoice(), seller_tax_id="")
    parts = _section(build_confirmation_view(with_key), "F14").parts
    assert [(p.label, p.value) for p in parts] == [(None, "示範商行"), ("統編", "-")]


def test_builder_does_not_mutate_adapter_output() -> None:
    import copy

    adapted = adapt_invoice_detail(build_api_detail(modified_fields=[_record(), _record("x", "y")]))
    snapshot = copy.deepcopy(adapted)

    build_confirmation_view(adapted)

    assert adapted == snapshot
