"""
模組名稱：app.utils.invoice_fields
功能說明：發票確認畫面的 14 類業務欄位 UI metadata，以及僅供前台畫面與測試使用的暫定 fixture key。
注意事項：
    - UiField.field_id（F01～F14）只是前台畫面的識別碼，不是 AI／API／validation 的正式 key。
    - 下方 FIXTURE_* 常數是 frontend-only 的暫定對照，用來讀取 mock 資料；
      A 組 AI JSON Schema 與 F 組 validation.field 定稿後，只需修改這一處。
    - 本檔不定義 API Contract，也不代表資料已持久化。
"""

from dataclasses import dataclass
from typing import Literal

FieldKind = Literal["scalar", "composite", "items"]


@dataclass(frozen=True)
class UiField:
    """畫面上的一類業務欄位。

    Attributes:
        field_id: 前台 UI 識別碼（F01～F14），非正式 API key。
        label: 中文顯示名稱。
        order: 顯示順序，從 1 開始。
        kind: scalar＝單一值；composite＝同一類含多個值；items＝明細表的一欄，可有多筆。
    """

    field_id: str
    label: str
    order: int
    kind: FieldKind


# 14 類業務欄位（依業務文件的順序）；F06～F09 為明細欄位，一張發票可有多筆
UI_FIELDS: tuple[UiField, ...] = (
    UiField("F01", "發票聯式／識別", 1, "scalar"),
    UiField("F02", "發票字軌號碼", 2, "scalar"),
    UiField("F03", "發票日期", 3, "scalar"),
    UiField("F04", "買受人名稱", 4, "scalar"),
    UiField("F05", "買受人統編", 5, "scalar"),
    UiField("F06", "品名／用途", 6, "items"),
    UiField("F07", "數量", 7, "items"),
    UiField("F08", "單價", 8, "items"),
    UiField("F09", "金額", 9, "items"),
    UiField("F10", "銷售額合計", 10, "scalar"),
    UiField("F11", "課稅別與稅額", 11, "composite"),
    UiField("F12", "總計／國字大寫", 12, "composite"),
    UiField("F13", "備註", 13, "scalar"),
    UiField("F14", "銷貨人", 14, "scalar"),
)

UI_FIELD_BY_ID: dict[str, UiField] = {field.field_id: field for field in UI_FIELDS}

# ---- frontend-only fixture key（暫定；不是正式 AI／API／validation key）----

# 明細清單在 mock 資料中的 key
FIXTURE_ITEMS_KEY = "items"
# validation 結果在 mock 資料中的 key
FIXTURE_VALIDATION_KEY = "validation"
# AI 原值（僅供畫面並列展示）在 mock 資料中的 key
FIXTURE_ORIGINAL_VALUES_KEY = "original_values"

# 非明細欄位：UI field_id → ((子項標籤, mock 資料 key), ...)；單值欄位的子項標籤為 None
FIXTURE_VALUE_KEYS: dict[str, tuple[tuple[str | None, str], ...]] = {
    "F01": ((None, "form_type"),),
    "F02": ((None, "track_number"),),
    "F03": ((None, "invoice_date"),),
    "F04": ((None, "buyer_name"),),
    "F05": ((None, "buyer_tax_id"),),
    "F10": ((None, "sales_amount"),),
    "F11": (("課稅別", "tax_type"), ("稅額", "tax_amount")),
    "F12": (("總計", "total_amount"), ("國字大寫", "total_amount_zh")),
    "F13": ((None, "remark"),),
    "F14": ((None, "seller_name"),),
}

# 明細欄位：UI field_id → 每筆明細 dict 內的 mock 資料 key
FIXTURE_ITEM_KEYS: dict[str, str] = {
    "F06": "item_name",
    "F07": "quantity",
    "F08": "unit_price",
    "F09": "amount",
}

# validation issue 的 field 值 → UI field_id；找不到的 issue 會保留為 general issue，不會被丟棄
FIXTURE_ISSUE_FIELD_TO_UI: dict[str, str] = {
    "form_type": "F01",
    "track_number": "F02",
    "invoice_date": "F03",
    "buyer_name": "F04",
    "buyer_tax_id": "F05",
    "item_name": "F06",
    "quantity": "F07",
    "unit_price": "F08",
    "amount": "F09",
    "sales_amount": "F10",
    "tax_type": "F11",
    "tax_amount": "F11",
    "total_amount": "F12",
    "total_amount_zh": "F12",
    "remark": "F13",
    "seller_name": "F14",
}
