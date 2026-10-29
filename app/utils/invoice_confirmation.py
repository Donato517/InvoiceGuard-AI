"""
模組名稱：app.utils.invoice_confirmation
功能說明：組合發票確認畫面的 view model——14 類欄位（含多筆明細）、各欄位的 issue、提交控制的畫面狀態。
相依模組：app.utils.invoice_fields、app.utils.validation_view
注意事項：
    - 輸入是 mock／暫定格式的 dict，讀取用的 key 全部集中在 invoice_fields.py 的 FIXTURE_*。
    - submit_control_enabled 只是畫面呈現條件，不代表案件已送審或核准，也不是 workflow 狀態。
    - original／current 並列只是畫面展示，不代表 AI 原值已被持久化保存。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.utils.invoice_fields import (
    FIXTURE_ISSUE_FIELD_TO_UI,
    FIXTURE_ITEM_KEYS,
    FIXTURE_ITEMS_KEY,
    FIXTURE_ORIGINAL_VALUES_KEY,
    FIXTURE_VALIDATION_KEY,
    FIXTURE_VALUE_KEYS,
    UI_FIELDS,
    UiField,
)
from app.utils.validation_view import IssueView, ValidationView, present_issues


@dataclass(frozen=True)
class FieldPart:
    """欄位中的一個值；original 只在與目前值不同時才有內容。"""

    label: str | None
    value: str
    original: str | None


@dataclass(frozen=True)
class FieldSection:
    """scalar／composite 欄位的畫面區塊。"""

    field: UiField
    parts: tuple[FieldPart, ...]
    issues: tuple[IssueView, ...]
    kind: str = "field"


@dataclass(frozen=True)
class ItemColumn:
    """明細表的一欄（對應一類業務欄位）與其 issue。"""

    field: UiField
    issues: tuple[IssueView, ...]


@dataclass(frozen=True)
class ItemsSection:
    """明細表區塊；rows 的每一列為一筆明細，cell 順序與 columns 相同。"""

    columns: tuple[ItemColumn, ...]
    rows: tuple[tuple[str, ...], ...]
    kind: str = "items"


@dataclass(frozen=True)
class ConfirmationView:
    """發票確認畫面的完整 view model。"""

    sections: tuple[FieldSection | ItemsSection, ...]
    validation: ValidationView
    checked_at: str
    rule_version: str

    @property
    def submit_control_enabled(self) -> bool:
        """「提交」控制在畫面上是否可按；僅 error 會使其 disabled。"""
        return not self.validation.has_blocking_error


def _text(value: Any) -> str:
    """畫面顯示用文字；空值顯示為「-」。"""
    return "-" if value is None or value == "" else str(value)


def _field_parts(
    field_id: str, invoice: Mapping[str, Any], originals: Mapping[str, Any]
) -> tuple[FieldPart, ...]:
    """取得非明細欄位的各個值，並在原值不同時一併帶出。"""
    parts = []
    for label, key in FIXTURE_VALUE_KEYS[field_id]:
        value = _text(invoice.get(key))
        original = originals.get(key)
        shown_original = (
            _text(original) if original is not None and _text(original) != value else None
        )
        parts.append(FieldPart(label, value, shown_original))
    return tuple(parts)


def _items_rows(
    invoice: Mapping[str, Any], item_field_ids: list[str]
) -> tuple[tuple[str, ...], ...]:
    """將明細清單轉為列；非 list 或非 dict 的內容忽略，不拋錯。"""
    items = invoice.get(FIXTURE_ITEMS_KEY)
    if not isinstance(items, list):
        return ()
    return tuple(
        tuple(_text(item.get(FIXTURE_ITEM_KEYS[field_id])) for field_id in item_field_ids)
        for item in items
        if isinstance(item, Mapping)
    )


def build_confirmation_view(invoice: Mapping[str, Any]) -> ConfirmationView:
    """由 mock／暫定格式的發票資料組成確認畫面。

    Args:
        invoice: 發票資料；欄位 key 見 invoice_fields.py 的 FIXTURE_*。

    Returns:
        ConfirmationView；sections 依 14 類欄位順序排列，明細欄位合併為一個表格區塊。
    """
    validation_raw = invoice.get(FIXTURE_VALIDATION_KEY)
    validation_raw = validation_raw if isinstance(validation_raw, Mapping) else {}
    validation = present_issues(validation_raw.get("issues"), FIXTURE_ISSUE_FIELD_TO_UI)
    originals = invoice.get(FIXTURE_ORIGINAL_VALUES_KEY)
    originals = originals if isinstance(originals, Mapping) else {}

    item_fields = [field for field in UI_FIELDS if field.kind == "items"]
    sections: list[FieldSection | ItemsSection] = []
    items_placed = False
    for field in UI_FIELDS:
        if field.kind == "items":
            if items_placed:
                continue
            items_placed = True
            sections.append(
                ItemsSection(
                    columns=tuple(
                        ItemColumn(f, validation.issues_by_field.get(f.field_id, ()))
                        for f in item_fields
                    ),
                    rows=_items_rows(invoice, [f.field_id for f in item_fields]),
                )
            )
        else:
            sections.append(
                FieldSection(
                    field=field,
                    parts=_field_parts(field.field_id, invoice, originals),
                    issues=validation.issues_by_field.get(field.field_id, ()),
                )
            )
    return ConfirmationView(
        sections=tuple(sections),
        validation=validation,
        checked_at=_text(validation_raw.get("checked_at")),
        rule_version=_text(validation_raw.get("rule_version")),
    )
