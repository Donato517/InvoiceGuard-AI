"""
模組名稱：app.routers.invoices
功能說明：我的發票——列表、上傳、手機拍照上傳、詳情、與發票作業前台流程（步驟 1～3：上傳、AI OCR 辨識、核對修正）。
路由：GET /invoices、GET /invoices/upload、GET /invoices/mobile-upload、POST /invoices/mobile-recognize、POST /invoices/check-duplicate、POST /invoices/mobile-upload、GET /invoices/{invoice_id}、GET /invoices/{invoice_id}/flow
注意事項：
    - 列表頁為「router → clients → 樣板」的完整參考寫法。
    - 手機上傳的辨識、查重、送出由頁面 JS 以 fetch（Accept: application/json）呼叫，本站轉呼叫 API 並回 JSON；
      錯誤（含 Session 核對與 Origin 檢查）由全域處理器回 JSON，Session 失效時（401）仍導向登入頁。
    - 發票流程 1～3 步驟由前台採購端執行，後續步驟 4～9 轉由後台審核。
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from app.clients import invoices as invoices_client
from app.constants import INVOICE_FLOW_STEPS, INVOICE_STATUS_LABEL
from app.core.deps import AccessToken
from app.core.security import verify_same_origin
from app.core.templating import templates
from app.routers.auth import require_session

# 全部發票頁面需登入：每次經 API 核對 Session
router = APIRouter(prefix="/invoices", tags=["invoices"], dependencies=[Depends(require_session)])

# 手機上傳影像上限：與 API 相同（Vercel 請求本文上限 4.5 MB），頁面會先縮圖
MAX_MOBILE_IMAGE_BYTES = 4 * 1024 * 1024

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
    """查重條件（字軌＋號碼＋賣方統編）；格式由 API 驗證。"""

    model_config = ConfigDict(extra="forbid")

    invoice_track: str = Field(max_length=2)
    invoice_number: str = Field(max_length=8)
    seller_tax_id: str = Field(max_length=8)


class MobileUploadItem(BaseModel):
    """核對後的一筆品名明細；source_line_no 為對應的 AI 辨識明細序號（新增的明細為 None）。"""

    model_config = ConfigDict(extra="forbid")

    source_line_no: int | None = Field(default=None, ge=1, le=50)
    item_name: str = Field(max_length=200)
    quantity: str | None = Field(default=None, max_length=30)
    unit_price: str | None = Field(default=None, max_length=30)
    line_amount: str = Field(max_length=30)


class MobileUploadChange(BaseModel):
    """核對頁的一次欄位修改（依時間順序）；API 據以保存修改歷程。"""

    model_config = ConfigDict(extra="forbid")

    field_scope: str = Field(max_length=10)
    line_no: int | None = Field(default=None, ge=1, le=50)
    field_name: str = Field(max_length=40)
    old_value: str | None = Field(default=None, max_length=200)
    new_value: str | None = Field(default=None, max_length=200)


class MobileUploadRequest(BaseModel):
    """核對、查重後送出的發票；欄位對應 API POST /invoices，格式與業務規則由 API 驗證。"""

    model_config = ConfigDict(extra="forbid")

    recognition_id: str = Field(max_length=36)
    invoice_track: str = Field(max_length=2)
    invoice_number: str = Field(max_length=8)
    invoice_date: str = Field(max_length=10)
    seller_tax_id: str = Field(max_length=8)
    seller_name: str | None = Field(default=None, max_length=200)
    buyer_tax_id: str | None = Field(default=None, max_length=8)
    buyer_name: str | None = Field(default=None, max_length=200)
    tax_type: str = Field(max_length=20)
    sales_amount: str = Field(max_length=30)
    tax_amount: str = Field(max_length=30)
    total_amount: str = Field(max_length=30)
    total_amount_zh: str | None = Field(default=None, max_length=200)
    items: list[MobileUploadItem] = Field(max_length=50)
    changes: list[MobileUploadChange] = Field(default_factory=list, max_length=500)


@router.get("/upload", response_class=HTMLResponse)
async def invoice_upload_page(request: Request, token: AccessToken) -> HTMLResponse:
    """上傳發票（電腦選檔）：本機 JPG／PNG 影像或單頁 PDF，流程與手機拍照頁相同。"""
    return templates.TemplateResponse(
        request, "pages/invoices/upload.html", {"upload_mode": "file"}
    )


@router.get("/mobile-upload", response_class=HTMLResponse)
async def mobile_upload_page(request: Request, token: AccessToken) -> HTMLResponse:
    """手機端採購拍照上傳頁面（含即時邊界對齊與 90° 旋轉校正）。"""
    return templates.TemplateResponse(
        request, "pages/invoices/mobile_upload.html", {"upload_mode": "camera"}
    )


@router.post("/mobile-recognize", dependencies=[Depends(verify_same_origin)], response_model=None)
async def mobile_recognize(
    token: AccessToken, file: Annotated[UploadFile, File()]
) -> dict[str, Any] | JSONResponse:
    """辨識（手機拍照頁與電腦上傳頁共用）：把影像或單頁 PDF 轉給 API（存檔、OCR、AI 整理欄位），回傳 API 的辨識 JSON。"""
    content = await file.read(MAX_MOBILE_IMAGE_BYTES + 1)
    if len(content) > MAX_MOBILE_IMAGE_BYTES:
        error = {
            "code": "INVOICE_IMAGE_TOO_LARGE",
            "message": "檔案超過 4 MB，請重新拍攝或改選較小的檔案",
        }
        return JSONResponse({"error": error}, status_code=400)
    return await invoices_client.recognize_invoice(
        token,
        filename=file.filename or "mobile_capture.jpg",
        content=content,
        content_type=file.content_type or "application/octet-stream",
    )


@router.post("/check-duplicate", dependencies=[Depends(verify_same_origin)], response_model=None)
async def check_duplicate_invoice(
    payload: CheckDuplicateRequest, token: AccessToken
) -> dict[str, Any]:
    """查重：經 API 確認字軌＋號碼＋賣方統編是否已存在。"""
    return await invoices_client.check_duplicate(token, **payload.model_dump())


@router.post("/mobile-upload", dependencies=[Depends(verify_same_origin)], response_model=None)
async def mobile_upload_submit(payload: MobileUploadRequest, token: AccessToken) -> dict[str, Any]:
    """手機端確認上傳：經 API 建立發票（待單位核准）並標記使用者修改的欄位；影像沿用辨識時保存的檔案。"""
    return await invoices_client.submit_invoice(token, payload.model_dump())


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
