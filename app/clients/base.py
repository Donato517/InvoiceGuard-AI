"""
模組名稱：app.clients.base
功能說明：呼叫 InvoiceGuard-AI-API 的共用 HTTP 用戶端——設定位址與逾時、附帶 token、統一錯誤格式。
注意事項：
    - 所有 API 呼叫都必須透過 request_json()。
    - API 錯誤格式：{"error": {"code", "message", "details"}}（見 API 專案 docs/API_CONVENTIONS.md）。
"""

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """API 呼叫失敗。message 可直接顯示給使用者，code 供程式判斷。"""

    def __init__(self, status_code: int, code: str, message: str, details: Any = None) -> None:
        """
        Args:
            status_code: HTTP 狀態碼；連線失敗時為 503。
            code: 錯誤代碼，例如 "NOT_FOUND"、"NETWORK_ERROR"。
            message: 給使用者看的錯誤訊息。
            details: 額外資訊（例如欄位錯誤清單）。
        """
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


async def request_json(method: str, path: str, *, token: str | None = None, **kwargs: Any) -> Any:
    """呼叫 API 並回傳 JSON 內容。

    Args:
        method: HTTP 方法，例如 "GET"、"POST"。
        path: API 路徑（不含 /api/v1），例如 "/invoices"。
        token: 使用者的 access token；不需登入的請求傳 None。
        **kwargs: 傳給 httpx 的其他參數，例如 params、json、files。

    Returns:
        回應的 JSON 內容；沒有內容時回傳 None。

    Raises:
        ApiError: 連線失敗或 API 回傳錯誤狀態碼。
    """
    settings.require_environment()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(
            base_url=settings.API_BASE_URL, timeout=settings.API_TIMEOUT_SECONDS
        ) as client:
            response = await client.request(method, path, headers=headers, **kwargs)
    except httpx.HTTPError as exc:
        logger.warning("API 連線失敗：%s %s（%s）", method, path, exc.__class__.__name__)
        raise ApiError(503, "NETWORK_ERROR", "服務暫時無法連線，請稍後再試") from exc

    if response.is_error:
        raise _to_api_error(response)
    if not response.content:
        return None
    return response.json()


async def request_image(path: str, *, token: str) -> tuple[bytes, str]:
    """透過既有 API 設定讀取受保護的範例圖片，不將 Token 放入圖片 URL。"""
    settings.require_environment()
    try:
        async with (
            httpx.AsyncClient(
                base_url=settings.API_BASE_URL, timeout=settings.API_TIMEOUT_SECONDS
            ) as client,
            client.stream("GET", path, headers={"Authorization": f"Bearer {token}"}) as response,
        ):
            if response.is_error or response.is_redirect:
                await response.aread()
                raise _to_api_error(response)
            mime = response.headers.get("content-type", "").split(";")[0]
            if mime not in {"image/jpeg", "image/png"}:
                raise ApiError(502, "SHOWCASE_IMAGE_INVALID", "範例圖片格式不符")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 4 * 1024 * 1024:
                    raise ApiError(502, "SHOWCASE_IMAGE_INVALID", "範例圖片超過大小限制")
            return bytes(content), mime
    except httpx.HTTPError:
        raise ApiError(503, "NETWORK_ERROR", "範例來源暫時無法連線") from None


def _to_api_error(response: httpx.Response) -> ApiError:
    """將 API 的錯誤回應轉為 ApiError；回應格式不符時使用預設訊息。"""
    try:
        body = response.json()
    except ValueError:
        body = None
    error = body.get("error") if isinstance(body, dict) else None
    error = error if isinstance(error, dict) else {}
    return ApiError(
        response.status_code,
        error.get("code", f"HTTP_{response.status_code}"),
        error.get("message", "系統發生錯誤，請稍後再試"),
        error.get("details"),
    )
