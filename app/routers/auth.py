"""
模組名稱：app.routers.auth
功能說明：登入 / 登出頁面。登入成功後把 API 的 access token 存入 httpOnly cookie。
路由：GET /login、POST /login、POST /logout
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.clients import auth as auth_client
from app.clients.base import ApiError
from app.core.security import (
    clear_session_cookie,
    safe_next_path,
    set_session_cookie,
    verify_same_origin,
)
from app.core.templating import templates

router = APIRouter(tags=["auth"])

LOGIN_TEMPLATE = "pages/auth/login.html"


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request, next_path: Annotated[str, Query(alias="next")] = "/"
) -> HTMLResponse:
    """顯示登入表單。next 為登入後要回到的頁面。"""
    return templates.TemplateResponse(request, LOGIN_TEMPLATE, {"next": safe_next_path(next_path)})


@router.post("/login", dependencies=[Depends(verify_same_origin)], response_model=None)
async def login(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next_path: Annotated[str, Form(alias="next")] = "/",
) -> HTMLResponse | RedirectResponse:
    """送出登入表單：呼叫 API 取得 token，成功後寫入 cookie 並導回 next 頁面。"""
    try:
        result = await auth_client.login(email.strip().lower(), password)
    except ApiError as exc:
        # 帳號密碼錯誤或格式錯誤：留在登入頁顯示訊息（不回填密碼）
        if exc.status_code in (400, 401, 422):
            context = {"next": safe_next_path(next_path), "email": email, "error": exc.message}
            return templates.TemplateResponse(request, LOGIN_TEMPLATE, context, status_code=400)
        raise

    response = RedirectResponse(safe_next_path(next_path), status_code=303)
    set_session_cookie(response, result["access_token"])
    return response


@router.post("/logout", dependencies=[Depends(verify_same_origin)])
async def logout() -> RedirectResponse:
    """登出：清除登入 cookie 並回到首頁。"""
    # TODO(JerryChien): API 完成後一併呼叫 auth_client.logout() 讓 token 失效
    response = RedirectResponse("/", status_code=303)
    clear_session_cookie(response)
    return response
