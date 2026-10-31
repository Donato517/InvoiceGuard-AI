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
    - API 詳情（經 invoice_detail_adapter）沒有 AI 原始快照，只有「被改過的欄位」紀錄（輸入的 modifications）：
      不走 original_values 比對（has_ai_snapshot 維持 False），改由 modifications 產生欄位備註、明細列備註、
      已刪除的 AI 明細與其他修改紀錄；明細備註只依真實 line_no 唯一對應，對不到或有重複時列入「無法對應」，
      不退回位置猜測。沒有紀錄的欄位不輸出任何狀態標籤，不代表未修改。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.utils.field_changes import compare_to_original
from app.utils.invoice_fields import (
    DETAIL_EXTRA_VALUE_KEYS,
    FIXTURE_ISSUE_FIELD_TO_UI,
    FIXTURE_ITEM_KEYS,
    FIXTURE_ITEMS_KEY,
    FIXTURE_ORIGINAL_VALUES_KEY,
    FIXTURE_VALIDATION_KEY,
    FIXTURE_VALUE_KEYS,
    ITEMS_OVERALL_ID,
    MODIFIED_HEADER_FIELD_TO_UI,
    MODIFIED_ITEM_FIELD_TO_UI,
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
class ModificationNote:
    """一筆 AI 原值備註（來自 API 的 modified_fields 紀錄）；original 已是安全的純文字。"""

    label: str | None
    original: str


@dataclass(frozen=True)
class DeletedAiItem:
    """送出時被刪除的 AI 明細；ai_line_no 是 AI 辨識順序，與目前明細的序號無關。"""

    ai_line_no: int
    cells: tuple[tuple[str, str], ...]
    omitted_extra: bool = False


@dataclass(frozen=True)
class UnmatchedItemNote:
    """對不到唯一一列明細的修改紀錄；不掛在任何一列。"""

    line_no: int
    label: str
    original: str
    reason: str


@dataclass(frozen=True)
class OtherModification:
    """無法歸入已知欄位的修改紀錄，原樣（純文字）顯示，不丟棄。"""

    scope: str | None
    name: str | None
    line_no: int | None
    original: str
    submitted: str | None


@dataclass(frozen=True)
class ModificationsView:
    """API 修改紀錄的畫面資料；total 是紀錄總數（只涵蓋本輪有修改紀錄的欄位，不是完整 AI 快照）。"""

    total: int
    deleted_items: tuple[DeletedAiItem, ...] = ()
    unmatched_items: tuple[UnmatchedItemNote, ...] = ()
    other: tuple[OtherModification, ...] = ()


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
    modifications: tuple[ModificationNote, ...] = ()
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
    row_line_nos: tuple[int | None, ...] = ()
    row_modifications: tuple[tuple[ModificationNote, ...], ...] = ()
    modification_mode: bool = False
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
    modifications: ModificationsView | None = None

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
    # 只供詳情顯示的附加子項（例如賣方統編）：來源真的有此 key 才顯示，不參與 AI 原值比對
    for label, key in DETAIL_EXTRA_VALUE_KEYS.get(field_id, ()):
        if key in invoice:
            parts.append(FieldPart(label, _text(invoice.get(key)), None))
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


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _row_line_nos(invoice: Mapping[str, Any]) -> tuple[int | None, ...]:
    """每一列明細自己的真實 line_no（與 _items_rows 相同的過濾規則，所以與列一一對應）。"""
    return tuple(
        item.get("line_no") if _is_int(item.get("line_no")) else None
        for item in _item_mappings(invoice)
    )


def _entries(group: Any) -> list[Any]:
    return list(group) if isinstance(group, list | tuple) else []


def _build_modifications(
    raw: Any, row_line_nos: tuple[int | None, ...]
) -> tuple[
    ModificationsView | None,
    dict[str, tuple[ModificationNote, ...]],
    tuple[tuple[ModificationNote, ...], ...],
]:
    """把轉接後的修改紀錄分配到欄位、明細列與獨立區塊；每一筆都有去處，不靜默丟棄。

    Returns:
        (ModificationsView 或 None（輸入沒有 modifications，例如 fixture）, UI field_id → 欄位備註,
        各明細列的備註（與列一一對應）)。明細紀錄只在恰有一列擁有該 line_no 時才掛上去。
    """
    if not isinstance(raw, Mapping):
        return None, {}, ()
    labels = {f.field_id: f.label for f in UI_FIELDS}
    field_notes: dict[str, list[ModificationNote]] = {}
    row_notes: list[list[ModificationNote]] = [[] for _ in row_line_nos]
    unmatched: list[UnmatchedItemNote] = []
    other: list[OtherModification] = []
    deleted: list[DeletedAiItem] = []

    def _other_from(entry: Any) -> None:
        if isinstance(entry, Mapping):
            line_no = entry.get("line_no")
            other.append(
                OtherModification(
                    scope=entry.get("scope") if isinstance(entry.get("scope"), str) else None,
                    name=entry.get("name") if isinstance(entry.get("name"), str) else None,
                    line_no=line_no if _is_int(line_no) else None,
                    original=_text(entry.get("original")),
                    submitted=entry.get("submitted")
                    if isinstance(entry.get("submitted"), str)
                    else None,
                )
            )
        else:
            other.append(OtherModification(None, None, None, "（無法解析的紀錄）", None))

    for entry in _entries(raw.get("header")):
        name = entry.get("name") if isinstance(entry, Mapping) else None
        target = MODIFIED_HEADER_FIELD_TO_UI.get(name) if isinstance(name, str) else None
        if target is None:
            _other_from(entry)
            continue
        field_id, label = target
        field_notes.setdefault(field_id, []).append(
            ModificationNote(label, _text(entry.get("original")))
        )

    for entry in _entries(raw.get("items")):
        name = entry.get("name") if isinstance(entry, Mapping) else None
        line_no = entry.get("line_no") if isinstance(entry, Mapping) else None
        field_id = MODIFIED_ITEM_FIELD_TO_UI.get(name) if isinstance(name, str) else None
        if field_id is None or not _is_int(line_no):
            _other_from(entry)
            continue
        label, original = labels[field_id], _text(entry.get("original"))
        rows = [i for i, number in enumerate(row_line_nos) if number == line_no]
        if len(rows) == 1:
            row_notes[rows[0]].append(ModificationNote(label, original))
        else:
            reason = "目前明細中找不到這個序號" if not rows else "有多筆明細使用同一個序號"
            unmatched.append(UnmatchedItemNote(line_no, label, original, reason))

    for entry in _entries(raw.get("deleted")):
        ai_line_no = entry.get("ai_line_no") if isinstance(entry, Mapping) else None
        if not _is_int(ai_line_no):
            _other_from(entry)
            continue
        cells = tuple(
            (labels[MODIFIED_ITEM_FIELD_TO_UI[name]], _text(text))
            for name, text in (
                c
                for c in _entries(entry.get("cells"))
                if isinstance(c, list | tuple) and len(c) == 2
            )
            if name in MODIFIED_ITEM_FIELD_TO_UI
        )
        deleted.append(DeletedAiItem(ai_line_no, cells, bool(entry.get("omitted_extra"))))

    for entry in _entries(raw.get("other")):
        _other_from(entry)

    total = raw.get("total")
    view = ModificationsView(
        total=total if _is_int(total) else 0,
        deleted_items=tuple(deleted),
        unmatched_items=tuple(unmatched),
        other=tuple(other),
    )
    return (
        view,
        {key: tuple(value) for key, value in field_notes.items()},
        tuple(tuple(value) for value in row_notes),
    )


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
    row_line_nos = _row_line_nos(invoice)
    modifications, field_notes, row_notes = _build_modifications(
        invoice.get("modifications"), row_line_nos
    )
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
                    row_line_nos=row_line_nos,
                    row_modifications=row_notes,
                    modification_mode=modifications is not None,
                )
            )
        else:
            sections.append(
                FieldSection(
                    field=field,
                    parts=_field_parts(field.field_id, invoice, originals),
                    issues=validation.issues_by_field.get(field.field_id, ()),
                    modifications=field_notes.get(field.field_id, ()),
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
        modifications=modifications,
    )
