"""測試目標：退回補正頁（GET／POST /invoices/{uuid}/correct）的前台行為（Mock：真實的 Router／Client／樣板，
只把 HTTP 傳輸換成 MockTransport；不連任何服務）。

只證明前台對符合 API 契約的回應行為正確；與真實 API／PostgreSQL 的整合另見 API 專案整合測試與手動端到端紀錄。
"""

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from stage1_detail import install_mock_api

ID = "24ab951f-1c13-4d43-9034-82ae52792b87"
ITEM = "11111111-1111-4111-8111-111111111111"
RETURN_ITEM = "22222222-2222-4222-8222-222222222222"


def _info(**overrides: Any) -> dict[str, Any]:
    ref = {"field_scope": "header", "line_no": None, "item_id": None}
    info: dict[str, Any] = {
        "invoice_id": ID,
        "status": "returned_to_applicant",
        "submission_round": 3,
        "can_resubmit": True,
        "requires_void": False,
        "resubmit_blocked_reason": None,
        "editable_fields": [
            {**ref, "field_name": "tax_amount"},
            {**ref, "field_name": "total_amount"},
        ],
        "return_items": [
            {
                "return_item_id": RETURN_ITEM,
                "item_kind": "field",
                "target": {**ref, "field_name": "tax_amount"},
                "reason": "稅額應為 50",
                "allowed_fields": [{**ref, "field_name": "total_amount"}],
                "status": "open",
            }
        ],
        "previous": {
            "invoice_track": "AB",
            "invoice_number": "12345678",
            "invoice_date": "2026-10-15",
            "seller_tax_id": "12345675",
            "seller_name": "甲公司",
            "buyer_tax_id": "27601907",
            "buyer_name": "乙公司",
            "tax_type": "taxable",
            "sales_amount": "1000",
            "tax_amount": "40",
            "total_amount": "1040",
            "total_amount_zh": None,
            "items": [
                {
                    "item_id": ITEM,
                    "line_no": 1,
                    "item_name": "品項1",
                    "quantity": "1",
                    "unit_price": "1000",
                    "line_amount": "1000",
                }
            ],
        },
    }
    return info | overrides


def test_correct_page_prefills_previous_data_and_only_authorized_fields_are_editable(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = install_mock_api(monkeypatch, lambda request: httpx.Response(200, json=_info()))

    response = logged_in_client.get(f"/invoices/{ID}/correct")

    assert response.status_code == 200
    html = response.text
    assert seen[-1].method == "GET" and seen[-1].url.path.endswith(f"/invoices/{ID}/return-items")
    assert 'data-expected-round="3"' in html and "稅額應為 50" in html
    assert 'id="f-tax_amount"' in html and 'value="40"' in html
    # 只有授權欄位沒有 readonly；其他欄位唯讀
    tax = html.split('id="f-tax_amount"')[1].split(">")[0]
    seller = html.split('id="f-seller_name"')[1].split(">")[0]
    assert "readonly" not in tax and "readonly" in seller
    assert f'data-item-id="{ITEM}"' in html and "invoice-correct.js" in html


def test_image_problem_shows_void_notice_and_no_form(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = _info(
        can_resubmit=False,
        requires_void=True,
        editable_fields=[],
        return_items=[
            {
                "return_item_id": RETURN_ITEM,
                "item_kind": "image",
                "target": None,
                "reason": "影像模糊",
                "allowed_fields": [],
                "status": "open",
            }
        ],
    )
    install_mock_api(monkeypatch, lambda request: httpx.Response(200, json=info))

    html = logged_in_client.get(f"/invoices/{ID}/correct").text

    assert "data-requires-void" in html and "影像模糊" in html
    assert 'id="correct-form"' not in html


def test_non_uuid_id_is_not_forwarded_to_the_api(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = install_mock_api(monkeypatch, lambda request: httpx.Response(200, json=_info()))

    assert logged_in_client.get("/invoices/1/correct").status_code == 404
    assert seen == []


def test_submit_forwards_the_payload_unchanged_and_returns_the_api_result(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = {"invoice_id": ID, "submission_round": 4, "replayed": False}
    seen = install_mock_api(monkeypatch, lambda request: httpx.Response(201, json=result))
    payload = {
        "idempotency_key": "k",
        "expected_round": 3,
        "changes": [{"field_name": "tax_amount"}],
    }

    response = logged_in_client.post(
        f"/invoices/{ID}/correct", json=payload, headers={"Origin": "http://testserver"}
    )

    assert response.status_code == 200 and response.json() == result
    assert seen[-1].method == "POST" and seen[-1].url.path.endswith(f"/invoices/{ID}/resubmit")
    assert __import__("json").loads(seen[-1].content) == payload


def test_submit_without_same_origin_is_refused(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = install_mock_api(monkeypatch, lambda request: httpx.Response(201, json={}))

    response = logged_in_client.post(
        f"/invoices/{ID}/correct", json={}, headers={"Origin": "http://evil.example"}
    )

    assert response.status_code >= 400 and seen == []


def test_api_conflict_is_returned_as_json_error(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {
        "error": {"code": "RESUBMIT_ROUND_STALE", "message": "案件已有較新的輪次", "details": None}
    }
    install_mock_api(monkeypatch, lambda request: httpx.Response(409, json=body))

    response = logged_in_client.post(
        f"/invoices/{ID}/correct",
        json={},
        headers={"Origin": "http://testserver", "Accept": "application/json"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESUBMIT_ROUND_STALE"


def test_correct_script_asks_for_json_errors() -> None:
    from pathlib import Path

    script = Path("app/static/js/invoice-correct.js").read_text(encoding="utf-8")

    assert "Accept: 'application/json'" in script


def test_void_forwards_to_the_api_and_requires_same_origin(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = install_mock_api(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"invoice_id": ID, "status": "voided", "submission_round": 1}
        ),
    )

    refused = logged_in_client.post(
        f"/invoices/{ID}/void",
        json={"expected_round": 1},
        headers={"Origin": "http://evil.example"},
    )
    ok = logged_in_client.post(
        f"/invoices/{ID}/void", json={"expected_round": 1}, headers={"Origin": "http://testserver"}
    )

    assert refused.status_code >= 400 and ok.status_code == 200 and ok.json()["status"] == "voided"
    assert len(seen) == 1 and seen[0].url.path.endswith(f"/invoices/{ID}/void")


def test_void_with_an_unexpected_api_body_is_rejected_as_invalid_upstream(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_mock_api(monkeypatch, lambda request: httpx.Response(200, json={"status": "approved"}))

    response = logged_in_client.post(
        f"/invoices/{ID}/void",
        json={"expected_round": 1},
        headers={"Origin": "http://testserver", "Accept": "application/json"},
    )

    assert response.status_code == 502


def test_image_problem_page_offers_void_and_reupload_links(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = _info(
        can_resubmit=False,
        requires_void=True,
        editable_fields=[],
        return_items=[
            {
                "return_item_id": RETURN_ITEM,
                "item_kind": "image",
                "target": None,
                "reason": "影像模糊",
                "allowed_fields": [],
                "status": "open",
            }
        ],
    )
    install_mock_api(monkeypatch, lambda request: httpx.Response(200, json=info))

    html = logged_in_client.get(f"/invoices/{ID}/correct").text

    assert (
        'id="void-button"' in html
        and "/invoices/mobile-upload" in html
        and "/invoices/upload" in html
    )
