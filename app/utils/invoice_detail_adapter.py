"""
模組名稱：app.utils.invoice_detail_adapter
功能說明：把 API 的發票詳情（GET /invoices/{id}，Stage 1）轉成 invoice_confirmation.build_confirmation_view 的輸入格式，
    並把 modified_fields 整理成安全可顯示的修改紀錄。
相依模組：app.utils.invoice_fields
注意事項：
    - 純函式：不修改輸入、不連網路、不讀取 demo／fixture 資料，輸出全部是新建的結構。
    - API 沒有的資料不補：不輸出 original_values（後端不提供 AI 原始快照，modified_fields 只含被改過的欄位，
      不能當成完整快照）、form_type、remark。
    - 修改紀錄的值是後端的標準值（例如金額 "1000"，與詳情欄位 "1000.00" 格式不同），這裡完全不比較兩者，
      「已修改」只由紀錄本身決定，所以尾端 0 不會產生假差異。
    - 每一筆 modified_fields 必定歸入 header／items／deleted／other 其中一類（total 等於各類加總），不靜默丟棄；
      無法完整顯示的值以明確標示取代（「（結構化值，已省略）」「（已截斷）」「（無法顯示）」）。
    - 唯一會拋出例外的情況：輸入根本不可能是發票詳情（不是物件、沒有 invoice_id、items 不是 list），
      由呼叫端轉成 502，避免畫面顯示成「正常的空案件」。其他型別異常只降級為「-」或明確標示。
    - 課稅別代碼對照來自後端 TaxType（InvoiceGuard-AI-API app/schemas/invoice_upload.py）；後端新增代碼時需同步。
"""

import re
from collections.abc import Mapping
from typing import Any

from app.utils.invoice_fields import MODIFIED_HEADER_FIELD_TO_UI, MODIFIED_ITEM_FIELD_TO_UI

# 後端課稅別代碼 → 畫面文字；不認得的代碼原樣顯示，不猜測
TAX_TYPE_LABEL: dict[str, str] = {
    "taxable": "應稅",
    "zero_rated": "零稅率",
    "tax_exempt": "免稅",
}

# 修改紀錄單一文字值的顯示長度上限（超過截斷並標示）
MAX_DISPLAY_CHARS = 200
EMPTY_TEXT = "（空）"
STRUCTURED_TEXT = "（結構化值，已省略）"
UNDISPLAYABLE_TEXT = "（無法顯示）"
TRUNCATED_SUFFIX = "…（已截斷）"

# 已刪除的 AI 明細：欄位名稱順序（顯示用）
_DELETED_ITEM_FIELDS: tuple[str, ...] = ("item_name", "quantity", "unit_price", "line_amount")
# deleted_item_{AI 明細序號}：只接受 1～6 位 ASCII 數字，避免超長數字轉 int
_DELETED_ITEM_NAME = re.compile(r"deleted_item_([0-9]{1,6})", re.ASCII)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class InvoiceDetailFormatError(ValueError):
    """輸入不可能是發票詳情；呼叫端應轉成上游回應異常（502），不可顯示成空案件。"""


def _is_int(value: Any) -> bool:
    """整數（bool 是 int 的子類別，必須明確排除）。"""
    return isinstance(value, int) and not isinstance(value, bool)


def display_value(value: Any, *, field_name: str | None = None) -> str:
    """修改紀錄的單一值轉成純文字（畫面由樣板轉義輸出，不使用 safe）。

    Args:
        value: ai_original_value／submitted_value 的內容，可為任意 JSON 型別。
        field_name: 欄位名稱；為 tax_type 時把已知代碼轉成中文。

    Returns:
        None→「（空）」；字串原樣（去除控制字元，超過上限截斷並標示）；整數轉字串；布林為 true／false；
        巢狀物件／陣列為「（結構化值，已省略）」；其他型別（例如浮點數）為「（無法顯示）」。
    """
    if value is None:
        return EMPTY_TEXT
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        text = _CONTROL_CHARS.sub("", value)
        if not text.strip():
            return EMPTY_TEXT
        if field_name == "tax_type":
            text = TAX_TYPE_LABEL.get(text, text)
        if len(text) > MAX_DISPLAY_CHARS:
            return text[:MAX_DISPLAY_CHARS] + TRUNCATED_SUFFIX
        return text
    if isinstance(value, Mapping | list | tuple):
        return STRUCTURED_TEXT
    return UNDISPLAYABLE_TEXT


def _plain(value: Any) -> Any:
    """一般欄位：字串與整數原樣（含空字串，由畫面顯示為「-」）、None 保持 None；其他型別以明確標示取代。"""
    if value is None or isinstance(value, str):
        return value
    if _is_int(value):
        return value
    return display_value(value)


def _track_number(header: Mapping[str, Any]) -> str | None:
    """字軌（2 碼）＋號碼（8 碼）直接串接；任一邊缺少時不串成看似完整的字串。"""
    track, number = header.get("invoice_track"), header.get("invoice_number")
    if not (isinstance(track, str) and isinstance(number, str)):
        return None
    track, number = track.strip(), number.strip()
    return track + number if track and number else None


def _tax_type(value: Any) -> Any:
    if isinstance(value, str):
        return TAX_TYPE_LABEL.get(value, value)
    return _plain(value)


def _items(raw: Any) -> list[dict[str, Any]]:
    """明細：只保留 Mapping，line_amount 改名 amount，並保留真實 line_no 供修改紀錄對應。"""
    if not isinstance(raw, list | tuple):
        return []
    return [
        {
            "line_no": item.get("line_no") if _is_int(item.get("line_no")) else None,
            "item_name": _plain(item.get("item_name")),
            "quantity": _plain(item.get("quantity")),
            "unit_price": _plain(item.get("unit_price")),
            "amount": _plain(item.get("line_amount")),
        }
        for item in raw
        if isinstance(item, Mapping)
    ]


def _warnings(raw: Any) -> list[Any]:
    """warnings 只取契約內的 field／code／message；不產生 severity。非物件的項目轉成文字，不丟棄。"""
    if not isinstance(raw, list | tuple):
        return []
    return [
        {key: _plain(entry[key]) for key in ("field", "code", "message") if key in entry}
        if isinstance(entry, Mapping)
        else display_value(entry)
        for entry in raw
    ]


def _deleted_cells(value: Mapping[str, Any]) -> tuple[list[tuple[str, str]], bool]:
    """已刪除 AI 明細的欄位（白名單四欄）；回傳 (欄位名稱與顯示文字, 是否另有未知欄位被省略)。"""
    cells = [
        (name, display_value(value.get(name), field_name=name))
        for name in _DELETED_ITEM_FIELDS
        if name in value
    ]
    return cells, any(key not in _DELETED_ITEM_FIELDS for key in value)


def _modifications(raw: Any) -> dict[str, Any]:
    """整理 modified_fields；每一筆必定歸入 header／items／deleted／other 其中一類。

    Returns:
        {"total", "header": [{"name","original"}], "items": [{"line_no","name","original"}],
         "deleted": [{"ai_line_no","cells","omitted_extra"}], "other": [{"scope","name","line_no",
         "original","submitted"}]}；original／submitted 都是顯示用純文字。
    """
    result: dict[str, Any] = {"total": 0, "header": [], "items": [], "deleted": [], "other": []}
    if not isinstance(raw, list | tuple):
        return result
    for record in raw:
        result["total"] += 1
        if not isinstance(record, Mapping):
            result["other"].append(
                {
                    "scope": None,
                    "name": None,
                    "line_no": None,
                    "original": display_value(record),
                    "submitted": None,
                }
            )
            continue
        scope, name, line_no = (
            record.get("field_scope"),
            record.get("field_name"),
            record.get("line_no"),
        )
        original = record.get("ai_original_value")
        text_name = name if isinstance(name, str) else None
        deleted = _DELETED_ITEM_NAME.fullmatch(name) if text_name is not None else None
        if scope == "header" and line_no is None and text_name in MODIFIED_HEADER_FIELD_TO_UI:
            result["header"].append(
                {"name": name, "original": display_value(original, field_name=name)}
            )
        elif scope == "item" and _is_int(line_no) and text_name in MODIFIED_ITEM_FIELD_TO_UI:
            result["items"].append(
                {
                    "line_no": line_no,
                    "name": name,
                    "original": display_value(original, field_name=name),
                }
            )
        elif scope == "header" and line_no is None and deleted and isinstance(original, Mapping):
            cells, omitted_extra = _deleted_cells(original)
            result["deleted"].append(
                {
                    "ai_line_no": int(deleted.group(1)),
                    "cells": cells,
                    "omitted_extra": omitted_extra,
                }
            )
        else:
            result["other"].append(
                {
                    "scope": None if scope is None else display_value(scope),
                    "name": None if name is None else display_value(name),
                    "line_no": line_no if _is_int(line_no) else None,
                    "original": display_value(original, field_name=text_name),
                    "submitted": display_value(record.get("submitted_value"), field_name=text_name),
                }
            )
    return result


def adapt_invoice_detail(raw: Any) -> dict[str, Any]:
    """把 API 發票詳情轉成確認畫面的輸入。

    Args:
        raw: GET /invoices/{id} 的回應（已由 API Client 檢查形狀）；不會被修改。

    Returns:
        確認畫面的輸入：invoice_id、status、submission_round、track_number、invoice_date、buyer_*、seller_*、
        sales_amount、tax_type（中文）、tax_amount、total_amount、total_amount_zh、items（含 line_no，
        金額 key 為 amount）、validation_results（{"warnings": [...]}，無 severity）、modifications。
        不含 original_values、form_type、remark（API 沒有這些來源）。

    Raises:
        InvoiceDetailFormatError: 輸入不是物件、沒有字串 invoice_id，或 items 不是 list。
    """
    if not isinstance(raw, Mapping):
        raise InvoiceDetailFormatError("詳情不是物件")
    if not isinstance(raw.get("invoice_id"), str) or not raw["invoice_id"]:
        raise InvoiceDetailFormatError("詳情沒有 invoice_id")
    if not isinstance(raw.get("items"), list | tuple):
        raise InvoiceDetailFormatError("詳情的 items 不是 list")
    return {
        "invoice_id": raw["invoice_id"],
        "status": _plain(raw.get("status")),
        "submission_round": raw.get("submission_round")
        if _is_int(raw.get("submission_round"))
        else None,
        "track_number": _track_number(raw),
        "invoice_date": _plain(raw.get("invoice_date")),
        "buyer_name": _plain(raw.get("buyer_name")),
        "buyer_tax_id": _plain(raw.get("buyer_tax_id")),
        "seller_name": _plain(raw.get("seller_name")),
        "seller_tax_id": _plain(raw.get("seller_tax_id")),
        "items": _items(raw.get("items")),
        "sales_amount": _plain(raw.get("sales_amount")),
        "tax_type": _tax_type(raw.get("tax_type")),
        "tax_amount": _plain(raw.get("tax_amount")),
        "total_amount": _plain(raw.get("total_amount")),
        "total_amount_zh": _plain(raw.get("total_amount_zh")),
        "validation_results": {"warnings": _warnings(raw.get("warnings"))},
        "modifications": _modifications(raw.get("modified_fields")),
    }
