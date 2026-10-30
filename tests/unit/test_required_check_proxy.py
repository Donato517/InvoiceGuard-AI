"""測試目標：前台 POST /invoices/check-required 代理路由（Session、Origin、錯誤處理、只轉呼叫必填檢核）。

注意：API 一律以替身取代，不連 API、DB 或 Storage；必填規則由 API 決定，這裡只驗證前台轉呼叫行為。
"""

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients import auth as auth_client
from app.clients import invoices as invoices_client
from app.clients.base import ApiError

JSON_ACCEPT = {"Accept": "application/json"}
URL = "/invoices/check-required"
BODY = {
    "recognition_id": "33333333-3333-4333-8333-333333333333",
    "invoice_track": "CD",
    "invoice_number": "",
    "items": [{"item_name": "", "line_amount": "100"}],
}
MISSING = {
    "required_complete": False,
    "missing": [
        {
            "field": "invoice_number",
            "code": "required_missing",
            "message": "請填寫發票號碼",
            "line_no": None,
        }
    ],
}


@pytest.fixture
def untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    """其他發票 API 都不應被必填檢核呼叫。"""

    async def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("必填檢核不應呼叫其他發票 API")

    for name in ("recognize_invoice", "check_duplicate", "submit_invoice"):
        monkeypatch.setattr(invoices_client, name, forbidden)


def test_requires_login(client: TestClient) -> None:
    response = client.post(URL, json=BODY)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_forwards_body_unchanged_and_returns_api_result(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, untouched: None
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def check_required_fields(token: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((token, payload))
        return MISSING

    monkeypatch.setattr(invoices_client, "check_required_fields", check_required_fields)
    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.status_code == 200
    assert response.json() == MISSING
    assert calls == [("test-access-token", BODY)]


def test_complete_result_is_passed_through(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, untouched: None
) -> None:
    async def check_required_fields(token: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"required_complete": True, "missing": []}

    monkeypatch.setattr(invoices_client, "check_required_fields", check_required_fields)
    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.json() == {"required_complete": True, "missing": []}


def test_rejects_cross_site_origin(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def forbidden(token: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("跨站請求不應轉給 API")

    monkeypatch.setattr(invoices_client, "check_required_fields", forbidden)
    response = logged_in_client.post(
        URL, json=BODY, headers={"Origin": "https://evil.example", **JSON_ACCEPT}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize("payload", [[], "text", 5, None])
def test_body_must_be_a_json_object(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, payload: Any
) -> None:
    async def forbidden(token: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("格式不符的請求不應轉給 API")

    monkeypatch.setattr(invoices_client, "check_required_fields", forbidden)
    response = logged_in_client.post(URL, json=payload, headers=JSON_ACCEPT)

    assert response.status_code == 422


def test_api_session_expiry_redirects_to_login(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def expired(token: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise ApiError(401, "UNAUTHORIZED", "登入已失效，請重新登入")

    monkeypatch.setattr(invoices_client, "check_required_fields", expired)
    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


@pytest.mark.parametrize(
    ("api_status", "code"), [(503, "NETWORK_ERROR"), (500, "INTERNAL_ERROR"), (502, "BAD_GATEWAY")]
)
def test_api_failure_is_a_json_error_never_a_pass(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, api_status: int, code: str
) -> None:
    async def failing(token: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise ApiError(api_status, code, "服務暫時無法連線，請稍後再試")

    monkeypatch.setattr(invoices_client, "check_required_fields", failing)
    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.status_code >= 400
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert "required_complete" not in body
    assert body["error"]["code"] == code


def test_session_check_failure_is_a_json_error(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unavailable(token: str) -> dict[str, Any]:
        raise ApiError(503, "SERVICE_UNAVAILABLE", "登入服務暫時無法使用，請稍後再試")

    monkeypatch.setattr(auth_client, "fetch_me", unavailable)
    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.status_code == 502
    assert "required_complete" not in response.json()


def test_existing_mobile_upload_proxy_still_rejects_missing_fields(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """正式提交的代理路由行為不變：缺欄位仍由前台模型 422 擋下，不轉給 API。"""

    async def submit_invoice(token: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("不應呼叫 API")

    monkeypatch.setattr(invoices_client, "submit_invoice", submit_invoice)
    response = logged_in_client.post("/invoices/mobile-upload", json={"invoice_number": "CD1"})

    assert response.status_code == 422


# ---- 真實 request_json（只把 HTTP 傳輸換成 MockTransport）：API 回應異常時的處理 ----
API_CHECK_URL = "http://127.0.0.1:8000/api/v1/invoices/check-required"
INVALID_MESSAGE = "服務回應異常，請稍後再試"
HTML_BODY = "<html><body>gateway SECRET-RAW-BODY</body></html>"


@pytest.fixture
def api_responds(monkeypatch: pytest.MonkeyPatch, untouched: None) -> Any:
    """讓真實的 invoices client 與 request_json 收到指定的 API 回應（不連任何服務）。"""
    seen: list[httpx.Request] = []
    real_async_client = httpx.AsyncClient

    def install(responder: Any) -> list[httpx.Request]:
        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return responder(request)

        def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_async_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        return seen

    return install


@pytest.mark.parametrize(
    ("status", "content"),
    [
        (200, HTML_BODY.encode()),
        (200, b""),
        (201, b""),
        (200, b"{not valid json"),
        (200, b"\x80\x81\x82"),
        (200, b"\xff\xfe\x00{"),
    ],
    ids=["html", "empty", "empty-201", "invalid-json", "non-utf8", "bom-garbage"],
)
def test_2xx_without_valid_json_is_a_502_json_error_never_a_pass(
    logged_in_client: TestClient, api_responds: Any, status: int, content: bytes
) -> None:
    seen = api_responds(lambda request: httpx.Response(status, content=content))

    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    error = response.json()["error"]
    assert error["code"] == "INVALID_UPSTREAM_RESPONSE"
    assert error["message"] == INVALID_MESSAGE
    assert "required_complete" not in response.text
    assert "SECRET-RAW-BODY" not in response.text and "html" not in response.text
    assert len(seen) == 1 and str(seen[0].url) == API_CHECK_URL  # 真的走到 request_json


def test_valid_json_through_real_request_json_is_unchanged(
    logged_in_client: TestClient, api_responds: Any
) -> None:
    seen = api_responds(lambda request: httpx.Response(200, json=MISSING))

    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.status_code == 200
    assert response.json() == MISSING
    assert seen[0].headers["authorization"] == "Bearer test-access-token"


@pytest.mark.parametrize("payload", [{}, [], {"required_complete": "yes"}])
def test_valid_json_with_unexpected_shape_is_still_passed_through(
    logged_in_client: TestClient, api_responds: Any, payload: Any
) -> None:
    """合法 JSON 但結構異常：維持原樣轉出（由前端 parseCheckResult 拒絕），不在此新增驗證。"""
    api_responds(lambda request: httpx.Response(200, json=payload))

    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.status_code == 200
    assert response.json() == payload


def test_api_401_still_redirects_to_login(logged_in_client: TestClient, api_responds: Any) -> None:
    api_responds(
        lambda request: httpx.Response(
            401, json={"error": {"code": "UNAUTHORIZED", "message": "x"}}
        )
    )

    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


def test_api_4xx_keeps_status_and_code(logged_in_client: TestClient, api_responds: Any) -> None:
    error = {"error": {"code": "VALIDATION_ERROR", "message": "請求參數格式錯誤", "details": []}}
    api_responds(lambda request: httpx.Response(422, json=error))

    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("status", "content", "code"),
    [
        (500, b'{"error": {"code": "INTERNAL_ERROR", "message": "x"}}', "INTERNAL_ERROR"),
        (502, HTML_BODY.encode(), "HTTP_502"),  # 錯誤狀態的非 JSON 本文：既有處理不變
    ],
)
def test_api_5xx_keeps_existing_mapping(
    logged_in_client: TestClient, api_responds: Any, status: int, content: bytes, code: str
) -> None:
    api_responds(lambda request: httpx.Response(status, content=content))

    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == code
    assert "required_complete" not in response.text


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), httpx.ConnectTimeout("slow")],
    ids=["connect", "read-timeout", "connect-timeout"],
)
def test_connection_failures_keep_network_error(
    logged_in_client: TestClient, api_responds: Any, error: httpx.HTTPError
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise error

    api_responds(fail)

    response = logged_in_client.post(URL, json=BODY, headers=JSON_ACCEPT)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "NETWORK_ERROR"
