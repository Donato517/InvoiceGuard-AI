"""
模組名稱：app.core.security
功能說明：登入 cookie 讀寫、登入後導向網址檢查（防 open redirect）、同源檢查（防 CSRF）。
注意事項：
    - API 的 access token 存在 httpOnly cookie，瀏覽器端 JavaScript 讀不到，降低 XSS 竊取風險。
    - cookie 設定 SameSite=Lax，並對會變更資料的 POST 請求加上 verify_same_origin 檢查。
"""

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Header, Request, Response

from app.constants import SESSION_COOKIE_NAME
from app.core.config import settings
from app.core.exceptions import ForbiddenError


def set_session_cookie(response: Response, access_token: str) -> None:
    """登入成功後寫入登入 cookie。"""
    response.set_cookie(
        SESSION_COOKIE_NAME,
        access_token,
        max_age=settings.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    """登出時清除登入 cookie。"""
    response.delete_cookie(
        SESSION_COOKIE_NAME, httponly=True, secure=settings.cookie_secure, samesite="lax"
    )


def get_session_token(request: Request) -> str | None:
    """從 cookie 取得 access token；未登入時回傳 None。"""
    return request.cookies.get(SESSION_COOKIE_NAME) or None


def safe_next_path(next_path: str | None, default: str = "/") -> str:
    """檢查登入後要導向的網址，只允許站內路徑。

    防止 open redirect：攻擊者若能讓 next 指向外部網站，就能把剛登入的使用者帶到釣魚頁面。

    Args:
        next_path: 使用者帶入的 next 參數。
        default: 不合法時改導向的路徑。

    Returns:
        合法的站內路徑，例如 "/invoices"；"//evil.com"、"https://evil.com" 會回傳 default。
    """
    if not next_path or not next_path.startswith("/") or next_path.startswith("//"):
        return default
    if "\\" in next_path:
        return default
    return next_path


def verify_same_origin(request: Request, origin: Annotated[str | None, Header()] = None) -> None:
    """確認 POST 等會變更資料的請求來自本站頁面（作為相依注入使用）。

    瀏覽器送出表單時會帶 Origin 標頭；與本站網域不同即拒絕，用來防止 CSRF。
    沒有 Origin 標頭（例如非瀏覽器的工具）時不阻擋，交由 SameSite cookie 保護。

    Raises:
        ForbiddenError: 請求來源與本站不同。
    """
    if origin is not None and urlsplit(origin).netloc != request.headers.get("host"):
        raise ForbiddenError("請求來源不正確")
