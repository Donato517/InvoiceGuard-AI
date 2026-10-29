"""測試目標：頁面路由、登入保護、錯誤頁、靜態檔"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.clients import invoices as invoices_client
from app.clients.base import ApiError

JPEG = b"\xff\xd8\xff\xe0synthetic-jpeg"
DUPLICATE_QUERY = {"invoice_track": "CD", "invoice_number": "88889999", "seller_tax_id": "27601907"}
# 手機頁 JS 的 fetch 帶 Accept: application/json，錯誤改回 JSON
JSON_ACCEPT = {"Accept": "application/json"}


def mobile_payload(**changes: Any) -> dict[str, Any]:
    """手機端核對後送出的合成發票資料（欄位對應 API POST /invoices）。"""
    payload: dict[str, Any] = {
        "recognition_id": "33333333-3333-4333-8333-333333333333",
        "invoice_track": "CD",
        "invoice_number": "88889999",
        "invoice_date": "2026-08-20",
        "seller_tax_id": "27601907",
        "seller_name": "範例文具行",
        "buyer_tax_id": "04595257",
        "buyer_name": "範例科技股份有限公司",
        "tax_type": "taxable",
        "sales_amount": "5000",
        "tax_amount": "250",
        "total_amount": "5250",
        "total_amount_zh": "伍仟貳佰伍拾元整",
        "items": [
            {
                "source_line_no": 1,
                "item_name": "伺服器硬碟",
                "quantity": "1",
                "unit_price": "5000",
                "line_amount": "5000",
            }
        ],
        "changes": [
            {
                "field_scope": "header",
                "line_no": None,
                "field_name": "seller_name",
                "old_value": "範例文具",
                "new_value": "範例文具行",
            }
        ],
    }
    return payload | changes


def test_home_page_renders(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "InvoiceGuard AI" in response.text


def test_static_css_is_served(client: TestClient) -> None:
    response = client.get("/static/css/main.css")

    assert response.status_code == 200


def test_robots_txt_does_not_block_crawling_so_noindex_is_read(client: TestClient) -> None:
    # 不收錄由頁面 noindex 負責；robots.txt 不封鎖，搜尋引擎才讀得到 noindex。
    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert "Allow: /" in response.text


def test_protected_page_redirects_to_login(client: TestClient) -> None:
    response = client.get("/invoices?page=2")

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Finvoices%3Fpage%3D2"


def test_unknown_page_shows_custom_404(client: TestClient) -> None:
    response = client.get("/not-exists")

    assert response.status_code == 404
    assert "找不到頁面" in response.text


def test_invoice_list_renders_api_result(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch_invoices(token: str, **kwargs: Any) -> dict[str, Any]:
        assert token == "test-access-token"
        item = {
            "id": 1,
            "invoice_number": "AB12345678",
            "invoice_date": "2026-10-21",
            "total_amount": "1234.5",
            "status": "flagged",
            "risk_score": 87,
        }
        return {"items": [item], "total": 1, "page": 1, "page_size": 20}

    monkeypatch.setattr(invoices_client, "fetch_invoices", fake_fetch_invoices)

    response = logged_in_client.get("/invoices")

    assert response.status_code == 200
    assert "AB12345678" in response.text
    assert "NT$ 1,234.5" in response.text
    assert "有風險" in response.text


def test_expired_token_redirects_to_login(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch_invoices(token: str, **kwargs: Any) -> dict[str, Any]:
        raise ApiError(401, "UNAUTHORIZED", "請重新登入")

    monkeypatch.setattr(invoices_client, "fetch_invoices", fake_fetch_invoices)

    response = logged_in_client.get("/invoices")

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_login_rejects_cross_site_post(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"email": "a@example.com", "password": "x"},
        headers={"Origin": "https://evil.example.com"},
    )

    assert response.status_code == 403


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_logout_accepts_same_host_origin_behind_https_proxy(
    client: TestClient, scheme: str
) -> None:
    # Vercel 等 proxy 後 ASGI scheme 可能是 http，瀏覽器 Origin 仍是 https；正式模式只比對主機:埠。
    proxied = TestClient(
        client.app, base_url=f"{scheme}://invoiceguard.example", follow_redirects=False
    )

    response = proxied.post("/logout", headers={"Origin": "https://invoiceguard.example"})

    assert response.status_code == 303


@pytest.mark.parametrize(
    "origin",
    ["https://evil.example.com", "https://invoiceguard.example:444", "http://[::1", "null"],
)
def test_logout_rejects_other_host_or_malformed_origin(client: TestClient, origin: str) -> None:
    proxied = TestClient(client.app, base_url="http://invoiceguard.example", follow_redirects=False)

    response = proxied.post("/logout", headers={"Origin": origin})

    assert response.status_code == 403


def test_logout_clears_session_cookie(logged_in_client: TestClient) -> None:
    response = logged_in_client.post("/logout")

    assert response.status_code == 303
    assert 'ig_session=""' in response.headers["set-cookie"]


def test_qa_page_requires_login(client: TestClient) -> None:
    response = client.get("/qa")
    assert response.status_code == 303
    assert "/login?next=" in response.headers["location"]


def test_qa_page_renders_for_logged_in_user(logged_in_client: TestClient) -> None:
    response = logged_in_client.get("/qa")
    assert response.status_code == 200
    assert "問答輔助" in response.text
    assert "營業稅相關規定" in response.text


def test_qa_ask_and_clear(logged_in_client: TestClient) -> None:
    ask_res = logged_in_client.post(
        "/qa/ask",
        data={"question": "如何進行發票申報？"},
    )
    assert ask_res.status_code == 200
    assert "如何進行發票申報？" in ask_res.text

    clear_res = logged_in_client.post("/qa/clear")
    assert clear_res.status_code == 303


def test_qa_sources_toggle(logged_in_client: TestClient) -> None:
    response = logged_in_client.post(
        "/qa/sources",
        data={"source_ids": ["tax", "voucher"]},
    )
    assert response.status_code == 200
    assert "營業稅相關規定" in response.text


def test_user_invoice_flow_steps(logged_in_client: TestClient) -> None:
    for step in range(1, 4):
        response = logged_in_client.get(f"/invoices/1/flow?step={step}")
        assert response.status_code == 200
        assert "發票作業" in response.text


def test_user_invoice_flow_upload_and_correct(logged_in_client: TestClient) -> None:
    upload_res = logged_in_client.post(
        "/invoices/1/flow/upload",
        files={"file": ("invoice_sample.jpg", b"fake-jpg-content", "image/jpeg")},
    )
    assert upload_res.status_code == 303
    assert upload_res.headers["location"] == "/invoices/1/flow?step=2"

    correct_res = logged_in_client.post(
        "/invoices/1/flow/correct",
        data={
            "invoice_number": "AB12345678",
            "invoice_date": "2026-08-15",
            "seller_tax_id": "24681357",
            "buyer_tax_id": "12345678",
            "net_amount": 5000,
        },
    )
    assert correct_res.status_code == 303
    assert correct_res.headers["location"] == "/invoices"


def test_mobile_upload_requires_login(client: TestClient) -> None:
    get_res = client.get("/invoices/mobile-upload")
    assert get_res.status_code == 303
    assert get_res.headers["location"] == "/login?next=%2Finvoices%2Fmobile-upload"

    recognize_res = client.post(
        "/invoices/mobile-recognize", files={"file": ("a.jpg", JPEG, "image/jpeg")}
    )
    assert recognize_res.status_code == 303

    dup_res = client.post("/invoices/check-duplicate", json=DUPLICATE_QUERY)
    assert dup_res.status_code == 303

    upload_res = client.post("/invoices/mobile-upload", json=mobile_payload())
    assert upload_res.status_code == 303


def test_mobile_user_home_redirects_to_login(client: TestClient) -> None:
    response = client.get(
        "/",
        headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X)"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Finvoices%2Fmobile-upload"


def test_mobile_upload_page_renders(logged_in_client: TestClient) -> None:
    response = logged_in_client.get("/invoices/mobile-upload")
    assert response.status_code == 200
    assert "採購拍照上傳" in response.text
    assert "mobile-camera.css" in response.text
    assert "mobile-camera.js" in response.text
    assert 'data-upload-mode="camera"' in response.text
    assert 'id="btn-open-camera"' in response.text
    assert 'accept="image/jpeg,image/png"' in response.text
    assert "繼續拍攝下一張" in response.text


def test_invoice_upload_page_uses_shared_flow_for_local_files(
    logged_in_client: TestClient,
) -> None:
    response = logged_in_client.get("/invoices/upload")

    assert response.status_code == 200
    text = response.text
    assert 'data-upload-mode="file"' in text
    assert 'accept="image/jpeg,image/png,application/pdf"' in text
    assert "mobile-camera.js" in text
    # 與手機頁共用的步驟（預覽、核對、查重、結果）與 PDF 預覽
    for element_id in (
        "step-preview",
        "step-fields",
        "step-confirm",
        "step-success",
        "preview-pdf",
    ):
        assert f'id="{element_id}"' in text
    assert 'id="btn-open-camera"' not in text
    assert "繼續上傳下一張" in text
    assert "disabled>上傳（建置中）" not in text


@pytest.mark.parametrize("path", ["/invoices/upload", "/invoices/mobile-upload"])
def test_upload_result_hides_unplanned_invoice_list_button(
    logged_in_client: TestClient, path: str
) -> None:
    # 發票列表頁尚未規劃（API GET /api/v1/invoices 未實作），上傳完成後不提供「查看發票清單」
    text = logged_in_client.get(path).text

    assert "查看發票清單" not in text
    success_step = text.split('id="step-success"', 1)[1].split("</section>", 1)[0]
    assert 'href="/invoices"' not in success_step


def test_invoice_upload_page_requires_login(client: TestClient) -> None:
    response = client.get("/invoices/upload")

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Finvoices%2Fupload"


def test_recognize_forwards_pdf_from_upload_page(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    pdf = b"%PDF-1.7\nsynthetic-pdf"

    async def recognize_invoice(token: str, **values: Any) -> dict[str, Any]:
        calls.append(values)
        return {"recognition_id": "33333333-3333-4333-8333-333333333333"}

    monkeypatch.setattr(invoices_client, "recognize_invoice", recognize_invoice)
    response = logged_in_client.post(
        "/invoices/mobile-recognize",
        files={"file": ("掃描發票.pdf", pdf, "application/pdf")},
        headers=JSON_ACCEPT,
    )

    assert response.status_code == 200
    assert calls == [
        {"filename": "掃描發票.pdf", "content": pdf, "content_type": "application/pdf"}
    ]


def test_mobile_recognize_forwards_image_to_api(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    recognition = {"recognition_id": "33333333-3333-4333-8333-333333333333", "warnings": []}

    async def recognize_invoice(token: str, **values: Any) -> dict[str, Any]:
        calls.append({"token": token, **values})
        return recognition

    monkeypatch.setattr(invoices_client, "recognize_invoice", recognize_invoice)
    response = logged_in_client.post(
        "/invoices/mobile-recognize", files={"file": ("相機拍攝.jpg", JPEG, "image/jpeg")}
    )

    assert response.status_code == 200
    assert response.json() == recognition
    assert calls == [
        {
            "token": "test-access-token",
            "filename": "相機拍攝.jpg",
            "content": JPEG,
            "content_type": "image/jpeg",
        }
    ]


def test_mobile_recognize_rejects_oversized_image(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def recognize_invoice(token: str, **values: Any) -> dict[str, Any]:
        raise AssertionError("不應呼叫 API")

    monkeypatch.setattr(invoices_client, "recognize_invoice", recognize_invoice)
    response = logged_in_client.post(
        "/invoices/mobile-recognize",
        files={"file": ("big.jpg", JPEG + b"0" * (4 * 1024 * 1024), "image/jpeg")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVOICE_IMAGE_TOO_LARGE"


@pytest.mark.parametrize(
    ("api_status", "expected_status"), [(400, 400), (409, 409), (502, 502), (503, 502)]
)
def test_mobile_endpoints_return_api_errors_as_json(
    logged_in_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    api_status: int,
    expected_status: int,
) -> None:
    async def fail(token: str, *args: Any, **values: Any) -> dict[str, Any]:
        raise ApiError(api_status, "OCR_FAILED", "發票文字辨識失敗，請稍後再試")

    monkeypatch.setattr(invoices_client, "recognize_invoice", fail)
    monkeypatch.setattr(invoices_client, "check_duplicate", fail)
    monkeypatch.setattr(invoices_client, "submit_invoice", fail)
    responses = mobile_posts(logged_in_client, JSON_ACCEPT)

    for response in responses:
        assert response.status_code == expected_status
        assert response.json()["error"]["code"] == "OCR_FAILED"
        assert response.json()["error"]["message"] == "發票文字辨識失敗，請稍後再試"


def test_mobile_recognize_redirects_to_login_when_api_session_expires(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def expired(token: str, **values: Any) -> dict[str, Any]:
        raise ApiError(401, "UNAUTHORIZED", "登入已失效，請重新登入")

    monkeypatch.setattr(invoices_client, "recognize_invoice", expired)
    response = logged_in_client.post(
        "/invoices/mobile-recognize", files={"file": ("a.jpg", JPEG, "image/jpeg")}
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


def test_mobile_check_duplicate_forwards_query(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    async def check_duplicate(token: str, **values: Any) -> dict[str, Any]:
        calls.append(values)
        return {"is_duplicate": True}

    monkeypatch.setattr(invoices_client, "check_duplicate", check_duplicate)
    response = logged_in_client.post("/invoices/check-duplicate", json=DUPLICATE_QUERY)

    assert response.status_code == 200
    assert response.json() == {"is_duplicate": True}
    assert calls == [DUPLICATE_QUERY]


def test_mobile_upload_forwards_confirmed_invoice(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    created = {
        "invoice_id": "44444444-4444-4444-8444-444444444444",
        "status": "pending_department_approval",
    }

    async def submit_invoice(token: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return created

    monkeypatch.setattr(invoices_client, "submit_invoice", submit_invoice)
    response = logged_in_client.post("/invoices/mobile-upload", json=mobile_payload())

    assert response.status_code == 200
    assert response.json() == created
    assert calls == [mobile_payload()]


@pytest.mark.parametrize(
    "payload",
    [
        mobile_payload(use="RD 部門採購設備"),
        mobile_payload(items=[{"item_name": "伺服器硬碟", "line_amount": "5000", "remark": "x"}]),
        {"invoice_number": "CD88889999"},
    ],
    ids=["unknown-field", "unknown-item-field", "missing-fields"],
)
def test_mobile_upload_rejects_unknown_or_missing_fields(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> None:
    async def submit_invoice(token: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("不應呼叫 API")

    monkeypatch.setattr(invoices_client, "submit_invoice", submit_invoice)
    response = logged_in_client.post("/invoices/mobile-upload", json=payload)

    assert response.status_code == 422


def mobile_posts(test_client: TestClient, headers: dict[str, str]) -> list[Any]:
    """依序呼叫手機上傳的辨識、查重、送出三個 POST。"""
    return [
        test_client.post(
            "/invoices/mobile-recognize",
            files={"file": ("a.jpg", JPEG, "image/jpeg")},
            headers=headers,
        ),
        test_client.post("/invoices/check-duplicate", json=DUPLICATE_QUERY, headers=headers),
        test_client.post("/invoices/mobile-upload", json=mobile_payload(), headers=headers),
    ]


def test_mobile_endpoints_reject_cross_site_origin(logged_in_client: TestClient) -> None:
    responses = mobile_posts(logged_in_client, {"Origin": "https://evil.example"})

    assert [response.status_code for response in responses] == [403, 403, 403]


def test_mobile_endpoints_reject_cross_site_origin_as_json(logged_in_client: TestClient) -> None:
    responses = mobile_posts(logged_in_client, {"Origin": "https://evil.example", **JSON_ACCEPT})

    assert [response.status_code for response in responses] == [403, 403, 403]
    assert {response.json()["error"]["code"] for response in responses} == {"FORBIDDEN"}


def test_mobile_session_check_failure_returns_json(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.clients import auth as auth_client

    async def unavailable(token: str) -> dict[str, Any]:
        raise ApiError(503, "SERVICE_UNAVAILABLE", "登入服務暫時無法使用，請稍後再試")

    monkeypatch.setattr(auth_client, "fetch_me", unavailable)
    responses = mobile_posts(logged_in_client, JSON_ACCEPT)

    for response in responses:
        assert response.status_code == 502
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["error"] == {
            "code": "SERVICE_UNAVAILABLE",
            "message": "登入服務暫時無法使用，請稍後再試",
            "details": None,
        }


def test_mobile_session_expiry_still_redirects_to_login(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.clients import auth as auth_client

    async def expired(token: str) -> dict[str, Any]:
        raise ApiError(401, "UNAUTHORIZED", "登入已失效，請重新登入")

    monkeypatch.setattr(auth_client, "fetch_me", expired)

    for response in mobile_posts(logged_in_client, JSON_ACCEPT):
        assert response.status_code == 303
        assert response.headers["location"].startswith("/login?next=")


def test_mobile_upload_validation_error_is_json_without_input(
    logged_in_client: TestClient,
) -> None:
    payload = mobile_payload(seller_name="機密內容" * 60)

    response = logged_in_client.post("/invoices/mobile-upload", json=payload, headers=JSON_ACCEPT)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "機密內容" not in response.text


def test_mobile_upload_shortcut(client: TestClient) -> None:
    response = client.get("/mobile-upload", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/invoices/mobile-upload"


def test_mobile_upload_clients_call_api_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    calls: list[tuple[str, str, dict[str, Any]]] = []

    async def request_json(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        calls.append((method, path, kwargs))
        return {}

    monkeypatch.setattr(invoices_client, "request_json", request_json)
    asyncio.run(
        invoices_client.recognize_invoice(
            "token", filename="a.jpg", content=JPEG, content_type="image/jpeg"
        )
    )
    asyncio.run(invoices_client.check_duplicate("token", **DUPLICATE_QUERY))
    asyncio.run(invoices_client.submit_invoice("token", mobile_payload()))

    assert calls == [
        (
            "POST",
            "/invoices/recognize",
            {"token": "token", "files": {"file": ("a.jpg", JPEG, "image/jpeg")}},
        ),
        ("POST", "/invoices/check-duplicate", {"token": "token", "json": DUPLICATE_QUERY}),
        ("POST", "/invoices", {"token": "token", "json": mobile_payload()}),
    ]


def test_form_validation_error_shows_page_without_input(client: TestClient) -> None:
    response = client.post(
        "/login", data={"email": "user@example.com"}, headers={"Accept": "text/html"}
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("text/html")
    assert "user@example.com" not in response.text


def test_unknown_route_follows_accept_header(client: TestClient) -> None:
    json_response = client.get("/no-such-page", headers=JSON_ACCEPT)
    html_response = client.get("/no-such-page")

    assert json_response.status_code == 404
    assert json_response.json()["error"]["code"] == "NOT_FOUND"
    assert html_response.status_code == 404
    assert html_response.headers["content-type"].startswith("text/html")
