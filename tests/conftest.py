"""
pytest 共用 fixture。
規則：
    - 單元測試不得呼叫真實 API；需要 API 回應時，以 monkeypatch 替換 app.clients 內的函式。
"""

import os
import socket
from contextvars import ContextVar
from typing import Any

import pytest
from fastapi.testclient import TestClient

# 匯入應用前清除已知設定；只處理名稱，不保存或列印公司環境值。
_CONFIGURATION_NAMES = {
    "APP_NAME",
    "APP_ENV",
    "DEBUG",
    "API_BASE_URL",
    "API_TIMEOUT_SECONDS",
    "SESSION_MAX_AGE_SECONDS",
    "VERCEL",
    "VERCEL_ENV",
    "VERCEL_GIT_COMMIT_SHA",
    "DATABASE_URL",
    "DATABASE_URL_UNPOOLED",
    "SESSION_SECRET_KEY",
    "JWT_SECRET_KEY",
    "CRON_SECRET",
    "SUPABASE_SECRET_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "AI_API_KEY",
    "EINVOICE_APP_ID",
    "EINVOICE_API_KEY",
    "BLOB_READ_WRITE_TOKEN",
    "VERCEL_TOKEN",
    "LOCAL_SECRET_FIELDS",
    "LOCAL_HTTPS_ORIGIN",
    "LOCAL_MOBILE_ACCESS_CODE",
    "LOCAL_MOBILE_ORIGIN_FILE",
}
for _name in tuple(os.environ):
    if _name.upper() in _CONFIGURATION_NAMES:
        del os.environ[_name]


@pytest.fixture(autouse=True)
def block_external_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """單元測試禁止真實 API／DNS；只允許 Windows 程序內 socketpair 通道。"""
    original_connect = socket.socket.connect
    original_socketpair = socket.socketpair
    inside_socketpair: ContextVar[bool] = ContextVar("inside_socketpair", default=False)

    def deny_connection(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("單元測試禁止外部網路或真實服務連線")

    def guarded_connect(connection: socket.socket, address: Any) -> Any:
        if inside_socketpair.get() and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(connection, address)
        return deny_connection()

    def guarded_socketpair(*args: Any, **kwargs: Any) -> tuple[socket.socket, socket.socket]:
        token = inside_socketpair.set(True)
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            inside_socketpair.reset(token)

    monkeypatch.setattr(socket, "create_connection", deny_connection)
    monkeypatch.setattr(socket, "getaddrinfo", deny_connection)
    monkeypatch.setattr(socket, "socketpair", guarded_socketpair)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_connection)
    monkeypatch.setattr(socket.socket, "sendto", deny_connection)


@pytest.fixture
def client() -> TestClient:
    """未登入的瀏覽器。follow_redirects=False 以便檢查導向。"""
    from app.main import app

    return TestClient(app, follow_redirects=False)


SYNTHETIC_SESSION = {
    "user_id": "11111111-1111-4111-8111-111111111111",
    "email": "user@example.com",
    "display_name": "測試使用者",
    "expires_at": "2026-10-28T12:00:00Z",
    "department": {
        "department_id": "22222222-2222-4222-8222-222222222222",
        "department_code": "purchasing_d",
        "department_name": "採購部",
        "is_primary": True,
    },
    "departments": [],
}


@pytest.fixture
def logged_in_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """已登入的瀏覽器：帶假的登入 cookie，API /auth/me 以替身回傳合成 Session。"""
    from app.clients import auth as auth_client
    from app.constants import SESSION_COOKIE_NAME
    from app.main import app

    async def fetch_me(token: str) -> dict[str, Any]:
        assert token == "test-access-token"
        return SYNTHETIC_SESSION

    monkeypatch.setattr(auth_client, "fetch_me", fetch_me)
    test_client = TestClient(app, follow_redirects=False)
    test_client.cookies.set(SESSION_COOKIE_NAME, "test-access-token")
    return test_client
