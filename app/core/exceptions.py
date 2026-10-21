"""
模組名稱：app.core.exceptions
功能說明：網站例外類別與全域例外處理器——未登入導向登入頁、API 錯誤與系統錯誤顯示錯誤頁。
注意事項：
    - 錯誤頁只顯示易懂的中文訊息，不顯示內部錯誤細節；完整堆疊寫入日誌。
"""

import logging
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
    async def handle_forbidden(request: Request, exc: ForbiddenError) -> HTMLResponse:
        return _error_page(request, 403, str(exc) or "沒有權限執行此操作")

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> HTMLResponse | RedirectResponse:
        # token 過期或無效：清除登入狀態，請使用者重新登入
        if exc.status_code == 401:
            return _login_redirect(request)
        # API 的 5xx 對使用者而言都是「服務暫時異常」，統一回 502
        status_code = exc.status_code if 400 <= exc.status_code < 500 else 502
        return _error_page(request, status_code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
        if exc.status_code == 404:
            return templates.TemplateResponse(request, "pages/errors/404.html", status_code=404)
        return _error_page(request, exc.status_code, "無法處理這個請求")

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> HTMLResponse:
        logger.exception("未預期錯誤：%s %s", request.method, request.url.path)
        return _error_page(request, 500, "系統發生錯誤，請稍後再試")
