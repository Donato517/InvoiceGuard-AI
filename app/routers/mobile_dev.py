"""手機開發檢查，只讀取 loopback API 的既有健康檢查，沒有任意代理或資料操作。"""

import ipaddress
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.core.config import Settings
from app.core.templating import templates


def local_api_health_url(base_url: str) -> str | None:
    """只允許直接 HTTP loopback；不解析 DNS，不接受雲端或任意測試網址。"""
    try:
        parsed = urlsplit(base_url)
        host = parsed.hostname or ""
        address = ipaddress.ip_address("127.0.0.1" if host == "localhost" else host)
        if (
            parsed.scheme != "http"
            or not address.is_loopback
            or isinstance(address, ipaddress.IPv6Address)
            and address.ipv4_mapped
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port is None
            or not 1024 <= parsed.port <= 65535
            or any(character.isspace() for character in base_url)
            or "\\" in base_url
        ):
            return None
        # localhost 固定轉成數字 loopback，避免任何 DNS 查詢；IPv6 亦使用標準表示。
        authority = f"[{address.compressed}]" if address.version == 6 else address.compressed
        return urlunsplit((parsed.scheme, f"{authority}:{parsed.port}", "/health", "", ""))
    except ValueError:
        return None


def create_router(configuration: Settings) -> APIRouter:
    """透過 closure 固定本次受驗設定，不接受請求提供目標 URL。"""
    router = APIRouter(include_in_schema=False)

    @router.get("/platforms", response_class=HTMLResponse)
    async def platforms_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "pages/dev/platforms.html")

    @router.get("/frontend")
    async def frontend_alias() -> RedirectResponse:
        """固定站內入口，不接受 next、url 或查詢參數改寫目的地。"""
        return RedirectResponse("/", status_code=303)

    @router.get("/mobile", response_class=HTMLResponse)
    @router.get("/__dev/mobile", response_class=HTMLResponse)
    async def mobile_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "pages/dev/mobile.html")

    @router.get("/mobile/upload")
    async def mobile_upload_alias() -> RedirectResponse:
        """導向手機拍照上傳頁面。"""
        return RedirectResponse("/invoices/mobile-upload", status_code=303)

    @router.get("/api-status")
    @router.get("/__dev/api-health")
    async def api_health() -> JSONResponse:
        target = local_api_health_url(configuration.API_BASE_URL)
        if target is None:
            return JSONResponse({"status": "error", "code": "LOCAL_API_REQUIRED"}, status_code=503)
        try:
            async with httpx.AsyncClient(
                timeout=3.0, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.get(target)
            body = response.json()
            if (
                response.status_code != 200
                or response.headers.get("X-InvoiceGuard-Service") != "InvoiceGuard-AI-API"
                or not isinstance(body, dict)
                or body.get("status") != "ok"
                or body.get("env") != "local"
            ):
                raise ValueError
        except (httpx.HTTPError, ValueError):
            return JSONResponse(
                {"status": "error", "code": "LOCAL_API_UNAVAILABLE"}, status_code=503
            )
        return JSONResponse(
            {
                "status": "ok",
                "service": "InvoiceGuard-AI-API",
                "environment": "local",
                "connectivity_checked": True,
                "business_operations_checked": False,
            }
        )

    return router
