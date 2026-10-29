"""
模組名稱：app.core.exceptions
功能說明：網站例外類別與全域例外處理器——未登入導向登入頁、API 錯誤與系統錯誤顯示錯誤頁。
注意事項：
    - 錯誤頁只顯示易懂的中文訊息，不顯示內部錯誤細節；完整堆疊寫入日誌。
    - 頁面 JS 以 fetch 呼叫並帶 Accept: application/json 時（例如手機上傳），錯誤改回
      {"error": {"code", "message", "details"}}（含 API 錯誤、Origin 檢查、格式錯誤、404／405 與未預期錯誤）；
      未登入或 Session 失效仍導向登入頁。
    - 格式錯誤（422）不論哪種格式都不回傳輸入值：一般請求顯示錯誤頁，JSON 只列欄位位置與錯誤類型。
"""

import logging
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.clients.base import ApiError
from app.constants import SESSION_COOKIE_NAME
from app.core.templating import templates

logger = logging.getLogger(__name__)


class LoginRequiredError(Exception):
    """需要登入；由全域處理器導向登入頁。"""


class ForbiddenError(Exception):
    """請求被拒絕（例如來源檢查失敗）。"""


def _login_redirect(request: Request) -> RedirectResponse:
    """導向登入頁，並記錄原本要去的頁面（登入後導回）。"""
    next_path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    response = RedirectResponse(f"/login?{urlencode({'next': next_path})}", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


# JSON 錯誤回應的框架層代碼（與 API 的 docs/API_CONVENTIONS.md 一致）
_HTTP_STATUS_CODES = {
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
}


def _wants_json(request: Request) -> bool:
    """頁面 JS 的 fetch 請求（Accept 含 application/json）要 JSON 錯誤，不要錯誤頁。"""
    return "application/json" in request.headers.get("accept", "").lower()


def _error_json(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    error = {"code": code, "message": message, "details": details}
    return JSONResponse({"error": error}, status_code=status_code)


def _error_page(request: Request, status_code: int, message: str) -> HTMLResponse:
    """顯示通用錯誤頁。"""
    return templates.TemplateResponse(
        request,
        "pages/errors/error.html",
        {"status_code": status_code, "message": message},
        status_code=status_code,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """在 FastAPI app 上註冊全域例外處理器（於 app.main 呼叫）。"""

    @app.exception_handler(LoginRequiredError)
    async def handle_login_required(request: Request, exc: LoginRequiredError) -> RedirectResponse:
        return _login_redirect(request)

    @app.exception_handler(ForbiddenError)
    async def handle_forbidden(request: Request, exc: ForbiddenError) -> Response:
        message = str(exc) or "沒有權限執行此操作"
        if _wants_json(request):
            return _error_json(403, "FORBIDDEN", message)
        return _error_page(request, 403, message)

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> Response:
        # token 過期或無效：清除登入狀態，請使用者重新登入
        if exc.status_code == 401:
            return _login_redirect(request)
        # API 的 5xx 對使用者而言都是「服務暫時異常」，統一回 502
        status_code = exc.status_code if 400 <= exc.status_code < 500 else 502
        if _wants_json(request):
            return _error_json(status_code, exc.code, exc.message, exc.details)
        return _error_page(request, status_code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> Response:
        # 兩種格式都不回傳輸入值（可能含密碼或個資）
        if not _wants_json(request):
            return _error_page(request, 422, "資料格式不正確，請重新填寫")
        details = [{"loc": error["loc"], "type": error["type"]} for error in exc.errors()]
        return _error_json(422, "VALIDATION_ERROR", "資料格式不正確，請重新核對", details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if _wants_json(request):
            code = _HTTP_STATUS_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
            message = "找不到這個頁面" if exc.status_code == 404 else "無法處理這個請求"
            return _error_json(exc.status_code, code, message)
        if exc.status_code == 404:
            return templates.TemplateResponse(request, "pages/errors/404.html", status_code=404)
        return _error_page(request, exc.status_code, "無法處理這個請求")

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> Response:
        logger.exception("未預期錯誤：%s %s", request.method, request.url.path)
        if _wants_json(request):
            return _error_json(500, "INTERNAL_ERROR", "系統發生錯誤，請稍後再試")
        return _error_page(request, 500, "系統發生錯誤，請稍後再試")
