"""測試目標：人工修改差異計算（C-01）——比較兩份完整發票快照；純函式，不涉及 API Contract、提交或持久化"""

import copy
import dataclasses
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest

from app.utils import field_changes
from app.utils.field_changes import (
    FieldChangeSet,
    IncompleteSnapshotError,
    ValueChange,
    detect_field_changes,
)
from app.utils.invoice_fields import (
    FIXTURE_ITEM_KEYS,
    FIXTURE_ITEMS_KEY,
    FIXTURE_VALUE_KEYS,
    UI_FIELDS,
)

ITEM_FIELD_IDS = ("F06", "F07", "F08", "F09")


def _row(
    name: str = "文具", quantity: Any = "2", unit_price: Any = "50", amount: Any = "100"
) -> dict:
    return {
        "item_name": name,
        "quantity": quantity,
        "unit_price": unit_price,
        "amount": amount,
    }


def _snapshot(**overrides: Any) -> dict[str, Any]:
    """完整快照 mock；key 為 frontend-only fixture key，非正式 Contract。"""
    data: dict[str, Any] = {
        "form_type": "三聯式",
        "track_number": "AB12345678",
        "invoice_date": "2026-10-20",
        "buyer_name": "測試股份有限公司",
        "buyer_tax_id": "12345678",
        "items": [_row(), _row("影印紙", "1", "200", "200")],
        "sales_amount": "300",
        "tax_type": "應稅",
        "tax_amount": "15",
        "total_amount": "315",
        "total_amount_zh": "參佰壹拾伍元整",
        "remark": "",
        "seller_name": "測試商行",
    }
    data.update(overrides)
    return data


def _only(change_set: FieldChangeSet) -> ValueChange:
    assert len(change_set.field_changes) == 1
    return change_set.field_changes[0]


# ---- 1～5：基本比較 ----


def test_unchanged_snapshots_report_no_changes() -> None:
    result = detect_field_changes(_snapshot(), _snapshot())

    assert not result.has_changes
    assert result.field_changes == ()
    assert result.item_changes == ()
    assert result.changed_field_ids == ()


def test_text_field_modified_reports_modified_and_keeps_raw_values() -> None:
    result = detect_field_changes(_snapshot(), _snapshot(buyer_name="新公司"))

    change = _only(result)
    assert (change.field_id, change.label, change.kind) == ("F04", None, "modified")
    assert (change.original, change.current) == ("測試股份有限公司", "新公司")
    assert result.has_changes
    assert result.changed_field_ids == ("F04",)


@pytest.mark.parametrize(
    ("before", "after"),
    [("300", "350"), (300, 350), (Decimal("300.5"), Decimal("350.5")), (300, "350")],
)
def test_numeric_field_modified_keeps_original_input_types(before: Any, after: Any) -> None:
    result = detect_field_changes(_snapshot(sales_amount=before), _snapshot(sales_amount=after))

    change = _only(result)
    assert change.field_id == "F10"
    assert change.original == before
    assert type(change.original) is type(before)
    assert change.current == after
    assert type(change.current) is type(after)


def test_null_original_filled_reports_filled() -> None:
    result = detect_field_changes(_snapshot(remark=None), _snapshot(remark="勞動節禮盒"))

    change = _only(result)
    assert (change.field_id, change.kind) == ("F13", "filled")
    assert change.original is None
    assert change.current == "勞動節禮盒"


@pytest.mark.parametrize("cleared", [None, "", "   "])
def test_value_cleared_reports_cleared_and_keeps_raw_current(cleared: Any) -> None:
    result = detect_field_changes(_snapshot(), _snapshot(buyer_name=cleared))

    change = _only(result)
    assert (change.field_id, change.kind) == ("F04", "cleared")
    assert change.original == "測試股份有限公司"
    assert change.current == cleared


def test_none_empty_and_blank_values_are_all_equal_empty() -> None:
    for before, after in [(None, ""), ("", None), (None, "  "), ("  ", "")]:
        result = detect_field_changes(_snapshot(remark=before), _snapshot(remark=after))
        assert not result.has_changes


# ---- 6：完整快照的結構檢查 ----

STRUCTURE_KEYS = [key for parts in FIXTURE_VALUE_KEYS.values() for _, key in parts] + [
    FIXTURE_ITEMS_KEY
]


@pytest.mark.parametrize("missing_key", STRUCTURE_KEYS)
@pytest.mark.parametrize("which", ["original", "current"])
def test_missing_structure_key_raises_incomplete_snapshot(missing_key: str, which: str) -> None:
    broken = _snapshot()
    del broken[missing_key]
    complete = _snapshot()
    args = (broken, complete) if which == "original" else (complete, broken)

    with pytest.raises(IncompleteSnapshotError, match=missing_key) as excinfo:
        detect_field_changes(*args)

    assert excinfo.value.snapshot == which
    assert excinfo.value.missing_keys == (missing_key,)
    assert excinfo.value.row_index is None
    assert which in str(excinfo.value)


def test_incomplete_snapshot_error_is_value_error_and_lists_all_missing_keys() -> None:
    broken = _snapshot()
    del broken["remark"]
    del broken["buyer_name"]

    with pytest.raises(ValueError) as excinfo:
        detect_field_changes(broken, _snapshot())

    assert isinstance(excinfo.value, IncompleteSnapshotError)
    assert set(excinfo.value.missing_keys) == {"remark", "buyer_name"}


def test_structure_key_with_none_value_is_allowed_as_empty() -> None:
    all_none = _snapshot(**{key: None for key in STRUCTURE_KEYS})
    result = detect_field_changes(all_none, _snapshot())

    assert result.has_changes
    assert detect_field_changes(all_none, copy.deepcopy(all_none)).has_changes is False


def test_items_none_is_treated_as_no_rows() -> None:
    result = detect_field_changes(_snapshot(items=None), _snapshot(items=[]))

    assert not result.has_changes


def test_item_row_missing_structure_key_raises_with_row_index() -> None:
    broken_row = _row()
    del broken_row["unit_price"]
    broken = _snapshot(items=[_row(), broken_row])

    with pytest.raises(IncompleteSnapshotError, match="unit_price") as excinfo:
        detect_field_changes(_snapshot(), broken)

    assert excinfo.value.snapshot == "current"
    assert excinfo.value.row_index == 1
    assert excinfo.value.missing_keys == ("unit_price",)


def test_item_row_beyond_other_snapshot_length_is_still_validated() -> None:
    broken_row = _row()
    del broken_row["amount"]
    broken = _snapshot(items=[_row(), _row(), broken_row])

    with pytest.raises(IncompleteSnapshotError) as excinfo:
        detect_field_changes(_snapshot(), broken)

    assert excinfo.value.row_index == 2


def test_item_cell_with_none_value_is_allowed() -> None:
    row = _row(quantity=None)
    result = detect_field_changes(_snapshot(items=[row]), _snapshot(items=[_row(quantity=None)]))

    assert not result.has_changes


def test_extra_keys_are_ignored() -> None:
    original = _snapshot(validation={"issues": []}, original_values={"buyer_name": "x"}, note=1.5)
    current = _snapshot(validation={"issues": [1]}, original_values={}, other=[1, 2])

    assert not detect_field_changes(original, current).has_changes


def test_item_row_extra_keys_are_ignored() -> None:
    row = _row()
    row["line_no"] = 1.5
    assert not detect_field_changes(_snapshot(items=[row]), _snapshot(items=[_row()])).has_changes


# ---- 7：複合欄位 ----


def test_composite_field_reports_only_changed_part() -> None:
    result = detect_field_changes(_snapshot(), _snapshot(tax_amount="16"))

    change = _only(result)
    assert (change.field_id, change.label, change.original, change.current) == (
        "F11",
        "稅額",
        "15",
        "16",
    )
    assert result.changed_field_ids == ("F11",)


def test_composite_field_both_parts_changed_reports_two_changes_in_part_order() -> None:
    result = detect_field_changes(
        _snapshot(), _snapshot(total_amount="320", total_amount_zh="參佰貳拾元整")
    )

    assert [(c.field_id, c.label) for c in result.field_changes] == [
        ("F12", "總計"),
        ("F12", "國字大寫"),
    ]
    assert result.changed_field_ids == ("F12",)


# ---- 8～9：明細列（依位置比對）----


def test_item_cell_modified_reports_row_change() -> None:
    current = _snapshot(items=[_row(), _row("影印紙", "1", "250", "200")])

    result = detect_field_changes(_snapshot(), current)

    assert result.field_changes == ()
    assert len(result.item_changes) == 1
    row = result.item_changes[0]
    assert (row.row_index, row.status) == (1, "modified")
    assert [(c.field_id, c.original, c.current) for c in row.changes] == [("F08", "200", "250")]
    assert result.has_changes
    assert result.changed_field_ids == ("F08",)


def test_item_row_added_reports_added_with_non_empty_cells() -> None:
    current = _snapshot(
        items=[_row(), _row("影印紙", "1", "200", "200"), _row("墨水", "3", "", "90")]
    )

    result = detect_field_changes(_snapshot(), current)

    row = result.item_changes[0]
    assert (row.row_index, row.status) == (2, "added")
    assert [(c.field_id, c.original, c.current, c.kind) for c in row.changes] == [
        ("F06", None, "墨水", "filled"),
        ("F07", None, "3", "filled"),
        ("F09", None, "90", "filled"),
    ]
    assert result.changed_field_ids == ITEM_FIELD_IDS


def test_item_row_removed_reports_removed_with_non_empty_cells() -> None:
    current = _snapshot(items=[_row()])

    result = detect_field_changes(_snapshot(), current)

    row = result.item_changes[0]
    assert (row.row_index, row.status) == (1, "removed")
    assert [(c.field_id, c.original, c.current, c.kind) for c in row.changes] == [
        ("F06", "影印紙", None, "cleared"),
        ("F07", "1", None, "cleared"),
        ("F08", "200", None, "cleared"),
        ("F09", "200", None, "cleared"),
    ]
    assert result.changed_field_ids == ITEM_FIELD_IDS


def test_added_blank_row_is_a_structure_change() -> None:
    blank = _row(None, "", "  ", None)
    result = detect_field_changes(
        _snapshot(), _snapshot(items=[_row(), _row("影印紙", "1", "200", "200"), blank])
    )

    assert result.has_changes
    row = result.item_changes[0]
    assert (row.row_index, row.status, row.changes) == (2, "added", ())
    assert result.changed_field_ids == ITEM_FIELD_IDS


def test_removed_blank_row_is_a_structure_change() -> None:
    blank = _row(None, "", "  ", None)
    original = _snapshot(items=[_row(), blank])

    result = detect_field_changes(original, _snapshot(items=[_row()]))

    assert result.has_changes
    row = result.item_changes[0]
    assert (row.row_index, row.status, row.changes) == (1, "removed", ())
    assert result.changed_field_ids == ITEM_FIELD_IDS


def test_blank_row_equal_to_blank_row_is_not_a_change() -> None:
    original = _snapshot(items=[_row(None, None, None, None)])
    current = _snapshot(items=[_row("", " ", "", None)])

    assert not detect_field_changes(original, current).has_changes


def test_reordered_item_rows_are_reported_as_modifications_of_both_rows() -> None:
    """限制：列以位置識別，沒有穩定列 ID；交換兩列不會被辨識為「移動」。"""
    first, second = _row(), _row("影印紙", "1", "200", "200")

    result = detect_field_changes(
        _snapshot(items=[first, second]), _snapshot(items=[second, first])
    )

    assert [(r.row_index, r.status) for r in result.item_changes] == [
        (0, "modified"),
        (1, "modified"),
    ]
    assert result.item_changes[0].changes[0].original == "文具"
    assert result.item_changes[0].changes[0].current == "影印紙"
    assert result.changed_field_ids == ITEM_FIELD_IDS


def test_deleting_middle_row_shifts_following_rows() -> None:
    """限制：刪除中間列，後面的列會顯示為修改，最後一列顯示為移除。"""
    rows = [_row("A", "1", "10", "10"), _row("B", "1", "20", "20"), _row("C", "1", "30", "30")]

    result = detect_field_changes(_snapshot(items=rows), _snapshot(items=[rows[0], rows[2]]))

    assert [(r.row_index, r.status) for r in result.item_changes] == [
        (1, "modified"),
        (2, "removed"),
    ]
    assert result.item_changes[0].changes[0].original == "B"
    assert result.item_changes[0].changes[0].current == "C"


def test_item_changes_are_ordered_by_row_index() -> None:
    rows = [_row("A"), _row("B"), _row("C")]
    changed = [_row("A1"), _row("B"), _row("C1")]

    result = detect_field_changes(_snapshot(items=rows), _snapshot(items=changed))

    assert [r.row_index for r in result.item_changes] == [0, 2]


# ---- 10：不修改輸入 ----


def test_inputs_are_not_mutated() -> None:
    original = _snapshot(remark=None)
    current = _snapshot(buyer_name="新公司", items=[_row("文具", "3", "50", "150")])
    original_before, current_before = copy.deepcopy(original), copy.deepcopy(current)

    detect_field_changes(original, current)

    assert original == original_before
    assert current == current_before


def test_read_only_mappings_are_accepted() -> None:
    original = MappingProxyType(_snapshot())
    current = MappingProxyType(_snapshot(buyer_name="新公司"))

    assert detect_field_changes(original, current).changed_field_ids == ("F04",)


def test_result_does_not_share_mutable_state_with_inputs() -> None:
    current = _snapshot(items=[_row(), _row("影印紙", "1", "200", "250")])

    result = detect_field_changes(_snapshot(), current)
    current["items"][1]["unit_price"] = "999"

    assert result.item_changes[0].changes[0].current == "250"


# ---- 11：輸入型別異常 ----


@pytest.mark.parametrize("bad", [None, [], "abc", 1, [("a", 1)]])
@pytest.mark.parametrize("position", [0, 1])
def test_non_mapping_snapshot_raises_type_error(bad: Any, position: int) -> None:
    args = [_snapshot(), _snapshot()]
    args[position] = bad

    with pytest.raises(TypeError, match="Mapping"):
        detect_field_changes(*args)


@pytest.mark.parametrize("bad_items", ["abc", {"a": 1}, 3, ("x",)])
def test_items_not_a_list_raises_type_error(bad_items: Any) -> None:
    with pytest.raises(TypeError, match="list"):
        detect_field_changes(_snapshot(), _snapshot(items=bad_items))


@pytest.mark.parametrize("bad_row", ["row", None, 5, [1, 2]])
def test_item_row_not_a_mapping_raises_type_error(bad_row: Any) -> None:
    with pytest.raises(TypeError, match="Mapping"):
        detect_field_changes(_snapshot(items=[bad_row]), _snapshot())


@pytest.mark.parametrize("bad_value", [1.5, True, False, ["a"], {"a": 1}, b"x", object()])
def test_unsupported_value_type_raises_type_error(bad_value: Any) -> None:
    with pytest.raises(TypeError, match="型別"):
        detect_field_changes(_snapshot(), _snapshot(buyer_name=bad_value))
    with pytest.raises(TypeError, match="型別"):
        detect_field_changes(_snapshot(sales_amount=bad_value), _snapshot())


@pytest.mark.parametrize("bad_value", [1.5, True, ["a"]])
def test_unsupported_item_cell_type_raises_type_error(bad_value: Any) -> None:
    with pytest.raises(TypeError, match="型別"):
        detect_field_changes(_snapshot(), _snapshot(items=[_row(unit_price=bad_value)]))


def test_unsupported_value_in_unchanged_position_still_raises() -> None:
    with pytest.raises(TypeError, match="型別"):
        detect_field_changes(_snapshot(remark=1.5), _snapshot(remark=1.5))


# ---- 12：重複執行與排序 ----


def test_repeated_calls_return_equal_results() -> None:
    original = _snapshot()
    current = _snapshot(buyer_name="新", items=[_row("文具", "3", "50", "150")], remark="備")

    assert detect_field_changes(original, current) == detect_field_changes(original, current)


def test_field_changes_follow_ui_field_order() -> None:
    current = _snapshot(seller_name="新商行", buyer_name="新公司", form_type="二聯式", remark="備")

    result = detect_field_changes(_snapshot(), current)

    assert [c.field_id for c in result.field_changes] == ["F01", "F04", "F13", "F14"]
    assert result.changed_field_ids == ("F01", "F04", "F13", "F14")


def test_changed_field_ids_merge_item_and_scalar_fields_in_ui_order() -> None:
    current = _snapshot(
        seller_name="新商行",
        items=[_row("文具", "2", "55", "100"), _row("影印紙", "1", "200", "200")],
    )

    result = detect_field_changes(_snapshot(), current)

    assert result.changed_field_ids == ("F08", "F14")


# ---- 規則細節 ----


def test_whitespace_only_difference_is_not_a_change() -> None:
    result = detect_field_changes(_snapshot(buyer_name="  測試股份有限公司 "), _snapshot())

    assert not result.has_changes


def test_change_keeps_untrimmed_original_input_values() -> None:
    result = detect_field_changes(
        _snapshot(buyer_name="  舊公司 "), _snapshot(buyer_name=" 新公司  ")
    )

    change = _only(result)
    assert (change.original, change.current) == ("  舊公司 ", " 新公司  ")


def test_trailing_zero_difference_counts_as_change() -> None:
    """限制：不做金額正規化，"100" 與 "100.00" 視為不同文字。"""
    result = detect_field_changes(_snapshot(sales_amount="100"), _snapshot(sales_amount="100.00"))

    assert _only(result).field_id == "F10"


@pytest.mark.parametrize(("left", "right"), [(100, "100"), (Decimal("100"), "100"), ("100", 100)])
def test_int_decimal_and_matching_text_are_equal(left: Any, right: Any) -> None:
    result = detect_field_changes(_snapshot(sales_amount=left), _snapshot(sales_amount=right))

    assert not result.has_changes


def test_zero_is_not_treated_as_empty() -> None:
    result = detect_field_changes(_snapshot(tax_amount=0), _snapshot(tax_amount=None))

    change = _only(result)
    assert (change.field_id, change.kind) == ("F11", "cleared")


def _non_item_changes() -> list[tuple[str, str, str | None]]:
    cases = []
    for field in UI_FIELDS:
        if field.kind == "items":
            continue
        for label, key in FIXTURE_VALUE_KEYS[field.field_id]:
            cases.append((field.field_id, key, label))
    return cases


@pytest.mark.parametrize(("field_id", "key", "label"), _non_item_changes())
def test_every_non_item_key_maps_to_its_ui_field_id(
    field_id: str, key: str, label: str | None
) -> None:
    result = detect_field_changes(_snapshot(), _snapshot(**{key: "變更後的值"}))

    change = _only(result)
    assert (change.field_id, change.label) == (field_id, label)


@pytest.mark.parametrize(("field_id", "key"), sorted(FIXTURE_ITEM_KEYS.items()))
def test_every_item_key_maps_to_its_ui_field_id(field_id: str, key: str) -> None:
    changed_row = _row()
    changed_row[key] = "變更後的值"

    result = detect_field_changes(_snapshot(items=[_row()]), _snapshot(items=[changed_row]))

    assert result.changed_field_ids == (field_id,)
    assert result.item_changes[0].changes[0].field_id == field_id


def test_results_are_immutable_and_not_serializable() -> None:
    result = detect_field_changes(_snapshot(), _snapshot(buyer_name="新"))

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.field_changes = ()  # type: ignore[misc]
    assert isinstance(result.field_changes, tuple)
    assert isinstance(result.item_changes, tuple)
    for name in ("to_dict", "as_dict", "to_json", "model_dump", "dict", "json"):
        assert not hasattr(result, name)
        assert not hasattr(result.field_changes[0], name)


def test_module_has_no_network_or_api_dependency() -> None:
    source = field_changes.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    for forbidden in ("app.clients", "app.routers", "httpx", "app.core.config"):
        assert forbidden not in text
