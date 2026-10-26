"""
模組名稱：app.core.config
功能說明：集中管理環境變數設定（pydantic-settings），全專案只從這裡讀取設定。
注意事項：
    - 禁止在其他模組直接使用 os.environ / os.getenv。
    - 新增設定時，必須同步更新根目錄 .env.example。
    - 不讀 .env 或 secrets 目錄；本機公開 URL 另由共用 JSON 載入，Vercel 只讀程序環境。
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.environment import environment_report, require_environment, settings_sources

# 專案根目錄（InvoiceGuard-AI/）
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """網站設定。欄位名稱即環境變數名稱。"""

    model_config = SettingsConfigDict(
        env_file=None,
        secrets_dir=None,
        extra="forbid",
        validate_assignment=True,
        hide_input_in_errors=True,
    )

    # ---- 基本 ----
    APP_NAME: str = "InvoiceGuard-AI"
    APP_ENV: Literal["local", "preview", "production"] = "local"
    DEBUG: bool = False

    # ---- 後端 API ----
    # localhost 預設只由本機 source 提供；雲端缺值必須拒絕，不能沿用開發網址。
    API_BASE_URL: str = Field(default="", repr=False)
    API_TIMEOUT_SECONDS: float = 30.0  # AI 分析可能較久

    # ---- 登入狀態 ----
    SESSION_MAX_AGE_SECONDS: int = 60 * 60

    # 僅限本機手機入口，由啟動器在程序內注入；不寫入 JSON 或雲端。
    LOCAL_HTTPS_ORIGIN: str = Field(default="", repr=False)
    LOCAL_MOBILE_ORIGIN_FILE: str = Field(default="", repr=False)
    LOCAL_MOBILE_ACCESS_CODE: SecretStr = Field(
        default_factory=lambda: SecretStr(""), repr=False, exclude=True
    )

    # 由設定 source 產生，僅保留誤載機密的欄位名稱，不保存其值。
    LOCAL_SECRET_FIELDS: tuple[str, ...] = Field(default=(), exclude=True, repr=False)

    # ---- Vercel 系統變數（由 Vercel 自動注入，不需手動設定）----
    VERCEL: str = ""
    VERCEL_ENV: str = ""
    VERCEL_GIT_COMMIT_SHA: str = ""

    @property
    def is_vercel(self) -> bool:
        """是否執行於 Vercel 環境。"""
        return self.VERCEL == "1"

    @property
    def cookie_secure(self) -> bool:
        """cookie 是否只走 HTTPS。本機開發為 http，因此只有 local 環境關閉。"""
        return (
            bool(self.LOCAL_HTTPS_ORIGIN or self.LOCAL_MOBILE_ORIGIN_FILE)
            or self.is_vercel
            or self.APP_ENV != "local"
        )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        """雲端只讀程序設定；不允許 _env_file／_secrets_dir 恢復讀取本機檔案。"""
        return settings_sources(
            init_settings, env_settings, repo_root=BASE_DIR, platform="frontend"
        )

    def check_environment(self) -> dict[str, Any]:
        """只驗證環境與 URL，不連 API。"""
        return environment_report(self, "frontend")

    def require_environment(self) -> None:
        """頁面組裝及 API 呼叫前驗證。"""
        require_environment(self, "frontend")

    @property
    def static_version(self) -> str:
        """靜態檔版本參數（部署後網址改變，瀏覽器才會重新下載 css / js）。"""
        return self.VERCEL_GIT_COMMIT_SHA[:7] or "dev"

    @property
    def temp_dir(self) -> Path:
        """暫存目錄。Vercel 上只有 /tmp 可寫入；本機使用專案內 tmp/（已列入 .gitignore）。"""
        if self.is_vercel:
            return Path("/tmp/invoiceguard")
        return BASE_DIR / "tmp"


@lru_cache
def get_settings() -> Settings:
    """取得設定單例（只在第一次呼叫時讀取環境變數）。"""
    return Settings()


settings = get_settings()
