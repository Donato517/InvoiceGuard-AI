"""
測試輔助：Stage 1 發票詳情（GET /api/v1/invoices/{invoice_id}）的合成 Mock 回應。
規則：
    - 依 InvoiceDetailRead（InvoiceGuard-AI-API app/schemas/invoice_detail.py:42-67，
      後端 commit c0e8a0248a24338076e8036f6f7a3122784ea7f9）整理的離線契約快照；
      不代表與真實 API 一致，也不連任何服務。
    - 全部是虛構資料。
"""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

API_DETAIL_ID = "123e4567-e89b-42d3-a456-426614174000"

# Stage 1 回應的頂層欄位（全部都會出現；可空的欄位以 null 表示）
STAGE1_DETAIL_KEYS = frozenset(
    {
        "invoice_id",
        "status",
        "submission_round",
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
        "items",
        "modified_fields",
        "warnings",
        "file",
    }
)


def build_api_detail(**overrides: Any) -> dict[str, Any]:
    """符合 Stage 1 契約的合成發票詳情；overrides 直接覆蓋頂層欄位（每次呼叫都是獨立副本）。"""
    detail: dict[str, Any] = {
        "invoice_id": API_DETAIL_ID,
        "status": "pending_department_approval",
        "submission_round": 1,
        "submitted_at": "2026-10-30T01:30:00Z",
        "tax_period": "202610",
        "invoice_track": "CD",
        "invoice_number": "75670992",
        "invoice_date": "2026-10-15",
        "seller_tax_id": "27601907",
        "seller_name": "範例文具行",
        "buyer_tax_id": "12345678",
        "buyer_name": "範例科技股份有限公司",
        "tax_type": "taxable",
        "sales_amount": "6000.00",
        "tax_amount": "300.00",
        "total_amount": "6300.00",
        "total_amount_zh": "陸仟參佰元整",
        "items": [
            {
                "line_no": 1,
                "item_name": "辦公用品",
                "quantity": "2.0000",
                "unit_price": "1000.00",
                "line_amount": "2000.00",
            },
            {
                "line_no": 2,
                "item_name": "文具",
                "quantity": "1.0000",
                "unit_price": "4000.00",
                "line_amount": "4000.00",
            },
        ],
        "modified_fields": [],
        "warnings": [],
        "file": {
            "mime_type": "image/jpeg",
            "original_filename": "invoice.jpg",
            "size_bytes": 123456,
            "version_no": 1,
        },
    }
    detail.update(overrides)
    return detail


def install_mock_api(
    monkeypatch: pytest.MonkeyPatch, responder: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    """讓真實的 API Client 與 request_json 收到指定的 HTTP 回應（只替換傳輸層，不連任何服務）。"""
    seen: list[httpx.Request] = []
    real_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responder(request)

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return seen
