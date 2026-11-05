"""範例取用前台：Session 轉送、只讀呈現、圖檔限制與登入保護。"""

import asyncio
from uuid import uuid4

import httpx
import pytest

from app.clients import base, invoices


def test_reference_page_is_read_only(
    logged_in_client: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """授權前台使用者可查啟用範例，原文安全轉義且不提供修改動作。"""

    async def references(token: str, tax_id: str, layout: str) -> list[dict[str, object]]:
        assert tax_id == "12345678"
        return [
            {
                "sample_id": str(uuid4()),
                "revision_id": str(uuid4()),
                "title": "<script>bad</script>",
                "supplier_name": "測試",
                "layout": "A",
                "writing": "手寫",
                "truths": [],
            }
        ]

    monkeypatch.setattr(invoices, "showcase_references", references)
    response = logged_in_client.get("/invoices/showcase-reference?tax_id=12345678")
    assert response.status_code == 200
    assert "&lt;script&gt;" in response.text
    assert "<script>bad</script>" not in response.text
    assert "確認並啟用" not in response.text
    assert logged_in_client.get("/invoices/showcase-reference?tax_id=invalid").status_code == 400


def test_anonymous_reference_is_denied(client: object) -> None:
    """參考入口不是公開圖片庫。"""
    response = client.get("/invoices/showcase-reference?tax_id=12345678")
    assert response.status_code == 303


def test_image_client_transfers_token_and_rejects_nonimage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token 只透過伺服器 Header，圖片類型及過大回應被拒。"""
    original = httpx.AsyncClient
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=b"image", headers={"content-type": "image/png"})

    monkeypatch.setattr(
        base.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)),
    )
    assert asyncio.run(base.request_image("/showcase-references/s/r/file", token="synthetic")) == (
        b"image",
        "image/png",
    )
    assert calls[0].headers["Authorization"] == "Bearer synthetic"
    assert "synthetic" not in str(calls[0].url)

    def invalid(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not an image")

    monkeypatch.setattr(
        base.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(invalid)),
    )
    with pytest.raises(base.ApiError):
        asyncio.run(base.request_image("/showcase-references/s/r/file", token="synthetic"))
