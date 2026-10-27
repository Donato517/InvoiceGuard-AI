"""
模組名稱：app.main
功能說明：前台網站進入點；建立 FastAPI app，掛載靜態檔、例外處理與頁面路由。
注意事項：
    - 本機啟動：uvicorn app.main:app --reload --port 8001
    - Vercel 會自動偵測本檔的 `app` 物件作為 Function 進入點，設定見 vercel.json。
    - Vercel 會把 app.mount 的 StaticFiles 提升到 CDN；加上全域 middleware 會讓靜態檔改由
      Function 回應（失去 CDN），因此本專案不使用全域 middleware，請改用相依注入。
    - 本檔只做「組裝」，不放任何業務邏輯。
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import BASE_DIR, Settings, settings
from app.core.exceptions import register_exception_handlers
from app.core.logging_config import setup_logging
from app.routers import auth, health, home, invoices, qa, robots


def create_app(configuration: Settings | None = None) -> FastAPI:
    """組裝原有網站；正式入口不掛載手機開發工具或全域 middleware。"""
    configuration = configuration if configuration is not None else settings
    configuration.require_environment()
    setup_logging()
    application = FastAPI(
        title=configuration.APP_NAME,
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
    register_exception_handlers(application)
    application.include_router(health.router)
    application.include_router(robots.router)
    application.include_router(home.router)
    application.include_router(auth.router)
    application.include_router(invoices.router)
    application.include_router(qa.router)
    return application


app = create_app()
