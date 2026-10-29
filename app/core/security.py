"""
模組名稱：app.core.security
功能說明：登入 cookie 讀寫、登入後導向網址檢查（防 open redirect）、同源檢查（防 CSRF）。
注意事項：
    - API 的 Session Token 存在 httpOnly cookie，瀏覽器端 JavaScript 讀不到，降低 XSS 竊取風險。
    - cookie 設定 SameSite=Lax，並對會變更資料的 POST 請求加上 verify_same_origin 檢查。
"""

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Header, Request, Response

from app.constants import SESSION_COOKIE_NAME
from app.core.config import settings
from app.core.exceptions import ForbiddenError


def set_session_cookie(response: Response, session_token: str, max_age: int | None = None) -> None:
    """登入成功後寫入登入 cookie。

    Args:
        response: 要寫入 cookie 的回應。
        session_token: API 登入回傳的 Session Token。
        max_age: API 回傳的 Session 有效秒數；cookie 不超過此值與 SESSION_MAX_AGE_SECONDS。
    """
    limit = settings.SESSION_MAX_AGE_SECONDS
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        max_age=limit if max_age is None else min(max_age, limit),
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
    """從 cookie 取得 Session Token；未登入時回傳 None（是否仍有效須經 API 核對）。"""
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

    一般／正式模式只比對 Origin 的「主機:埠」與 Host 標頭：Vercel 等平台在 proxy 後
    傳給 ASGI 的 scheme 不保證是 https，不能拿 request.base_url 的 scheme 比對。
    手機開發模式（LOCAL_HTTPS_ORIGIN／LOCAL_MOBILE_ORIGIN_FILE）才依完整 origin 嚴格比對；
    握手檔尚未載入時沒有可信 origin，一律拒絕。

    Raises:
        ForbiddenError: 請求來源與本站不同。
    """
    if origin is None:
        return
    if settings.LOCAL_HTTPS_ORIGIN or settings.LOCAL_MOBILE_ORIGIN_FILE:
        actual_origin = _origin_tuple(origin)
        if actual_origin is None or actual_origin != _origin_tuple(settings.LOCAL_HTTPS_ORIGIN):
            raise ForbiddenError("請求來源不正確")
        return
    try:
        same_host = urlsplit(origin).netloc == request.headers.get("host")
    except ValueError:
        same_host = False
    if not same_host:
        raise ForbiddenError("請求來源不正確")


def _origin_tuple(value: str) -> tuple[str, str, int] | None:
    """依 scheme／host／有效 port 比對，拒絕偽裝成 Origin 的帳密或路徑。"""
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or any(character.isspace() for character in value)
            or "\\" in value
        ):
            return None
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            return None
        return parsed.scheme, parsed.hostname, port
    except ValueError:
        return None
