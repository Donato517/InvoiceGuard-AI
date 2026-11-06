"""測試目標：多頁 PDF 找發票頁——前台轉送路由（POST /invoices/pdf-pages/classify）與上傳頁載入 pdf.js 的設定。

範圍：API client 以替身取代，不連真實 API；挑頁邏輯本身的測試在 tests/js/pdf_invoice_page.test.mjs。
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.clients import invoices as invoices_client

ROOT = Path(__file__).resolve().parents[2]
JPEG = b"\xff\xd8\xff\xe0synthetic-jpeg"
URL = "/invoices/pdf-pages/classify"


def _files(count: int, content: bytes = JPEG) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (f"page_{n}.jpg", content, "image/jpeg")) for n in range(1, count + 1)]


def test_classify_forwards_page_images_in_order(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    result = {"pages": [{"index": 1, "is_triplicate_invoice": True, "copy_no": 2}], "model": "m"}

    async def classify(token: str, **values: Any) -> dict[str, Any]:
        calls.append({"token": token, **values})
        return result

    monkeypatch.setattr(invoices_client, "classify_pdf_pages", classify)
    response = logged_in_client.post(URL, files=_files(2))

    assert response.status_code == 200
    assert response.json() == result
    assert calls == [
        {
            "token": "test-access-token",
            "images": [
                ("page_1.jpg", JPEG, "image/jpeg"),
                ("page_2.jpg", JPEG, "image/jpeg"),
            ],
        }
    ]


@pytest.mark.parametrize(
    ("files", "code"),
    [
        (_files(10), "INVOICE_PAGE_COUNT_INVALID"),
        (_files(1, JPEG + b"0" * (1536 * 1024)), "INVOICE_IMAGE_TOO_LARGE"),
        (_files(4, JPEG + b"0" * (1100 * 1024)), "INVOICE_IMAGE_TOO_LARGE"),  # 合計超過 4 MB
    ],
)
def test_classify_rejects_invalid_batches_without_calling_api(
    logged_in_client: TestClient, monkeypatch: pytest.MonkeyPatch, files: list[Any], code: str
) -> None:
    async def classify(token: str, **values: Any) -> dict[str, Any]:
        raise AssertionError("不應呼叫 API")

    monkeypatch.setattr(invoices_client, "classify_pdf_pages", classify)
    response = logged_in_client.post(URL, files=files)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code


def test_classify_requires_login(client: TestClient) -> None:
    response = client.post(URL, files=_files(1), follow_redirects=False)
    assert response.status_code == 303


def test_upload_page_loads_pdf_finder_with_vendor_pdfjs(logged_in_client: TestClient) -> None:
    html = logged_in_client.get("/invoices/upload").text
    assert "js/pdf-invoice-page.js" in html
    assert "js/vendor/pdfjs/pdf.min.mjs" in html
    assert "js/vendor/pdfjs/pdf.worker.min.mjs" in html
    assert 'data-pdfjs-cmaps="/static/js/vendor/pdfjs/cmaps/"' in html
    assert 'id="pdf-pick-status"' in html
    assert "45 頁以內" in html
    # 挑頁模組要在 mobile-camera.js 之前載入
    assert html.index("pdf-invoice-page.js") < html.index("mobile-camera.js")


def test_camera_page_does_not_load_pdf_finder(logged_in_client: TestClient) -> None:
    html = logged_in_client.get("/invoices/mobile-upload").text
    assert "pdf-invoice-page.js" not in html


def test_vendor_pdfjs_files_and_license_are_present() -> None:
    vendor = ROOT / "app/static/js/vendor"
    for name in ("pdf.min.mjs", "pdf.worker.min.mjs", "LICENSE"):
        assert (vendor / "pdfjs" / name).is_file()
    assert any((vendor / "pdfjs/cmaps").glob("*.bcmap"))
    readme = (vendor / "README.md").read_text(encoding="utf-8")
    assert "pdfjs-dist" in readme and "4.10.38" in readme
