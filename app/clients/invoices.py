"""
模組名稱：app.clients.invoices
功能說明：發票相關 API——手機上傳流程（辨識、必填檢核、查重、送出）、詳情、列表、上傳、重新分析。
    對應 API 路徑：/api/v1/invoices
注意事項：
    - 手機上傳流程與詳情（GET /invoices/{id}，Stage 1）已由 API 實作；列表（GET /invoices，只含本人提交）已由 API 實作；上傳與重新分析的 API 端點仍為 TODO。
    - fetch_invoices、fetch_invoice 會驗證列表與詳情回應的型別與巢狀形狀，不符一律 502，不把不合法的資料交給畫面。
"""

import json
import logging
from typing import Any
from uuid import UUID

from app.clients.base import ApiError, request_json

logger = logging.getLogger(__name__)

INVALID_UPSTREAM_RESPONSE_MESSAGE = "服務回應異常，請稍後再試"


async def recognize_invoice(
    token: str, *, filename: str, content: bytes, content_type: str
) -> dict[str, Any]:
    """辨識發票影像（POST /invoices/recognize）：API 存入 invoices bucket、OCR、AI 整理欄位。

    Returns:
        {"recognition_id", "result_status", "is_triplicate", "invoice": {...欄位與 items},
         "printed": {...}, "warnings": [...], "recognition": {...}, "expires_at"}

    Raises:
        ApiError: 影像不符（400）、Session 無效（401）、外部服務失敗（502）或服務無法使用（503）。
    """
    files = {"file": (filename, content, content_type)}
    return await request_json("POST", "/invoices/recognize", token=token, files=files)


async def check_duplicate(
    token: str, *, invoice_track: str, invoice_number: str, seller_tax_id: str
) -> dict[str, Any]:
    """查重（POST /invoices/check-duplicate）：字軌＋號碼＋賣方統編是否已存在（已作廢者不計）。

    Returns:
        {"is_duplicate": bool}
    """
    payload = {
        "invoice_track": invoice_track,
        "invoice_number": invoice_number,
        "seller_tax_id": seller_tax_id,
    }
    return await request_json("POST", "/invoices/check-duplicate", token=token, json=payload)


async def check_required_fields(token: str, payload: dict[str, Any]) -> dict[str, Any]:
    """必填欄位檢核（POST /invoices/check-required）：一次列出正式提交的所有必填缺漏，不寫入任何資料。

    Args:
        token: 使用者的 access token。
        payload: 核對頁目前的欄位值（欄位同 POST /invoices，可缺漏或空白）。

    Returns:
        {"required_complete": bool, "missing": [{"field", "code", "message", "line_no"}]}；
        required_complete 只代表沒有必填缺漏，不代表格式或金額正確，也不代表可以提交。

    Raises:
        ApiError: API 錯誤（401、4xx、5xx）、連線失敗（503），或 API 回 2xx 但本文不是合法 JSON／沒有本文時
            為 502 INVALID_UPSTREAM_RESPONSE（不含原始本文）；由全域處理器統一轉成 502 JSON。
    """
    try:
        result = await request_json("POST", "/invoices/check-required", token=token, json=payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("必填檢核的 API 回應不是合法 JSON（%s）", exc.__class__.__name__)
        raise _invalid_upstream_response() from exc
    if result is None:  # 2xx 但沒有本文：此端點一定回傳檢核結果物件
        logger.warning("必填檢核的 API 回應沒有本文")
        raise _invalid_upstream_response()
    return result


async def check_invoice_warnings(token: str, payload: dict[str, Any]) -> dict[str, Any]:
    """業務警示預覽（POST /invoices/check-warnings）：未來日期與金額不一致；只是提醒，不寫入任何資料。

    Args:
        token: 使用者的 access token。
        payload: 核對頁目前的欄位值（欄位同 POST /invoices，可缺漏或格式錯誤）。

    Returns:
        {"warnings": [{"field", "code", "message"}], "checked_on": "YYYY-MM-DD"}；警示不阻擋送出。

    Raises:
        ApiError: API 錯誤（401、4xx、5xx）、連線失敗（503），或 API 回 2xx 但本文不是合法 JSON／沒有本文時
            為 502 INVALID_UPSTREAM_RESPONSE（不含原始本文）。
    """
    try:
        result = await request_json("POST", "/invoices/check-warnings", token=token, json=payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("業務警示預覽的 API 回應不是合法 JSON（%s）", exc.__class__.__name__)
        raise _invalid_upstream_response() from exc
    if result is None:
        logger.warning("業務警示預覽的 API 回應沒有本文")
        raise _invalid_upstream_response()
    return result


def _invalid_upstream_response() -> ApiError:
    """API 回 2xx 但內容無法使用；不帶原始本文，由全域處理器轉成 502 JSON。"""
    return ApiError(502, "INVALID_UPSTREAM_RESPONSE", INVALID_UPSTREAM_RESPONSE_MESSAGE)


async def submit_invoice(token: str, payload: dict[str, Any]) -> dict[str, Any]:
    """送出核對後的發票（POST /invoices）：建立發票（待單位核准）並連結辨識時保存的影像。

    Returns:
        {"invoice_id", "status", "tax_period", "submitted_at", "warnings": [...]}

    Raises:
        ApiError: 辨識紀錄不存在（404）、已送出／逾時／重複（409）、格式錯誤（422）或其他 API 錯誤。
    """
    return await request_json("POST", "/invoices", token=token, json=payload)


async def fetch_invoices(
    token: str, *, page: int = 1, page_size: int = 20, status: str | None = None
) -> dict[str, Any]:
    """取得我的發票列表（GET /invoices）：只含提交者本人的發票，最新送出在前。

    Args:
        token: 使用者的 access token。
        page: 頁碼，從 1 開始。
        page_size: 每頁筆數（1～100）。
        status: 簽核狀態代碼（見 app.utils.invoice_status.APPROVAL_STATUS_LABEL 的鍵）；None 表示全部。

    Returns:
        已通過形狀檢查的分頁結果：{"items": [...], "total": int, "page": int, "page_size": int}；
        每筆含 invoice_id、status、submission_round、submitted_at、invoice_track、invoice_number、
        invoice_date、seller_name、total_amount（金額為字串）。

    Raises:
        ApiError: API 錯誤（401、422、5xx）、連線失敗（503），或 API 回 2xx 但本文不是合法 JSON、
            型別或形狀不符、回傳的 page／page_size 與請求不同時為 502 INVALID_UPSTREAM_RESPONSE
            （不含原始本文）。
    """
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if status:
        params["status"] = status
    try:
        result = await request_json("GET", "/invoices", token=token, params=params)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("發票列表的 API 回應不是合法 JSON（%s）", exc.__class__.__name__)
        raise _invalid_upstream_response() from exc
    reason = _list_violation(result, page, page_size)
    if reason is not None:
        # 只記錄固定的原因代碼，不記錄回應內容
        logger.warning("發票列表的 API 回應不符契約：%s", reason)
        raise _invalid_upstream_response()
    return result


_LIST_TEXT_KEYS = (
    "submitted_at",
    "invoice_track",
    "invoice_number",
    "invoice_date",
    "seller_name",
    "total_amount",
)


def _is_uuid_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value.lower()
    except ValueError:
        return False


def _list_violation(result: Any, page: int, page_size: int) -> str | None:
    """檢查列表回應；回傳固定的原因代碼，合法時回傳 None。

    只檢查畫面會用到的型別；狀態代碼不在此限制為九種（未知代碼由畫面標示「未知狀態」）。
    """
    if not isinstance(result, dict):
        return "result_not_object"
    items = result.get("items")
    if not isinstance(items, list):
        return "items_not_list"
    total = result.get("total")
    if not _is_int(total) or total < 0:
        return "total_invalid"
    if result.get("page") != page or not _is_int(result.get("page")):
        return "page_mismatch"
    if result.get("page_size") != page_size or not _is_int(result.get("page_size")):
        return "page_size_mismatch"
    if len(items) > min(page_size, total):
        return "items_exceed_page"
    for entry in items:
        if not isinstance(entry, dict):
            return "item_not_object"
        if not _is_uuid_text(entry.get("invoice_id")):
            return "item_invoice_id_invalid"
        if not isinstance(entry.get("status"), str):
            return "item_status_invalid"
        round_no = entry.get("submission_round")
        if not _is_int(round_no) or round_no < 0:
            return "item_round_invalid"
        if any(not _is_text_or_none(entry.get(key)) for key in _LIST_TEXT_KEYS):
            return "item_text_invalid"
    return None


async def fetch_invoice(token: str, invoice_id: str) -> dict[str, Any]:
    """取得單張發票詳情（GET /invoices/{id}）：提交者本人讀取已送出的表頭、明細、修改紀錄與警示。

    Args:
        token: 使用者的 access token。
        invoice_id: 發票 UUID 字串（路由已先檢查格式）。

    Returns:
        已通過形狀檢查的回應：invoice_id、status、submission_round、表頭欄位、items、
        modified_fields、warnings、file（可為 null）。金額與數量為字串。

    Raises:
        ApiError: API 錯誤（401、404、422、5xx）、連線失敗（503），或 API 回 2xx 但本文不是合法 JSON、
            沒有本文、型別或巢狀形狀不符、回傳的 invoice_id 不是請求的那一張時為
            502 INVALID_UPSTREAM_RESPONSE（不含原始本文）。
    """
    try:
        result = await request_json("GET", f"/invoices/{invoice_id}", token=token)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("發票詳情的 API 回應不是合法 JSON（%s）", exc.__class__.__name__)
        raise _invalid_upstream_response() from exc
    reason = _detail_violation(result, invoice_id)
    if reason is not None:
        # 只記錄固定的原因代碼，不記錄回應內容
        logger.warning("發票詳情的 API 回應不符契約：%s", reason)
        raise _invalid_upstream_response()
    return result


# 詳情回應中「字串或 null」的表頭欄位；金額欄位另列，浮點數一律不接受（避免尾端 0 在上游就遺失）
_DETAIL_TEXT_KEYS = (
    "submitted_at",
    "tax_period",
    "invoice_track",
    "invoice_number",
    "invoice_date",
    "seller_tax_id",
    "seller_name",
    "buyer_tax_id",
    "buyer_name",
    "tax_type",
    "total_amount_zh",
)
_DETAIL_AMOUNT_KEYS = ("sales_amount", "tax_amount", "total_amount")
_DETAIL_ITEM_TEXT_KEYS = ("item_name", "quantity", "unit_price", "line_amount")
_DETAIL_WARNING_KEYS = ("field", "code", "message")


def _is_int(value: Any) -> bool:
    """整數（bool 是 int 的子類別，必須明確排除）。"""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_text_or_none(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _detail_violation(result: Any, requested_id: str) -> str | None:
    """檢查詳情回應；回傳固定的原因代碼，合法時回傳 None。

    只檢查畫面會用到的型別與巢狀形狀；多出來的欄位、未知的 field_scope／field_name、
    重複的 line_no 與 modified_fields 的值（任意型別）不在此拒絕，由 Adapter 與畫面處理。
    """
    if not isinstance(result, dict):
        return "body_not_object"
    returned_id = result.get("invoice_id")
    if not isinstance(returned_id, str):
        return "invoice_id_not_text"
    try:
        returned_uuid, requested_uuid = UUID(returned_id), UUID(requested_id)
    except ValueError:
        return "invoice_id_not_uuid"
    if returned_uuid != requested_uuid:
        return "invoice_id_mismatch"
    if not isinstance(result.get("status"), str):
        return "status_not_text"
    if not _is_int(result.get("submission_round")):
        return "submission_round_not_int"
    for key in _DETAIL_TEXT_KEYS:
        if key in result and not _is_text_or_none(result[key]):
            return f"{key}_type"
    for key in _DETAIL_AMOUNT_KEYS:
        if key in result and not _is_text_or_none(result[key]):
            return f"{key}_type"
    return (
        _items_violation(result.get("items"))
        or _modified_fields_violation(result.get("modified_fields"))
        or _warnings_violation(result.get("warnings"))
        or _file_violation(result)
    )


def _items_violation(items: Any) -> str | None:
    if not isinstance(items, list):
        return "items_not_list"
    for item in items:
        if not isinstance(item, dict):
            return "item_not_object"
        if not _is_int(item.get("line_no")):
            return "item_line_no_not_int"
        for key in _DETAIL_ITEM_TEXT_KEYS:
            if key in item and not _is_text_or_none(item[key]):
                return f"item_{key}_type"
    return None


def _modified_fields_violation(records: Any) -> str | None:
    if not isinstance(records, list):
        return "modified_fields_not_list"
    for record in records:
        if not isinstance(record, dict):
            return "modified_field_not_object"
        if not isinstance(record.get("field_scope"), str):
            return "modified_field_scope_not_text"
        if not isinstance(record.get("field_name"), str):
            return "modified_field_name_not_text"
        line_no = record.get("line_no")
        if line_no is not None and not _is_int(line_no):
            return "modified_field_line_no_type"
    return None


def _warnings_violation(warnings: Any) -> str | None:
    if not isinstance(warnings, list):
        return "warnings_not_list"
    for warning in warnings:
        if not isinstance(warning, dict):
            return "warning_not_object"
        if not all(isinstance(warning.get(key), str) for key in _DETAIL_WARNING_KEYS):
            return "warning_field_type"
    return None


def _file_violation(result: dict[str, Any]) -> str | None:
    if "file" in result and result["file"] is not None and not isinstance(result["file"], dict):
        return "file_not_object"
    return None


async def upload_invoice(
    token: str, *, filename: str, content: bytes, content_type: str
) -> dict[str, Any]:
    """上傳發票圖片 / PDF（POST /invoices/upload）。

    Returns:
        建立後的發票資料。
    """
    files = {"file": (filename, content, content_type)}
    return await request_json("POST", "/invoices/upload", token=token, files=files)


async def analyze_invoice(token: str, invoice_id: int) -> dict[str, Any]:
    """重新觸發 AI 分析（POST /invoices/{id}/analyze）。"""
    return await request_json("POST", f"/invoices/{invoice_id}/analyze", token=token)


async def fetch_return_items(token: str, invoice_id: str) -> dict[str, Any]:
    """讀取退回補正所需資料（GET /invoices/{id}/return-items）：退件項目、可修改欄位、上一輪正式提交資料。

    Raises:
        ApiError: 案件不存在或不是本人（404）、不是退回狀態（409）、其他 API 錯誤；回應形狀不符時為 502。
    """
    result = await request_json("GET", f"/invoices/{invoice_id}/return-items", token=token)
    if not isinstance(result, dict) or not isinstance(result.get("previous"), dict):
        raise _invalid_upstream_response()
    if not isinstance(result.get("return_items"), list) or not isinstance(
        result.get("editable_fields"), list
    ):
        raise _invalid_upstream_response()
    return result


async def void_invoice(token: str, invoice_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """申請人作廢被退回的案件（POST /invoices/{id}/void）：只轉換狀態，保留案件與影像；之後重新上傳建立新案件。

    Raises:
        ApiError: 非原提交者（404）、已不是退回狀態或輪次過期（409）等 API 錯誤。
    """
    result = await request_json("POST", f"/invoices/{invoice_id}/void", token=token, json=payload)
    if not isinstance(result, dict) or result.get("status") != "voided":
        raise _invalid_upstream_response()
    return result


async def resubmit_invoice(token: str, invoice_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """同案重送（POST /invoices/{id}/resubmit）：原樣轉送瀏覽器收集的欄位、編輯事件與回覆，規則全部由 API 決定。

    Raises:
        ApiError: 權限（404）、輪次過期／圖片問題／重複（409）、欄位未授權或回覆不完整（400）、格式錯誤（422）等。
    """
    result = await request_json(
        "POST", f"/invoices/{invoice_id}/resubmit", token=token, json=payload
    )
    if not isinstance(result, dict):
        raise _invalid_upstream_response()
    return result
