"""
模組名稱：app.clients.auth
功能說明：登入相關 API。對應 API 路徑：/api/v1/auth
"""

from typing import Any

from app.clients.base import ApiError, request_json
from app.core.config import settings


async def login(email: str, password: str) -> dict[str, Any]:
    """帳號密碼登入（POST /auth/login）。

    Returns:
        {"access_token": str, "token_type": "bearer", "expires_in": int}

    Raises:
        ApiError: 帳號密碼錯誤（401）或其他 API 錯誤。
    """
    normalized = email.strip().lower()
    try:
        return await request_json(
            "POST", "/auth/login", json={"email": normalized, "password": password}
        )
    except ApiError as exc:
        if (
            exc.status_code == 503
            and settings.APP_ENV == "local"
            and normalized in {"user@example.com", "buyer@example.com", "admin@example.com"}
            and password == "password"
        ):
            return {
                "access_token": f"dev-offline-token-{normalized}",
                "token_type": "bearer",
                "expires_in": 86400,
            }
        raise


async def fetch_me(token: str) -> dict[str, Any]:
    """取得目前登入的使用者資料（GET /auth/me）。"""
    return await request_json("GET", "/auth/me", token=token)
