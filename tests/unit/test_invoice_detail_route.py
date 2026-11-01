"""測試目標：正式詳情路由 GET /invoices/{uuid} 的端到端行為（Mock：真實的 Router／API Client／Adapter／Builder／樣板，
只把 HTTP 傳輸換成 MockTransport；不連任何服務）。

這些測試證明程式在符合 Stage 1 契約的 Mock 回應下行為正確，不代表與真實 API／PostgreSQL 整合通過。
"""

import inspect
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from stage1_detail import API_DETAIL_ID, build_api_detail, install_mock_api

import app.routers.invoices as router_module
from app.utils.demo_invoice import build_demo_invoice

URL = f"/invoices/{API_DETAIL_ID}"
SECRET = "SECRET-RAW-BODY"


def _api(monkeypatch: pytest.MonkeyPatch, body: Any, status: int = 200) -> list[httpx.Request]:
    return install_mock_api(monkeypatch, lambda request: httpx.Response(status, json=body))


def _rec(
    scope: str, name: str, line_no: Any, original: Any, submitted: Any = None
) -> dict[str, Any]:
    return {
        "field_scope": scope,
        "line_no": line_no,
        "field_name": name,
        "ai_original_value": original,
        "submitted_value": submitted,
    }


def _item(line_no: int, name: str) -> dict[str, Any]:
    return {
        "line_no": line_no,
        "item_name": name,
        "quantity": "1",
        "unit_price": "10",
        "line_amount": "10",
    }


# ---- 正常顯示與請求內容 ----


def test_valid_stage1_response_renders_read_only_page(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _api(monkeypatch, build_api_detail())

    response = logged_in_client.get(URL)

    assert response.status_code == 200
    html = response.text
    for text in ("CD75670992", "範例科技股份有限公司", "應稅", "6000.00", "27601907", "辦公用品"):
        assert text in html
    assert "待單位核准" in html and "第 1 輪" in html
    assert 'id="submit-control"' not in html and 'data-readonly-note="true"' in html
    assert "data-demo-banner" not in html
    # 請求：只帶 Bearer token，GET 該案件；不帶部門參數
    assert [(r.method, r.url.path.rsplit("/", 1)[-1]) for r in seen] == [("GET", API_DETAIL_ID)]
    assert seen[0].url.query == b""
    assert all("department" not in key.lower() for key in seen[0].headers)
    assert "test-access-token" not in html


def test_fields_without_an_api_source_show_a_dash_and_nothing_is_invented(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _api(monkeypatch, build_api_detail())

    html = logged_in_client.get(URL).text

    for field_id in ("F01", "F13"):  # form_type、remark：Stage 1 沒有這兩個欄位
        block = html.split(f'data-field-id="{field_id}"')[1].split("</section>")[0]
        assert "field-block__value" in block and ">-" in " ".join(block.split()).replace(" ", "")
    assert "三聯式" not in html
    assert 'data-original-status="unchanged"' not in html
    assert "沒有 AI 原始快照" in html


def test_file_null_and_file_metadata_never_leak_paths_or_names(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _api(monkeypatch, build_api_detail(file=None))
    assert logged_in_client.get(URL).status_code == 200

    _api(monkeypatch, build_api_detail())
    html = logged_in_client.get(URL).text

    assert "invoice.jpg" not in html and "storage" not in html.lower() and "<img" not in html


def test_nullable_fields_render_without_error(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    nullable = {
        key: None
        for key in (
            "submitted_at",
            "tax_period",
            "invoice_track",
            "invoice_number",
            "invoice_date",
            "seller_tax_id",
            "seller_name",
            "buyer_tax_id",
            "buyer_name",
            "tax_type",
            "sales_amount",
            "tax_amount",
            "total_amount",
            "total_amount_zh",
            "file",
        )
    }
    _api(monkeypatch, build_api_detail(items=[], **nullable))

    response = logged_in_client.get(URL)

    assert response.status_code == 200
    assert "沒有明細資料" in response.text


# ---- 修改紀錄的頁面呈現 ----


def test_modification_records_are_rendered_in_their_places(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _api(
        monkeypatch,
        build_api_detail(
            items=[_item(1, "甲"), _item(5, "乙")],
            sales_amount="1000.00",
            modified_fields=[
                _rec("header", "sales_amount", None, "1000", "1000"),
                _rec("header", "invoice_track", None, "AB"),
                _rec("item", "item_name", 5, "舊乙"),
                _rec("item", "item_name", 9, "不存在的列"),
                _rec("header", "deleted_item_2", None, {"item_name": "已刪品", "quantity": "3"}),
                _rec("future", "mystery", None, {"a": [1]}),
            ],
        ),
    )

    html = logged_in_client.get(URL).text

    assert "AI 原值只涵蓋本輪有修改紀錄的欄位（共 6 筆紀錄）" in html
    assert "1000.00" in html and "AI 原值：1000）" in html  # 顯示值與紀錄標準值各自原樣呈現
    assert "已修改・字軌（AI 原值：AB）" in html
    # 第 5 號明細（第 2 列）有備註；第 1 列沒有
    rows = html.split('data-field-group="items"')[1].split("</table>")[0]
    row1, row2 = rows.split('data-source-line-no="')[1:3]
    assert row1.startswith("1") and "本輪無修改紀錄" in row1
    assert row2.startswith("5") and "已修改・品名／用途（AI 原值：舊乙）" in row2
    # 對不到的序號不掛到任何列
    assert "無法對應到目前明細的修改紀錄" in html and "不存在的列" in html
    assert "不存在的列" not in rows
    # 已刪除的 AI 明細獨立呈現
    deleted = html.split('data-deleted-items="true"')[1].split("</section>")[0]
    assert "AI 第 2 筆" in deleted and "已刪品" in deleted and "與上表的明細序號無關" in deleted
    assert "已刪品" not in rows
    # 無法歸類的紀錄原樣列出
    other = html.split('data-other-modifications="true"')[1].split("</section>")[0]
    assert "mystery" in other and "（結構化值，已省略）" in other


def test_values_are_escaped_and_long_text_is_marked(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _api(
        monkeypatch,
        build_api_detail(
            buyer_name="<b>買方</b>",
            modified_fields=[
                _rec("header", "buyer_name", None, "<script>alert(1)</script>"),
                _rec("header", "seller_name", None, "字" * 500),
                _rec("future", "<img src=x onerror=alert(1)>", None, "x"),
            ],
        ),
    )

    html = logged_in_client.get(URL).text

    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "<b>買方</b>" not in html
    assert "<img src=x" not in html
    assert "…（已截斷）" in html and "字" * 201 not in html


def test_no_record_means_no_modified_label_anywhere(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _api(monkeypatch, build_api_detail(modified_fields=[]))

    html = logged_in_client.get(URL).text

    assert "已修改" not in html
    assert "data-modified-note" not in html
    assert "共 0 筆紀錄" in html


# ---- 上游異常：一律錯誤頁，不顯示成正常案件，不回退展示資料 ----


@pytest.mark.parametrize(
    "responder",
    [
        lambda request: httpx.Response(200, content=f"<html>{SECRET}</html>".encode()),
        lambda request: httpx.Response(200, content=b""),
        lambda request: httpx.Response(200, content=b"\xff\xfe\x00{"),
        lambda request: httpx.Response(200, json=[]),
        lambda request: httpx.Response(200, json={}),
        lambda request: httpx.Response(200, json=build_demo_invoice()),  # fixture 格式
        lambda request: httpx.Response(200, json=build_api_detail(submission_round=True)),
        lambda request: httpx.Response(200, json=build_api_detail(items="x")),
        lambda request: httpx.Response(200, json=build_api_detail(modified_fields=None)),
        lambda request: httpx.Response(
            200, json=build_api_detail(invoice_id="123e4567-e89b-42d3-a456-426614174999")
        ),
    ],
    ids=[
        "html",
        "empty",
        "bom-garbage",
        "array",
        "empty-object",
        "fixture-shaped",
        "round-bool",
        "items-str",
        "modified-null",
        "other-case",
    ],
)
def test_invalid_upstream_response_is_a_502_page_never_an_empty_case(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, responder: Any
) -> None:
    install_mock_api(monkeypatch, responder)

    response = logged_in_client.get(URL)

    assert response.status_code == 502
    assert "服務回應異常，請稍後再試" in response.text
    for marker in (SECRET, "發票詳情 #", "甲乙示範", "範例科技", 'id="submit-control"'):
        assert marker not in response.text


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (404, "NOT_FOUND", 404),
        (422, "VALIDATION_ERROR", 422),
        (500, "INVOICE_DATA_INVALID", 502),
        (500, "INTERNAL_ERROR", 502),
        (503, "SERVICE_UNAVAILABLE", 502),
    ],
)
def test_api_error_responses_become_error_pages(
    logged_in_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    code: str,
    expected: int,
) -> None:
    body = {"error": {"code": code, "message": "後端訊息", "details": None}}
    _api(monkeypatch, body, status)

    response = logged_in_client.get(URL)

    assert response.status_code == expected
    assert "後端訊息" in response.text
    assert "發票詳情 #" not in response.text


def test_api_401_clears_login_and_redirects(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {"error": {"code": "UNAUTHORIZED", "message": "請重新登入", "details": None}}
    _api(monkeypatch, body, 401)

    response = logged_in_client.get(URL)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


@pytest.mark.parametrize("exception", [httpx.ConnectError("x"), httpx.ReadTimeout("x")])
def test_connection_failure_and_timeout_are_error_pages(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, exception: Exception
) -> None:
    def raise_it(request: httpx.Request) -> httpx.Response:
        raise exception

    install_mock_api(monkeypatch, raise_it)

    response = logged_in_client.get(URL)

    assert response.status_code == 502
    assert "服務暫時無法連線" in response.text


def test_non_uuid_ids_are_404_without_calling_the_api(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _api(monkeypatch, build_api_detail())

    for bad in ("7", "0007", "9" * 18, "abc", "../etc"):
        assert logged_in_client.get(f"/invoices/{bad}").status_code == 404

    assert seen == []


def test_requires_login(client: TestClient) -> None:
    response = client.get(URL)

    assert response.status_code == 303 and response.headers["location"].startswith("/login")


# ---- 隔離：正式路徑與展示資料 ----


def test_formal_route_source_never_references_demo_data() -> None:
    source = inspect.getsource(router_module.invoice_detail)

    # is_demo=False 是傳給樣板的旗標；其餘不得出現 demo（例如 build_demo_invoice、DEMO_INVOICE_ID）
    assert "demo" not in source.lower().replace("is_demo", "")
    assert "except" not in source.replace("except InvoiceDetailFormatError", "")


def test_demo_page_is_unchanged_by_the_formal_changes(logged_in_client: TestClient) -> None:
    html = logged_in_client.get("/invoices/demo/detail").text

    assert 'data-demo-banner="true"' in html
    assert 'data-demo-submit-note="true"' in html
    assert "data-readonly-note" not in html and "data-modification-notice" not in html
    assert "data-deleted-items" not in html and "data-other-modifications" not in html
    assert 'id="submit-control"' not in html
    assert "AI 原值：甲乙公司" in html
