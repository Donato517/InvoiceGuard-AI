"""
模組名稱：app.routers.home
功能說明：首頁。
路由：GET /
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.templating import templates

router = APIRouter(tags=["home"])


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    """首頁：產品介紹與上傳發票入口。"""
    return templates.TemplateResponse(request, "pages/home/index.html")


@router.get("/mobile-upload")
async def mobile_upload_shortcut() -> RedirectResponse:
    """手機拍照上傳快速捷徑。"""
    return RedirectResponse("/invoices/mobile-upload", status_code=303)
