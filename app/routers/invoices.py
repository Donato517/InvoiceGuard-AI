"""
模組名稱：app.routers.invoices
功能說明：我的發票——列表、上傳、詳情（皆需登入）。
路由：GET /invoices、GET /invoices/upload、GET /invoices/{invoice_id}
    （詳情為確認畫面骨架：只讀取與呈現，尚無修改／重新檢核／提交路由）
注意事項：
    - 列表頁為「router → clients → 樣板」的完整參考寫法，其他頁面依同樣模式實作。
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.clients import invoices as invoices_client
from app.constants import INVOICE_STATUS_LABEL
from app.core.deps import AccessToken
from app.core.templating import templates
from app.utils.invoice_confirmation import build_confirmation_view

router = APIRouter(prefix="/invoices", tags=["invoices"])


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


@router.get("/upload", response_class=HTMLResponse)
async def invoice_upload_page(request: Request, token: AccessToken) -> HTMLResponse:
    """上傳發票表單。"""
    # TODO(JerryChien): 新增 POST /invoices/upload：檢查檔案類型與大小 → upload_invoice() → 導向詳情頁
    return templates.TemplateResponse(request, "pages/invoices/upload.html")


@router.get("/{invoice_id}", response_class=HTMLResponse)
async def invoice_detail(request: Request, token: AccessToken, invoice_id: int) -> HTMLResponse:
    """發票確認畫面：14 類業務欄位、明細與規則檢核結果（僅呈現，不修改、不提交）。"""
    invoice = await invoices_client.fetch_invoice(token, invoice_id)
    return templates.TemplateResponse(
        request,
        "pages/invoices/detail.html",
        {"invoice_id": invoice_id, "view": build_confirmation_view(invoice)},
    )
