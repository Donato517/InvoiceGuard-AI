"""
模組名稱：app.utils.field_changes
功能說明：比較兩份完整的發票資料快照（AI 原始值與人工修改後的值），找出有變動的欄位與明細列。
相依模組：app.utils.invoice_fields
注意事項：
    - 純函式，只讀取輸入，不修改、不連網路、不呼叫 API、不保存任何資料。
    - 輸入是 mock／暫定格式的 dict，讀取用的 key 全部集中在 invoice_fields.py 的 FIXTURE_*；
      結果中的 field_id（F01～F14）只是前台畫面識別碼，不是 API／AI／validation 的正式 key。
    - 結果只是兩份快照的「最終狀態差異」：不是正式修改歷程，不保證記錄每一次編輯
      （改了又改回原值不會留下紀錄），也不代表使用者已確認或案件已送審。
    - 結果刻意不提供 to_dict／序列化方法，避免被當成儲存或傳輸格式。
    - 快照須「結構完整」：必要結構 key 缺少時拋出 IncompleteSnapshotError，不視為空值。
      這是資料結構檢查，不是發票業務必填規則；key 存在而值為 None 視為空值。
    - 明細列依「位置」比對，沒有穩定的列 ID：交換兩列會被報告為兩列都修改，
      刪除中間一列會讓後面各列顯示為修改、最後一列顯示為移除。不做相似度配對或推測列身分。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from app.utils.invoice_fields import (
    FIXTURE_ITEM_KEYS,
    FIXTURE_ITEMS_KEY,
    FIXTURE_VALUE_KEYS,
    UI_FIELDS,
)

# 支援的值型別：None、str、int、Decimal（bool 與 float 一律不支援，避免靜默誤判）
ChangeValue = str | int | Decimal | None
ChangeKind = Literal["filled", "cleared", "modified"]
RowStatus = Literal["modified", "added", "removed"]

# 明細欄位的 UI field_id（依畫面順序）與其在每一列中必須存在的 key
_ITEM_FIELD_IDS: tuple[str, ...] = tuple(f.field_id for f in UI_FIELDS if f.kind == "items")
_ITEM_ROW_KEYS: tuple[str, ...] = tuple(FIXTURE_ITEM_KEYS[field_id] for field_id in _ITEM_FIELD_IDS)
# 快照頂層必須存在的結構 key：所有非明細欄位的 key，加上明細清單的 key
_SNAPSHOT_KEYS: tuple[str, ...] = (
    *(key for parts in FIXTURE_VALUE_KEYS.values() for _, key in parts),
    FIXTURE_ITEMS_KEY,
)


class IncompleteSnapshotError(ValueError):
    """快照缺少必要結構 key（資料結構不完整，不是業務必填欄位）。

    Attributes:
        snapshot: 出問題的快照名稱（"original" 或 "current"）。
        missing_keys: 缺少的 key。
        row_index: 缺少的是明細列內的 key 時，該列的位置（從 0 起算）；頂層缺少時為 None。
    """

    def __init__(
        self, snapshot: str, missing_keys: tuple[str, ...], row_index: int | None = None
    ) -> None:
        """
        Args:
            snapshot: 快照名稱。
            missing_keys: 缺少的 key。
            row_index: 明細列位置（從 0 起算）；頂層缺少時為 None。
        """
        location = (
            snapshot if row_index is None else f"{snapshot} 的明細第 {row_index} 列（從 0 起算）"
        )
        super().__init__(f"{location} 缺少必要結構 key：{', '.join(missing_keys)}")
        self.snapshot = snapshot
        self.missing_keys = missing_keys
        self.row_index = row_index


@dataclass(frozen=True)
class ValueChange:
    """單一值的差異；original／current 保留呼叫端傳入的原始值（不去空白、不轉型別）。

    Attributes:
        field_id: 前台 UI 識別碼（F01～F14），非正式 API key。
        label: 複合欄位的子項標籤（例如 F11 的「稅額」）；單值與明細欄位為 None。
        original: 原始快照中的值；新增列的儲存格為 None。
        current: 目前快照中的值；被移除列的儲存格為 None。
    """

    field_id: str
    label: str | None
    original: ChangeValue
    current: ChangeValue

    @property
    def kind(self) -> ChangeKind:
        """變動種類：filled＝空值變有值、cleared＝有值變空值、modified＝有值變成另一個值。"""
        if _comparable(self.original, "original") is None:
            return "filled"
        if _comparable(self.current, "current") is None:
            return "cleared"
        return "modified"


@dataclass(frozen=True)
class ItemRowChange:
    """一列明細的差異（依位置比對）。

    Attributes:
        row_index: 列的位置（從 0 起算）；不是穩定的列 ID。
        status: modified＝兩邊都有此列且有儲存格不同；added＝只在目前快照有；
            removed＝只在原始快照有。added／removed 即使整列空白也屬列結構變更。
        changes: 有差異的儲存格（依 F06～F09 順序）。added 只列出非空的儲存格，
            removed 只列出原本非空的儲存格；整列空白時為空 tuple。
    """

    row_index: int
    status: RowStatus
    changes: tuple[ValueChange, ...]


@dataclass(frozen=True)
class FieldChangeSet:
    """兩份快照的差異結果；僅供前台畫面使用，不是儲存格式。

    Attributes:
        field_changes: 非明細欄位的差異，依畫面欄位順序，複合欄位只含有變動的子項。
        item_changes: 明細列的差異，依列位置排序。
    """

    field_changes: tuple[ValueChange, ...] = ()
    item_changes: tuple[ItemRowChange, ...] = ()

    @property
    def has_changes(self) -> bool:
        """是否有任何差異（含明細列的新增／移除等結構變更）。"""
        return bool(self.field_changes or self.item_changes)

    @property
    def changed_field_ids(self) -> tuple[str, ...]:
        """有變動的 UI field_id（依畫面順序）。

        modified 列只標記有差異的明細類別；added／removed 屬列結構變更，標記全部明細類別。
        """
        ids = {change.field_id for change in self.field_changes}
        for row in self.item_changes:
            if row.status == "modified":
                ids.update(change.field_id for change in row.changes)
            else:
                ids.update(_ITEM_FIELD_IDS)
        return tuple(field.field_id for field in UI_FIELDS if field.field_id in ids)


def _comparable(value: Any, where: str) -> str | None:
    """取得比較用文字；None 與空白字串都視為空值（回傳 None）。

    Args:
        value: 待比較的值，僅支援 None、str、int、Decimal。
        where: 值的位置描述，用於錯誤訊息。

    Returns:
        去除前後空白的文字（int／Decimal 以 str() 轉換，不做數值正規化）；空值為 None。

    Raises:
        TypeError: 值的型別不在支援範圍（bool、float、list 等）。
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, str | int | Decimal):
        raise TypeError(
            f"{where} 的值型別不支援：{type(value).__name__}（僅支援 None、str、int、Decimal）"
        )
    text = value.strip() if isinstance(value, str) else str(value)
    return text or None


def _validated_rows(snapshot: Any, name: str) -> tuple[Mapping[str, Any], ...]:
    """檢查快照的資料結構並取出明細列。

    Raises:
        TypeError: 快照不是 Mapping、明細不是 list，或明細列不是 Mapping。
        IncompleteSnapshotError: 缺少必要結構 key（頂層或明細列內）。
    """
    if not isinstance(snapshot, Mapping):
        raise TypeError(f"{name} 須為 Mapping，收到 {type(snapshot).__name__}")
    missing = tuple(key for key in _SNAPSHOT_KEYS if key not in snapshot)
    if missing:
        raise IncompleteSnapshotError(name, missing)
    items = snapshot[FIXTURE_ITEMS_KEY]
    if items is None:
        return ()
    if not isinstance(items, list):
        raise TypeError(f"{name} 的明細須為 list 或 None，收到 {type(items).__name__}")
    rows: list[Mapping[str, Any]] = []
    for index, row in enumerate(items):
        if not isinstance(row, Mapping):
            raise TypeError(f"{name} 的明細第 {index} 列須為 Mapping，收到 {type(row).__name__}")
        missing_cells = tuple(key for key in _ITEM_ROW_KEYS if key not in row)
        if missing_cells:
            raise IncompleteSnapshotError(name, missing_cells, index)
        rows.append(row)
    return tuple(rows)


def _diff(
    field_id: str, label: str | None, original: Any, current: Any, where: str
) -> ValueChange | None:
    """比較單一值；比較用文字相同時回傳 None，否則回傳保留原始輸入值的 ValueChange。"""
    if _comparable(original, f"original.{where}") == _comparable(current, f"current.{where}"):
        return None
    return ValueChange(field_id, label, original, current)


def _row_changes(
    original_row: Mapping[str, Any] | None, current_row: Mapping[str, Any] | None, index: int
) -> tuple[ValueChange, ...]:
    """比較一列明細；其中一邊為 None 代表該邊沒有此列（各儲存格以空值計）。"""
    changes = []
    for field_id in _ITEM_FIELD_IDS:
        key = FIXTURE_ITEM_KEYS[field_id]
        before = None if original_row is None else original_row[key]
        after = None if current_row is None else current_row[key]
        change = _diff(field_id, None, before, after, f"items[{index}].{key}")
        if change is not None:
            changes.append(change)
    return tuple(changes)


def detect_field_changes(original: Mapping[str, Any], current: Mapping[str, Any]) -> FieldChangeSet:
    """比較 AI 原始快照與人工修改後的快照，找出有變動的欄位與明細列。

    比較規則（簡化政策）：值轉成文字後去除前後空白再比較；None 與空白字串視為空值；
    int／Decimal 以 str() 轉文字，不做金額正規化（"100" 與 "100.00" 視為不同）。
    差異結果保留呼叫端傳入的原始值，不保存正規化後的字串。支援的值型別僅 None、str、int、
    Decimal；bool、float、list、dict 等一律拋出 TypeError，即使該位置沒有差異也一樣。
    明細列依位置比對（見模組說明的重新排序限制）。快照中的額外 key（例如 validation）會被忽略。

    Args:
        original: AI 原始值的完整快照。
        current: 人工修改後的完整快照；須與 original 具有相同的結構 key。

    Returns:
        FieldChangeSet；沒有差異時 has_changes 為 False。

    Raises:
        TypeError: 快照不是 Mapping、明細不是 list、明細列不是 Mapping，或值型別不支援。
        IncompleteSnapshotError: 任一快照缺少必要結構 key。
    """
    original_rows = _validated_rows(original, "original")
    current_rows = _validated_rows(current, "current")

    field_changes: list[ValueChange] = []
    for field in UI_FIELDS:
        if field.kind == "items":
            continue
        for label, key in FIXTURE_VALUE_KEYS[field.field_id]:
            change = _diff(field.field_id, label, original[key], current[key], key)
            if change is not None:
                field_changes.append(change)

    item_changes: list[ItemRowChange] = []
    for index in range(max(len(original_rows), len(current_rows))):
        before = original_rows[index] if index < len(original_rows) else None
        after = current_rows[index] if index < len(current_rows) else None
        changes = _row_changes(before, after, index)
        if before is None:
            item_changes.append(ItemRowChange(index, "added", changes))
        elif after is None:
            item_changes.append(ItemRowChange(index, "removed", changes))
        elif changes:
            item_changes.append(ItemRowChange(index, "modified", changes))

    return FieldChangeSet(tuple(field_changes), tuple(item_changes))
