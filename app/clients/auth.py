"""
模組名稱：app.clients.auth
功能說明：登入相關 API。對應 API 路徑：/api/v1/auth
注意事項：
    - 登入回傳的 session_token 由 routers/auth.py 存入 httpOnly cookie；之後以 Bearer 帶給 API。
"""

from typing import Any

from app.clients.base import request_json


async def login(email: str, password: str) -> dict[str, Any]:
    """帳號密碼登入（POST /auth/login）；API 會建立一筆 Session。

    Returns:
        {"session_token": str, "token_type": "bearer", "expires_in": int, "expires_at": str,
         "user_id": str, "email": str, "display_name": str,
         "department": {...}, "departments": [{...}]}

    Raises:
        ApiError: 帳號密碼錯誤（401）、服務無法使用（503）或其他 API 錯誤。
    """
    return await request_json(
        "POST", "/auth/login", json={"email": email.strip().lower(), "password": password}
    )


async def fetch_me(token: str) -> dict[str, Any]:
    """取得目前登入者與選取部門（GET /auth/me）；API 每次都重新核對 Session。

    Returns:
        {"user_id": str, "email": str, "display_name": str, "expires_at": str,
         "department": {"department_id", "department_code", "department_name", "is_primary"},
         "departments": [...]}

    Raises:
        ApiError: Session 無效或過期（401）或其他 API 錯誤。
    """
    return await request_json("GET", "/auth/me", token=token)


async def logout(token: str) -> None:
    """登出（POST /auth/logout）：撤銷 API 端的 Session。"""
    await request_json("POST", "/auth/logout", token=token)
