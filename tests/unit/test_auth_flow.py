"""
模組名稱：tests.unit.test_auth_flow
功能說明：測試前台登入頁、登入跳轉、手機上傳登入保護與登出流程。
"""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.clients import auth as auth_client
from app.constants import SESSION_COOKIE_NAME
from app.main import app

client = TestClient(app, follow_redirects=False)


def test_login_page_renders() -> None:
    response = client.get("/login")
    assert response.status_code == 200
    assert "登入" in response.text


def test_mobile_upload_unauthenticated_redirects_to_login() -> None:
    response = client.get("/invoices/mobile-upload")
    assert response.status_code == 303
    assert "/login?next=" in response.headers["location"]


def test_login_flow_redirects_to_next_page(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_login = AsyncMock(
        return_value={
            "access_token": "mock-access-token-12345",
            "token_type": "bearer",
            "expires_in": 3600,
        }
    )
    monkeypatch.setattr(auth_client, "login", mock_login)

    response = client.post(
        "/login",
        data={
            "email": "user@example.com",
            "password": "password",
            "next": "/invoices/mobile-upload",
        },
        headers={"Host": "testserver", "Origin": "http://testserver"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/invoices/mobile-upload"
    assert SESSION_COOKIE_NAME in response.cookies


def test_logout_clears_cookie() -> None:
    response = client.post(
        "/logout",
        headers={"Host": "testserver", "Origin": "http://testserver"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
