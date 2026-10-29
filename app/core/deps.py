"""
模組名稱：app.core.deps
功能說明：集中定義 FastAPI 相依注入（Depends）的型別別名，供 routers 使用。
使用方式：
    @router.get("/invoices")
    async def invoice_list(request: Request, token: AccessToken) -> HTMLResponse:
        ...
"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.exceptions import LoginRequiredError
from app.core.security import get_session_token


def require_login(request: Request) -> str:
    """需要登入的頁面使用：回傳 cookie 中的 Session Token；沒有 cookie 時拋出 LoginRequiredError。

    只確認 cookie 存在；Session 是否有效由 routers/auth.py 的 require_session 經 API 核對。
    """
    token = get_session_token(request)
    if token is None:
        raise LoginRequiredError
    return token


# 需要登入的頁面：在參數宣告 `token: AccessToken`
AccessToken = Annotated[str, Depends(require_login)]
