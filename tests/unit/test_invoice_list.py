"""測試目標：我的發票列表（前台）——API Client 的契約檢查、顯示資料整理、GET /invoices 路由端到端。

Mock：真實的 Router／API Client／View／樣板，只把 HTTP 傳輸換成 MockTransport；不連任何服務。
這些測試證明程式在符合 API 列表契約的 Mock 回應下行為正確，不代表與真實 API／PostgreSQL 整合通過。
"""

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient
from stage1_detail import install_mock_api

from app.clients import invoices as invoices_client
from app.clients.base import ApiError
from app.utils.invoice_list_view import build_list_view, normalize_status, page_numbers
from app.utils.invoice_status import APPROVAL_STATUS_LABEL

ID_1 = "11111111-1111-4111-8111-111111111111"
ID_2 = "22222222-2222-4222-8222-222222222222"


def item(invoice_id: str = ID_1, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "invoice_id": invoice_id,
        "status": "pending_department_approval",
        "submission_round": 1,
        "submitted_at": "2026-10-20T02:00:00Z",
        "invoice_track": "AB",
        "invoice_number": "12345678",
        "invoice_date": "2026-10-01",
        "seller_name": "賣方",
        "total_amount": "1050.00",
    }
    data.update(overrides)
    return data


def page_body(items: list[dict[str, Any]], total: int | None = None, page: int = 1, size: int = 20):
    return {
        "items": items,
        "total": len(items) if total is None else total,
        "page": page,
        "page_size": size,
    }


def _api(monkeypatch: pytest.MonkeyPatch, body: Any, status: int = 200) -> list[httpx.Request]:
    return install_mock_api(monkeypatch, lambda request: httpx.Response(status, json=body))


# ---- API Client：請求內容與契約檢查 ----


@pytest.mark.anyio
async def test_client_sends_page_size_and_status(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _api(monkeypatch, page_body([], page=3, size=20))
    result = await invoices_client.fetch_invoices("tok", page=3, page_size=20, status="approved")
    assert result["page"] == 3
    query = parse_qs(seen[0].url.query.decode())
    assert query == {"page": ["3"], "page_size": ["20"], "status": ["approved"]}
    assert seen[0].url.path.endswith("/invoices")
    assert seen[0].headers["authorization"] == "Bearer tok"


@pytest.mark.anyio
async def test_client_omits_status_when_all(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _api(monkeypatch, page_body([]))
    await invoices_client.fetch_invoices("tok")
    assert "status" not in parse_qs(seen[0].url.query.decode())


BAD_BODIES: list[tuple[str, Any]] = [
    ("not_object", []),
    ("items_missing", {"total": 0, "page": 1, "page_size": 20}),
    ("total_negative", {"items": [], "total": -1, "page": 1, "page_size": 20}),
    ("total_bool", {"items": [], "total": True, "page": 1, "page_size": 20}),
    ("total_str", {"items": [], "total": "0", "page": 1, "page_size": 20}),
    ("page_mismatch", page_body([], page=2)),
    ("page_size_mismatch", page_body([], size=50)),
    ("too_many_items", page_body([item(ID_1), item(ID_2)], total=1)),
    ("item_not_object", page_body(["x"], total=1)),
    ("id_not_uuid", page_body([item("123")])),
    ("id_int", page_body([item(1)])),
    ("status_missing", page_body([{k: v for k, v in item().items() if k != "status"}])),
    ("round_negative", page_body([item(submission_round=-1)])),
    ("round_bool", page_body([item(submission_round=True)])),
    ("amount_float", page_body([item(total_amount=1050.5)])),
    ("text_int", page_body([item(seller_name=5)])),
]


@pytest.mark.anyio
@pytest.mark.parametrize(("name", "body"), BAD_BODIES, ids=[n for n, _ in BAD_BODIES])
async def test_client_rejects_contract_violations(
    monkeypatch: pytest.MonkeyPatch, name: str, body: Any
) -> None:
    _api(monkeypatch, body)
    with pytest.raises(ApiError) as exc:
        await invoices_client.fetch_invoices("tok")
    assert exc.value.status_code == 502
    assert exc.value.code == "INVALID_UPSTREAM_RESPONSE"


@pytest.mark.anyio
async def test_client_rejects_non_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    install_mock_api(monkeypatch, lambda r: httpx.Response(200, content=b"<html>SECRET-RAW</html>"))
    with pytest.raises(ApiError) as exc:
        await invoices_client.fetch_invoices("tok")
    assert exc.value.code == "INVALID_UPSTREAM_RESPONSE"
    assert "SECRET" not in exc.value.message


@pytest.mark.anyio
async def test_client_accepts_null_fields_and_unknown_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = item(
        status="future_status",
        submitted_at=None,
        invoice_track=None,
        invoice_number=None,
        invoice_date=None,
        seller_name=None,
        total_amount=None,
        submission_round=0,
    )
    _api(monkeypatch, page_body([row]))
    result = await invoices_client.fetch_invoices("tok")
    assert result["items"][0]["status"] == "future_status"


# ---- 顯示資料整理 ----


def test_normalize_status_accepts_only_nine_codes() -> None:
    assert len(APPROVAL_STATUS_LABEL) == 9
    for code in APPROVAL_STATUS_LABEL:
        assert normalize_status(code) == code
    for bad in (None, "", "pending", "passed", "APPROVED", "approved ", "x"):
        assert normalize_status(bad) is None


def test_page_numbers_window_and_gaps() -> None:
    assert page_numbers(1, 1) == [1]
    assert page_numbers(1, 3) == [1, 2, 3]
    assert page_numbers(1, 10) == [1, 2, 3, None, 10]
    assert page_numbers(5, 10) == [1, None, 3, 4, 5, 6, 7, None, 10]
    assert page_numbers(10, 10) == [1, None, 8, 9, 10]


def test_build_list_view_rows_and_pages() -> None:
    view = build_list_view(
        page_body([item(), item(ID_2, status="approved", submission_round=0)], total=45, size=20)
    )
    assert view["total_pages"] == 3
    first, second = view["rows"]
    assert first["number"] == "AB12345678"
    assert first["status"].label == "待單位核准" and first["tone"] == "warning"
    assert first["round_text"] == "第 1 輪"
    assert second["tone"] == "success" and second["round_text"] == "草稿（尚未提交）"


def test_build_list_view_missing_number_and_unknown_status() -> None:
    row = item(status="mystery", invoice_track=None, invoice_number=None)
    view = build_list_view(page_body([row]))
    assert view["rows"][0]["number"] == "-"
    assert view["rows"][0]["status"].label == "未知狀態（mystery）"
    assert view["rows"][0]["tone"] == ""


def test_build_list_view_empty_has_one_page() -> None:
    view = build_list_view(page_body([]))
    assert view["rows"] == [] and view["total_pages"] == 1 and view["pages"] == [1]


# ---- 路由 GET /invoices（Mock 傳輸）----


def test_route_renders_rows_with_uuid_links_and_no_risk_score(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _api(monkeypatch, page_body([item(), item(ID_2, status="approved")]))
    response = logged_in_client.get("/invoices")
    assert response.status_code == 200
    html = response.text
    assert f'href="/invoices/{ID_1}"' in html and f'href="/invoices/{ID_2}"' in html
    assert "AB12345678" in html and "NT$ 1,050" in html and "已核准" in html
    table = html[html.index('id="invoice-table"') :]
    assert "風險" not in table and "risk" not in table.lower()
    assert "2026/10/20 10:00" in html  # 台灣時間
    query = parse_qs(seen[0].url.query.decode())
    assert query["page"] == ["1"] and query["page_size"] == ["20"] and "status" not in query


def test_route_select_lists_nine_statuses_and_keeps_selection(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _api(monkeypatch, page_body([item(status="approved")]))
    html = logged_in_client.get("/invoices?status=approved").text
    for code, label in APPROVAL_STATUS_LABEL.items():
        assert f'value="{code}"' in html and label in html
    assert 'value="approved" selected' in html
    assert parse_qs(seen[0].url.query.decode())["status"] == ["approved"]


@pytest.mark.parametrize("bad", ["pending", "passed", "x'--", "APPROVED"])
def test_route_ignores_illegal_status_and_does_not_forward_it(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    seen = _api(monkeypatch, page_body([]))
    response = logged_in_client.get("/invoices", params={"status": bad})
    assert response.status_code == 200
    assert "status" not in parse_qs(seen[0].url.query.decode())


def test_route_empty_list_shows_upload_hint(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _api(monkeypatch, page_body([]))
    html = logged_in_client.get("/invoices").text
    assert "目前沒有發票" in html and "/invoices/upload" in html


def test_route_empty_filtered_list_offers_all(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _api(monkeypatch, page_body([]))
    html = logged_in_client.get("/invoices?status=voided").text
    assert "沒有符合這個狀態的發票" in html


def test_route_page_beyond_last_shows_back_link(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _api(monkeypatch, page_body([], total=5, page=4))
    html = logged_in_client.get("/invoices?page=4").text
    assert "這一頁沒有資料" in html


def test_route_pagination_links_keep_status(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _api(monkeypatch, page_body([item()], total=60, page=2), status=200)
    html = logged_in_client.get("/invoices?page=2&status=approved").text
    assert 'href="/invoices?page=3&status=approved"' in html
    assert 'aria-current="page"' in html and "共 60 張" in html


@pytest.mark.parametrize("bad_page", ["0", "-1", "x", "10001"])
def test_route_invalid_page_is_422_without_calling_api(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, bad_page: str
) -> None:
    seen = _api(monkeypatch, page_body([]))
    assert logged_in_client.get("/invoices", params={"page": bad_page}).status_code == 422
    assert seen == []


def test_route_api_401_redirects_to_login(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _api(monkeypatch, {"error": {"code": "UNAUTHORIZED", "message": "x", "details": None}}, 401)
    response = logged_in_client.get("/invoices")
    assert response.status_code == 303 and response.headers["location"].startswith("/login")


def test_route_without_login_redirects_before_calling_api(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _api(monkeypatch, page_body([]))
    response = client.get("/invoices")
    assert response.status_code == 303 and seen == []


@pytest.mark.parametrize("status", [500, 503])
def test_route_api_failure_shows_error_page_not_empty_list(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    _api(
        monkeypatch,
        {"error": {"code": "INTERNAL_ERROR", "message": "boom", "details": None}},
        status,
    )
    response = logged_in_client.get("/invoices")
    assert response.status_code == 502
    assert "目前沒有發票" not in response.text


def test_route_malformed_response_shows_error_page(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _api(monkeypatch, page_body([item("not-a-uuid")]))
    response = logged_in_client.get("/invoices")
    assert response.status_code == 502
    assert "not-a-uuid" not in response.text


def test_route_connection_failure_shows_error_page(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    install_mock_api(monkeypatch, boom)
    response = logged_in_client.get("/invoices")
    assert response.status_code in (502, 503)
