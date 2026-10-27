"""
模組名稱：app.routers.home
功能說明：首頁。
路由：GET /
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.security import get_session_token
from app.core.templating import templates

router = APIRouter(tags=["home"])


def is_mobile_client(request: Request) -> bool:
    """判斷請求是否來自行動裝置瀏覽器。"""
    ua = request.headers.get("user-agent", "").lower()
    return any(keyword in ua for keyword in ("mobile", "android", "iphone", "ipod"))


@router.get("/", response_class=HTMLResponse, response_model=None)
async def home(request: Request) -> HTMLResponse | RedirectResponse:
    """首頁：未登入之手機端訪客自動導向登入頁；已登入或電腦端顯示首頁。"""
    token = get_session_token(request)
    if is_mobile_client(request) and token is None:
        return RedirectResponse("/login?next=%2Finvoices%2Fmobile-upload", status_code=303)
    return templates.TemplateResponse(request, "pages/home/index.html")


@router.get("/mobile-upload")
async def mobile_upload_shortcut() -> RedirectResponse:
    """手機拍照上傳快速捷徑。"""
    return RedirectResponse("/invoices/mobile-upload", status_code=303)
