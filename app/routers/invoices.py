"""
模組名稱：app.routers.invoices
功能說明：我的發票——列表、上傳、手機拍照上傳、詳情、與發票作業前台流程（步驟 1～3：上傳、AI OCR 辨識、核對修正）。
路由：GET /invoices、GET /invoices/upload、GET /invoices/mobile-upload、POST /invoices/mobile-upload、POST /invoices/check-duplicate、GET /invoices/{invoice_id}、GET /invoices/{invoice_id}/flow
注意事項：
    - 列表頁為「router → clients → 樣板」的完整參考寫法。
    - 發票流程 1～3 步驟由前台採購端執行，後續步驟 4～9 轉由後台審核。
"""

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.clients import invoices as invoices_client
from app.constants import INVOICE_FLOW_STEPS, INVOICE_STATUS_LABEL
from app.core.deps import AccessToken
from app.core.templating import templates

router = APIRouter(prefix="/invoices", tags=["invoices"])

# 示範前台發票記憶體資料
_CLIENT_INVOICES: list[dict[str, Any]] = [
    {
        "id": 1,
        "invoice_number": "AB12345678",
        "invoice_date": "2026-08-15",
        "seller_tax_id": "24681357",
        "buyer_tax_id": "12345678",
        "net_amount": 6000,
        "tax_amount": 300,
        "total_amount": 6300,
        "file_name": "invoice_001.jpg",
        "ocr_status": "done",
    },
    {
        "id": 2,
        "invoice_number": "AB12345679",
        "invoice_date": "2026-08-15",
        "seller_tax_id": "24681357",
        "buyer_tax_id": "12345678",
        "net_amount": 2000,
        "tax_amount": 100,
        "total_amount": 2100,
        "file_name": "invoice_002.jpg",
        "ocr_status": "done",
    },
]


def _find_client_invoice(invoice_id: int) -> dict[str, Any] | None:
    return next((i for i in _CLIENT_INVOICES if i["id"] == invoice_id), None)


def _build_user_flow_steps(current_step: int, invoice_id: int) -> list[dict[str, Any]]:
    steps = []
    for idx, label in enumerate(INVOICE_FLOW_STEPS, start=1):
        if idx < current_step:
            state = "done"
        elif idx == current_step:
            state = "active"
        else:
            state = "locked"

        # 前台只開放 1～3 步驟
        steps.append(
            {
                "number": idx,
                "label": label,
                "state": state,
                "url": f"/invoices/{invoice_id}/flow?step={idx}" if idx <= 3 else "#",
            }
        )
    return steps


@router.get("", response_class=HTMLResponse)
async def invoice_list(
    request: Request,
    token: AccessToken,
    page: Annotated[int, Query(ge=1)] = 1,
    status: str | None = None,
) -> HTMLResponse:
    """我的發票列表：分頁、依狀態篩選。"""
    # 不認得的狀態值視為「全部」，避免把任意字串傳給 API
    status = status if status in INVOICE_STATUS_LABEL else None
    result = await invoices_client.fetch_invoices(token, page=page, status=status)
    return templates.TemplateResponse(
        request,
        "pages/invoices/list.html",
        {"result": result, "status": status},
    )


class CheckDuplicateRequest(BaseModel):
    invoice_number: str


class MobileUploadRequest(BaseModel):
    invoice_number: str
    invoice_date: str = ""
    seller_tax_id: str = ""
    buyer_tax_id: str = ""
    net_amount: int = 0
    tax_amount: int = 0
    total_amount: int = 0
    item_name: str = ""
    file_name: str = "mobile_capture.jpg"
    rotation: int = 0
    use: str = ""


@router.get("/upload", response_class=HTMLResponse)
async def invoice_upload_page(request: Request, token: AccessToken) -> HTMLResponse:
    """上傳發票表單。"""
    return templates.TemplateResponse(request, "pages/invoices/upload.html")


@router.get("/mobile-upload", response_class=HTMLResponse)
async def mobile_upload_page(request: Request) -> HTMLResponse:
    """手機端採購拍照上傳頁面（含即時邊界對齊與 90° 旋轉校正）。"""
    return templates.TemplateResponse(request, "pages/invoices/mobile_upload.html")


@router.post("/check-duplicate")
async def check_duplicate_invoice(payload: CheckDuplicateRequest) -> dict[str, bool]:
    """檢查發票單號是否已存在。"""
    num = payload.invoice_number.strip().upper()
    is_duplicate = any(
        str(inv.get("invoice_number", "")).strip().upper() == num for inv in _CLIENT_INVOICES
    )
    return {"duplicate": is_duplicate}


@router.post("/mobile-upload")
async def mobile_upload_submit(payload: MobileUploadRequest) -> dict[str, Any]:
    """手機端確認上傳發票與校正後影像。"""
    new_id = max((int(inv["id"]) for inv in _CLIENT_INVOICES), default=0) + 1
    new_invoice = {
        "id": new_id,
        "invoice_number": payload.invoice_number,
        "invoice_date": payload.invoice_date,
        "seller_tax_id": payload.seller_tax_id,
        "buyer_tax_id": payload.buyer_tax_id,
        "net_amount": payload.net_amount,
        "tax_amount": payload.tax_amount,
        "total_amount": payload.total_amount,
        "item_name": payload.item_name,
        "file_name": payload.file_name,
        "rotation": payload.rotation,
        "use": payload.use,
        "ocr_status": "done",
    }
    _CLIENT_INVOICES.append(new_invoice)
    return {"status": "ok", "invoice_id": new_id}


@router.get("/{invoice_id}", response_class=HTMLResponse)
async def invoice_detail(request: Request, token: AccessToken, invoice_id: int) -> HTMLResponse:
    """發票詳情：發票資料、明細、AI 風險分數與判斷理由。"""
    return templates.TemplateResponse(
        request, "pages/invoices/detail.html", {"invoice_id": invoice_id}
    )


@router.get("/{invoice_id}/flow", response_class=HTMLResponse)
async def invoice_flow(
    request: Request,
    token: AccessToken,
    invoice_id: int,
    step: Annotated[int, Query(ge=1, le=3)] = 1,
) -> HTMLResponse:
    """發票作業前台流程（步驟 1～3：上傳、AI 辨識預覽、核對修正）。"""
    invoice = _find_client_invoice(invoice_id)
    if not invoice:
        # 如果是新發票，建立預設草稿
        invoice = {
            "id": invoice_id,
            "invoice_number": f"AB{12345670 + invoice_id}",
            "invoice_date": "2026-08-15",
            "seller_tax_id": "24681357",
            "buyer_tax_id": "12345678",
            "net_amount": 1000,
            "tax_amount": 50,
            "total_amount": 1050,
            "file_name": None,
            "ocr_status": "pending",
        }
        _CLIENT_INVOICES.append(invoice)

    steps = _build_user_flow_steps(step, invoice_id)

    return templates.TemplateResponse(
        request,
        "pages/invoices/flow.html",
        {
            "invoice": invoice,
            "step": step,
            "steps": steps,
            "field_errors": {},
            "error": None,
        },
    )


@router.post("/{invoice_id}/flow/upload")
async def upload_invoice_file(
    token: AccessToken,
    invoice_id: int,
    file: Annotated[UploadFile, File()],
) -> RedirectResponse:
    """步驟 1：上傳發票檔案並進入辨識。"""
    invoice = _find_client_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="找不到指定發票")

    if file and file.filename:
        invoice["file_name"] = file.filename
        invoice["ocr_status"] = "done"

    return RedirectResponse(f"/invoices/{invoice_id}/flow?step=2", status_code=303)


@router.post("/{invoice_id}/flow/correct")
async def correct_invoice_fields(
    token: AccessToken,
    invoice_id: int,
    invoice_number: Annotated[str, Form()],
    invoice_date: Annotated[str, Form()],
    seller_tax_id: Annotated[str | None, Form()] = None,
    buyer_tax_id: Annotated[str | None, Form()] = None,
    net_amount: Annotated[int, Form()] = 0,
) -> RedirectResponse:
    """步驟 3：採購核對修正發票資料。"""
    invoice = _find_client_invoice(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="找不到指定發票")

    invoice["invoice_number"] = invoice_number
    invoice["invoice_date"] = invoice_date
    invoice["seller_tax_id"] = seller_tax_id or ""
    invoice["buyer_tax_id"] = buyer_tax_id or ""
    invoice["net_amount"] = net_amount
    invoice["tax_amount"] = round(net_amount * 0.05)
    invoice["total_amount"] = net_amount + invoice["tax_amount"]

    # 採購核對完成後導回發票列表，待後台審核
    return RedirectResponse("/invoices", status_code=303)
