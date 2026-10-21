"""
pytest 共用 fixture。
規則：
    - 單元測試不得呼叫真實 API；需要 API 回應時，以 monkeypatch 替換 app.clients 內的函式。
"""

import pytest
from fastapi.testclient import TestClient

from app.constants import SESSION_COOKIE_NAME
from app.main import app


@pytest.fixture
def client() -> TestClient:
    """未登入的瀏覽器。follow_redirects=False 以便檢查導向。"""
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def logged_in_client() -> TestClient:
    """已登入的瀏覽器（帶假的登入 cookie）。"""
    test_client = TestClient(app, follow_redirects=False)
    test_client.cookies.set(SESSION_COOKIE_NAME, "test-access-token")
    return test_client
