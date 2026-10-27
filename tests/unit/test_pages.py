"""測試目標：頁面路由、登入保護、錯誤頁、靜態檔"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.clients import invoices as invoices_client
from app.clients.base import ApiError


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
