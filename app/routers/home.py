"""
模組名稱：app.routers.home
功能說明：首頁。
路由：GET /
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core.templating import templates

router = APIRouter(tags=["home"])


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    """首頁：產品介紹與上傳發票入口。"""
    return templates.TemplateResponse(request, "pages/home/index.html")
