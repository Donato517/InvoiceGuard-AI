"""
模組名稱：tests.unit.test_auth_flow
功能說明：測試前台登入頁、登入跳轉、需登入頁面的 Session 核對與登出流程（API 以替身取代）。
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.clients import auth as auth_client
from app.clients.base import ApiError
from app.constants import SESSION_COOKIE_NAME
from app.main import app

SAME_ORIGIN = {"Host": "testserver", "Origin": "http://testserver"}
LOGIN_RESULT: dict[str, Any] = {
    "session_token": "synthetic-session-token",
    "token_type": "bearer",
    "expires_in": 1800,
    "expires_at": "2026-10-28T12:00:00Z",
    "user_id": "11111111-1111-4111-8111-111111111111",
    "email": "user@example.com",
    "display_name": "測試使用者",
    "department": {
        "department_id": "22222222-2222-4222-8222-222222222222",
        "department_code": "purchasing_d",
        "department_name": "採購部",
        "is_primary": True,
    },
    "departments": [],
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, follow_redirects=False)


def submit_login(client: TestClient, password: str = "password") -> Any:
    return client.post(
        "/login",
        data={
            "email": " User@Example.com ",
            "password": password,
            "next": "/invoices/mobile-upload",
        },
        headers=SAME_ORIGIN,
    )


def test_login_page_renders(client: TestClient) -> None:
    response = client.get("/login")
    assert response.status_code == 200
    assert "登入" in response.text


def test_mobile_upload_unauthenticated_redirects_to_login(client: TestClient) -> None:
    response = client.get("/invoices/mobile-upload")
    assert response.status_code == 303
    assert "/login?next=" in response.headers["location"]


def test_login_stores_session_token_and_redirects(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_login = AsyncMock(return_value=LOGIN_RESULT)
    monkeypatch.setattr(auth_client, "login", mock_login)

    response = submit_login(client)

    assert response.status_code == 303
    assert response.headers["location"] == "/invoices/mobile-upload"
    mock_login.assert_awaited_once_with("user@example.com", "password")
    assert response.cookies[SESSION_COOKIE_NAME] == "synthetic-session-token"
    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "Max-Age=1800" in cookie_header


def test_login_revokes_previous_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_client, "login", AsyncMock(return_value=LOGIN_RESULT))
    mock_logout = AsyncMock(return_value=None)
    monkeypatch.setattr(auth_client, "logout", mock_logout)
    client.cookies.set(SESSION_COOKIE_NAME, "old-session-token")

    response = submit_login(client)

    assert response.status_code == 303
    mock_logout.assert_awaited_once_with("old-session-token")


def test_login_failure_stays_on_form_without_password(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = ApiError(401, "UNAUTHORIZED", "帳號或密碼錯誤")
    monkeypatch.setattr(auth_client, "login", AsyncMock(side_effect=error))

    response = submit_login(client, password="synthetic-wrong-password")

    assert response.status_code == 400
    assert "帳號或密碼錯誤" in response.text
    assert "synthetic-wrong-password" not in response.text
    assert SESSION_COOKIE_NAME not in response.cookies


def test_login_shows_service_unavailable_on_form(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = ApiError(503, "SERVICE_UNAVAILABLE", "登入服務暫時無法使用，請稍後再試")
    monkeypatch.setattr(auth_client, "login", AsyncMock(side_effect=error))

    response = submit_login(client)

    assert response.status_code == 503
    assert "登入服務暫時無法使用" in response.text


def test_protected_page_shows_current_user_and_department(logged_in_client: TestClient) -> None:
    response = logged_in_client.get("/invoices/mobile-upload")

    assert response.status_code == 200
    assert "測試使用者｜採購部" in response.text


def test_invalid_session_redirects_to_login_and_clears_cookie(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = ApiError(401, "UNAUTHORIZED", "登入已失效，請重新登入")
    monkeypatch.setattr(auth_client, "fetch_me", AsyncMock(side_effect=error))
    client.cookies.set(SESSION_COOKIE_NAME, "expired-session-token")

    response = client.get("/invoices/mobile-upload")

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")
    assert f'{SESSION_COOKIE_NAME}=""' in response.headers["set-cookie"]


def test_logout_revokes_session_and_clears_cookie(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_logout = AsyncMock(return_value=None)
    monkeypatch.setattr(auth_client, "logout", mock_logout)
    client.cookies.set(SESSION_COOKIE_NAME, "current-session-token")

    response = client.post("/logout", headers=SAME_ORIGIN)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    mock_logout.assert_awaited_once_with("current-session-token")
    assert f'{SESSION_COOKIE_NAME}=""' in response.headers["set-cookie"]


def test_logout_still_clears_cookie_when_api_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = ApiError(503, "NETWORK_ERROR", "服務暫時無法連線，請稍後再試")
    monkeypatch.setattr(auth_client, "logout", AsyncMock(side_effect=error))
    client.cookies.set(SESSION_COOKIE_NAME, "current-session-token")

    response = client.post("/logout", headers=SAME_ORIGIN)

    assert response.status_code == 303
    assert f'{SESSION_COOKIE_NAME}=""' in response.headers["set-cookie"]


def test_logout_without_cookie_does_not_call_api(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_logout = AsyncMock(return_value=None)
    monkeypatch.setattr(auth_client, "logout", mock_logout)

    response = client.post("/logout", headers=SAME_ORIGIN)

    assert response.status_code == 303
    mock_logout.assert_not_awaited()
