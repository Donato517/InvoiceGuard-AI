"""
模組名稱：app.clients.invoices
功能說明：發票相關 API——手機上傳流程（辨識、查重、送出）、列表、詳情、上傳、重新分析。
    對應 API 路徑：/api/v1/invoices
注意事項：
    - 手機上傳流程已由 API 實作；列表、詳情、上傳與重新分析的 API 端點仍為 TODO。
"""

from typing import Any

from app.clients.base import request_json


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
    """取得我的發票列表（GET /invoices）。

    Args:
        token: 使用者的 access token。
        page: 頁碼，從 1 開始。
        page_size: 每頁筆數（上限 100）。
        status: 依狀態篩選，值見 app.constants.INVOICE_STATUS_LABEL 的鍵；None 表示全部。

    Returns:
        {"items": [...], "total": int, "page": int, "page_size": int}
    """
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if status:
        params["status"] = status
    return await request_json("GET", "/invoices", token=token, params=params)


async def fetch_invoice(token: str, invoice_id: int) -> dict[str, Any]:
    """取得單張發票詳情，含明細與 AI 分析結果（GET /invoices/{id}）。"""
    return await request_json("GET", f"/invoices/{invoice_id}", token=token)


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
