"""
模組名稱：app.clients.invoices
功能說明：發票相關 API——列表、詳情、上傳、重新分析。對應 API 路徑：/api/v1/invoices
"""

from typing import Any

from app.clients.base import request_json


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
