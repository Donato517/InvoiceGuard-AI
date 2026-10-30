"""測試目標：前台 POST /invoices/check-warnings 代理路由與頁面接線（業務警示預覽：未來日期、金額不一致）。

注意：API 一律以替身取代，不連 API、DB 或 Storage；警示規則全部在 API，這裡只驗證前台轉呼叫、錯誤處理與樣板接線。
"""

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients import invoices as invoices_client
from app.clients.base import ApiError

JSON_ACCEPT = {"Accept": "application/json"}
URL = "/invoices/check-warnings"
BODY = {
    "invoice_date": "2099-01-01",
    "sales_amount": "6000",
    "tax_amount": "300",
    "total_amount": "9999",
}
RESULT = {
    "warnings": [
        {
            "field": "invoice_date",
            "code": "invoice_date_future",
            "message": "發票日期晚於今天，請核對原始發票。",
        }
    ],
    "checked_on": "2026-10-30",
}


@pytest.fixture
def untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("業務警示預覽不應呼叫其他發票 API")

    for name in ("recognize_invoice", "check_duplicate", "submit_invoice", "check_required_fields"):
        monkeypatch.setattr(invoices_client, name, forbidden)


def test_requires_login(client: TestClient) -> None:
    response = client.post(URL, json=BODY)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_forwards_body_unchanged_and_returns_result(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, untouched: None
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def check_invoice_warnings(token: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((token, payload))
        return RESULT

    monkeypatch.setattr(invoices_client, "check_invoice_warnings", check_invoice_warnings)
    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.status_code == 200
    assert response.json() == RESULT
    assert calls == [("test-access-token", BODY)]


def test_rejects_cross_site_origin(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def forbidden(token: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("跨站請求不應轉給 API")

    monkeypatch.setattr(invoices_client, "check_invoice_warnings", forbidden)
    response = logged_in_client.post(
        URL, json=BODY, headers={"Origin": "https://evil.example", **JSON_ACCEPT}
    )

    assert response.status_code == 403


@pytest.mark.parametrize("payload", [[], "text", 5, None])
def test_body_must_be_a_json_object(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, payload: Any
) -> None:
    async def forbidden(token: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("格式不符的請求不應轉給 API")

    monkeypatch.setattr(invoices_client, "check_invoice_warnings", forbidden)

    assert logged_in_client.post(URL, json=payload, headers=JSON_ACCEPT).status_code == 422


def test_session_expiry_redirects_to_login(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def expired(token: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise ApiError(401, "UNAUTHORIZED", "登入已失效，請重新登入")

    monkeypatch.setattr(invoices_client, "check_invoice_warnings", expired)
    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


@pytest.mark.parametrize(
    ("api_status", "code"), [(503, "NETWORK_ERROR"), (500, "INTERNAL_ERROR"), (502, "BAD_GATEWAY")]
)
def test_api_failure_is_a_json_error_never_an_empty_result(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, api_status: int, code: str
) -> None:
    async def failing(token: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise ApiError(api_status, code, "服務暫時無法連線，請稍後再試")

    monkeypatch.setattr(invoices_client, "check_invoice_warnings", failing)
    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.status_code >= 400
    assert "warnings" not in response.json()
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize(
    ("status", "content"),
    [(200, "<html>gateway</html>"), (200, ""), (204, "")],
)
def test_malformed_api_success_becomes_502(
    logged_in_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    untouched: None,
    status: int,
    content: str,
) -> None:
    real_async_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(status, content=content)
        )
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.status_code == 502
    assert "warnings" not in response.json()
    assert "gateway" not in response.text


def test_client_calls_the_expected_api_path(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, untouched: None
) -> None:
    seen: list[httpx.Request] = []
    real_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=RESULT)

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.json() == RESULT
    assert [r.url.path for r in seen][-1] == "/api/v1/invoices/check-warnings"


def test_review_page_has_hidden_business_warning_box_and_no_prerendered_warnings(
    logged_in_client: TestClient,
) -> None:
    html = logged_in_client.get("/invoices/mobile-upload").text

    assert 'id="business-warnings"' in html
    assert "field-business-warning" not in html
    box = html[html.index('id="business-warnings"') :][:200]
    assert "hidden" in box


def test_business_warnings_are_display_only_in_front_code() -> None:
    """前台不得自建金額或日期規則：不出現稅率、容差或與「今天」比較。"""
    rules = Path("app/static/js/invoice-field-rules.js").read_text(encoding="utf-8")
    camera = Path("app/static/js/mobile-camera.js").read_text(encoding="utf-8")

    assert "0.05" not in rules and "TAX_RATE" not in rules
    assert "new Date()" not in rules
    assert "max =" not in camera and "'max'" not in camera  # 不限制日期欄位最大可選日
    assert "'/invoices/check-warnings'" in camera
