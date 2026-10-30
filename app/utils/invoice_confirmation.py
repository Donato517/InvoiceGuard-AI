"""
模組名稱：app.utils.invoice_confirmation
功能說明：組合發票確認畫面的 view model——14 類欄位（含多筆明細）、各欄位的 issue、提交控制的畫面狀態。
相依模組：app.utils.invoice_fields、app.utils.validation_view
注意事項：
    - 輸入是 mock／暫定格式的 dict，讀取用的 key 全部集中在 invoice_fields.py 的 FIXTURE_*。
    - submit_control_enabled 只是畫面呈現條件，不代表案件已送審或核准，也不是 workflow 狀態。
    - original／current 並列只是畫面展示，不代表 AI 原值已被持久化保存。
    - AI 原值以 field_changes.compare_to_original 分類：一致／不同／原值為空／快照沒有該欄位／
      整份快照不存在／型別不支援；後四者都不會被當成「未修改」。這只是畫面差異，不是修改歷程。
    - 檢核資料可為 fixture 的 validation，或 API 的 validation_results（{"warnings": [...]}），
      先經 validation_adapter 轉接；issue 有明細序號（line_no）時掛在對應明細列，
      只有 field="items" 或序號對不到任何一列時顯示在明細整體區域，不猜測是哪一列。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.utils.field_changes import compare_to_original
from app.utils.invoice_fields import (
    FIXTURE_ISSUE_FIELD_TO_UI,
    FIXTURE_ITEM_KEYS,
    FIXTURE_ITEMS_KEY,
    FIXTURE_ORIGINAL_VALUES_KEY,
    FIXTURE_VALIDATION_KEY,
    FIXTURE_VALUE_KEYS,
    ITEMS_OVERALL_ID,
    UI_FIELDS,
    UiField,
)
from app.utils.invoice_status import StatusView, round_label, status_view
from app.utils.validation_adapter import normalize_validation
from app.utils.validation_view import IssueView, ValidationView, present_issues


@dataclass(frozen=True)
class FieldPart:
    """欄位中的一個值；original 只在與目前值不同時才有內容。"""

    label: str | None
    value: str
    original: str | None
    status: str = "no_snapshot"


@dataclass(frozen=True)
class ItemRowOriginal:
    """一列明細與 AI 原值的比對：status 為 unchanged／modified／modified_reference（明細筆數與 AI 不同，位置比對不可靠）／added（AI 沒有此列）／partial
    （部分儲存格沒有 AI 原值）或 field_missing／original_null／no_snapshot／not_comparable；
    note 只在 modified 時列出各儲存格的「原值 → 目前值」。"""

    status: str
    note: str = ""


@dataclass(frozen=True)
class InvoiceHeaderView:
    """詳情頁表頭：UUID、簽核狀態、提交輪次（唯讀；來源沒給就顯示「-」，不推算）。"""

    invoice_id: str = "-"
    status: StatusView = StatusView(None, "-", False)
    submission_round: str = "-"


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
    """明細表區塊；rows 的每一列為一筆明細，cell 順序與 columns 相同。

    row_issues 與 rows 等長，第 i 項是對應第 i 列（line_no = i + 1）的 issue；
    overall_issues 是 field="items" 的 issue，顯示在整個明細區域。
    columns 內的 issues 只含沒有明細序號（或序號對不到列）的欄位 issue。
    """

    columns: tuple[ItemColumn, ...]
    rows: tuple[tuple[str, ...], ...]
    row_issues: tuple[tuple[IssueView, ...], ...] = ()
    overall_issues: tuple[IssueView, ...] = ()
    row_originals: tuple[ItemRowOriginal, ...] = ()
    removed_original_rows: int = 0
    row_count_mismatch: bool = False
    row_compare_limited: bool = False
    kind: str = "items"


@dataclass(frozen=True)
class ConfirmationView:
    """發票確認畫面的完整 view model。"""

    sections: tuple[FieldSection | ItemsSection, ...]
    validation: ValidationView
    checked_at: str
    rule_version: str
    header: InvoiceHeaderView = InvoiceHeaderView()
    has_ai_snapshot: bool = False

    @property
    def submit_control_enabled(self) -> bool:
        """「提交」控制在畫面上是否可按；僅 error 會使其 disabled。"""
        return not self.validation.has_blocking_error


def _text(value: Any) -> str:
    """畫面顯示用文字；空值顯示為「-」。"""
    return "-" if value is None or value == "" else str(value)


def _field_parts(
    field_id: str, invoice: Mapping[str, Any], originals: Mapping[str, Any] | None
) -> tuple[FieldPart, ...]:
    """取得非明細欄位的各個值，並依 AI 原值分類；只有「不同」時才帶出原值。"""
    parts = []
    for label, key in FIXTURE_VALUE_KEYS[field_id]:
        value = invoice.get(key)
        comparison = compare_to_original(originals, key, value)
        shown_original = _text(comparison.original) if comparison.status == "modified" else None
        parts.append(FieldPart(label, _text(value), shown_original, comparison.status))
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


def _item_mappings(invoice: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """目前明細中的 Mapping 列（與 _items_rows 相同的過濾規則）。"""
    items = invoice.get(FIXTURE_ITEMS_KEY)
    return [item for item in items if isinstance(item, Mapping)] if isinstance(items, list) else []


def _row_originals(
    invoice: Mapping[str, Any], originals: Mapping[str, Any] | None, item_field_ids: list[str]
) -> tuple[tuple[ItemRowOriginal, ...], int, bool]:
    """逐列比對明細與 AI 原值（依位置）；回傳 (各列比對結果, AI 有但目前沒有的列數, 筆數是否不同)。

    筆數不同時，刪除或插入會讓位置位移，同位置的差異不能當成確定的修改：「modified」降級為
    「modified_reference」（僅供參考）。筆數相同也沒有列識別資訊，無法證明沒有被重新排序。
    """
    current_rows = _item_mappings(invoice)
    snapshot_status = None
    if not isinstance(originals, Mapping):
        snapshot_status = "no_snapshot"
    elif FIXTURE_ITEMS_KEY not in originals:
        snapshot_status = "field_missing"
    elif originals[FIXTURE_ITEMS_KEY] is None:
        snapshot_status = "original_null"
    elif not isinstance(originals[FIXTURE_ITEMS_KEY], list):
        snapshot_status = "not_comparable"
    if snapshot_status is not None:
        return tuple(ItemRowOriginal(snapshot_status) for _ in current_rows), 0, False

    original_rows = originals[FIXTURE_ITEMS_KEY]
    labels = {f.field_id: f.label for f in UI_FIELDS}
    mismatch = len(original_rows) != len(current_rows)
    results: list[ItemRowOriginal] = []
    for index, row in enumerate(current_rows):
        if index >= len(original_rows):
            results.append(ItemRowOriginal("added"))
            continue
        original_row = original_rows[index]
        original_row = original_row if isinstance(original_row, Mapping) else None
        comparisons = [
            (
                field_id,
                compare_to_original(
                    original_row, FIXTURE_ITEM_KEYS[field_id], row.get(FIXTURE_ITEM_KEYS[field_id])
                ),
            )
            for field_id in item_field_ids
        ]
        statuses = {c.status for _, c in comparisons}
        if "modified" in statuses:
            note = "；".join(
                f"{labels[field_id]}：{_text(c.original)} → {_text(c.current)}"
                for field_id, c in comparisons
                if c.status == "modified"
            )
            results.append(ItemRowOriginal("modified_reference" if mismatch else "modified", note))
        elif "not_comparable" in statuses:
            results.append(ItemRowOriginal("not_comparable"))
        elif statuses == {"unchanged"}:
            results.append(ItemRowOriginal("unchanged"))
        else:
            results.append(ItemRowOriginal("partial"))
    return tuple(results), max(0, len(original_rows) - len(current_rows)), mismatch


def _locate_item_issues(
    validation: ValidationView, item_field_ids: list[str], row_count: int
) -> tuple[dict[str, tuple[IssueView, ...]], tuple[tuple[IssueView, ...], ...]]:
    """將明細欄位的 issue 分成「對應某一列」與「留在欄位／整體區域」兩類。

    Returns:
        (各明細欄位剩餘的 issue, 各列的 issue)。issue 的順序維持原順序，沒有任何 issue 被丟棄。
    """
    by_row: list[list[IssueView]] = [[] for _ in range(row_count)]
    remaining: dict[str, tuple[IssueView, ...]] = {}
    for field_id in [*item_field_ids, ITEMS_OVERALL_ID]:
        kept = []
        for issue in validation.issues_by_field.get(field_id, ()):
            if issue.line_no is not None and issue.line_no <= row_count:
                by_row[issue.line_no - 1].append(issue)
            else:
                kept.append(issue)
        remaining[field_id] = tuple(kept)
    return remaining, tuple(tuple(row) for row in by_row)


def build_confirmation_view(invoice: Mapping[str, Any]) -> ConfirmationView:
    """由 mock／暫定格式的發票資料組成確認畫面。

    Args:
        invoice: 發票資料；欄位 key 見 invoice_fields.py 的 FIXTURE_*。

    Returns:
        ConfirmationView；sections 依 14 類欄位順序排列，明細欄位合併為一個表格區塊。
    """
    validation_raw = normalize_validation(
        invoice.get(FIXTURE_VALIDATION_KEY) or invoice.get("validation_results")
    )
    validation = present_issues(validation_raw["issues"], FIXTURE_ISSUE_FIELD_TO_UI)
    originals = invoice.get(FIXTURE_ORIGINAL_VALUES_KEY)
    originals = originals if isinstance(originals, Mapping) else None

    item_fields = [field for field in UI_FIELDS if field.kind == "items"]
    item_field_ids = [f.field_id for f in item_fields]
    rows = _items_rows(invoice, item_field_ids)
    remaining, row_issues = _locate_item_issues(validation, item_field_ids, len(rows))
    row_originals, removed_rows, count_mismatch = _row_originals(invoice, originals, item_field_ids)
    sections: list[FieldSection | ItemsSection] = []
    items_placed = False
    for field in UI_FIELDS:
        if field.kind == "items":
            if items_placed:
                continue
            items_placed = True
            sections.append(
                ItemsSection(
                    columns=tuple(ItemColumn(f, remaining[f.field_id]) for f in item_fields),
                    rows=rows,
                    row_issues=row_issues,
                    overall_issues=remaining[ITEMS_OVERALL_ID],
                    row_originals=row_originals,
                    removed_original_rows=removed_rows,
                    row_count_mismatch=count_mismatch,
                    row_compare_limited=bool(row_originals)
                    and row_originals[0].status
                    not in ("no_snapshot", "field_missing", "original_null", "not_comparable"),
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
        header=InvoiceHeaderView(
            invoice_id=_text(invoice.get("invoice_id")),
            status=status_view(invoice.get("status")),
            submission_round=round_label(invoice.get("submission_round")),
        ),
        has_ai_snapshot=originals is not None,
    )
