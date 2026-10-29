"""
模組名稱：app.routers.auth
功能說明：登入 / 登出頁面，以及需登入頁面共用的 Session 核對。
路由：GET /login、POST /login、POST /logout
注意事項：
    - 登入成功後把 API 的 session_token 存入 httpOnly cookie；登出時請 API 撤銷 Session 再清 cookie。
    - require_session 每次經 API /auth/me 核對 Session，不只看 cookie 是否存在。
"""

import logging
from contextlib import suppress
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.clients import auth as auth_client
from app.clients.base import ApiError
from app.core.deps import AccessToken
from app.core.security import (
    clear_session_cookie,
    get_session_token,
    safe_next_path,
    set_session_cookie,
    verify_same_origin,
)
from app.core.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

LOGIN_TEMPLATE = "pages/auth/login.html"
# 留在登入頁顯示訊息的 API 錯誤：帳密錯誤、格式錯誤、服務暫時無法使用
_LOGIN_FORM_ERRORS = {400, 401, 403, 422, 503}


async def require_session(request: Request, token: AccessToken) -> dict[str, Any]:
    """需登入的頁面使用：經 API 核對 Session，登入者資料放在 request.state.current_user。

    沒有 cookie 時由 AccessToken 導向登入頁；Session 失效時 API 回 401，
    由全域例外處理器清除 cookie 並導向登入頁。

    Returns:
        API /auth/me 的回應：使用者 UUID、Email、顯示名稱、選取部門與部門清單。
    """
    current_user = await auth_client.fetch_me(token)
    request.state.current_user = current_user
    return current_user


# 需要登入者資料的頁面：在參數宣告 `current_user: CurrentUser`
CurrentUser = Annotated[dict[str, Any], Depends(require_session)]


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
    """送出登入表單：呼叫 API 建立 Session，成功後寫入 cookie 並導回 next 頁面。"""
    try:
        result = await auth_client.login(email.strip().lower(), password)
    except ApiError as exc:
        # 帳號密碼錯誤或服務暫時無法使用：留在登入頁顯示訊息（不回填密碼）
        if exc.status_code in _LOGIN_FORM_ERRORS:
            context = {"next": safe_next_path(next_path), "email": email, "error": exc.message}
            status_code = 503 if exc.status_code == 503 else 400
            return templates.TemplateResponse(
                request, LOGIN_TEMPLATE, context, status_code=status_code
            )
        raise

    # 新 Session 建立成功後才撤銷瀏覽器原有的舊 Session；舊的已失效或撤銷失敗都不影響這次登入
    old_token = get_session_token(request)
    if old_token:
        with suppress(ApiError):
            await auth_client.logout(old_token)

    response = RedirectResponse(safe_next_path(next_path), status_code=303)
    set_session_cookie(response, result["session_token"], max_age=result["expires_in"])
    return response


@router.post("/logout", dependencies=[Depends(verify_same_origin)])
async def logout(request: Request) -> RedirectResponse:
    """登出：請 API 撤銷 Session，清除登入 cookie 並回到首頁。"""
    token = get_session_token(request)
    if token:
        try:
            await auth_client.logout(token)
        except ApiError as exc:
            # API 無法連線時仍清除 cookie；該 Session 會在到期時間後失效
            logger.warning("API 登出失敗（%s），仍清除登入 cookie", exc.code)
    response = RedirectResponse("/", status_code=303)
    clear_session_cookie(response)
    return response
