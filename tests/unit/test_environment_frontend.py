"""前端組裝與出站 API 都必須使用已驗證的環境。"""

import asyncio
import importlib
from typing import Any

import pytest

from app.clients import base
from app.core import config
from app.core.environment import EnvironmentConfigurationError


def cloud_settings(**values: Any) -> config.Settings:
    defaults = {"VERCEL": "1", "VERCEL_ENV": "production", "APP_ENV": "production"}
    return config.Settings(_env_prefix="IG_FRONTEND_TEST_", **(defaults | values))


def test_cloud_missing_api_url_has_no_localhost_fallback() -> None:
    settings = cloud_settings()
    assert settings.API_BASE_URL == ""
    with pytest.raises(EnvironmentConfigurationError, match="invalid_api_url"):
        settings.require_environment()


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/api/v1",
        "https://localhost/api/v1",
        "https://temporary.trycloudflare.com/api/v1",
        "https://10.0.0.1/api/v1",
    ],
)
def test_cloud_rejects_development_api_urls(url: str) -> None:
    assert not cloud_settings(API_BASE_URL=url).check_environment()["configuration_valid"]


def test_frontend_refuses_invalid_url_before_constructing_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(base, "settings", cloud_settings())

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("不合規環境不得建立 HTTP client")

    monkeypatch.setattr(base.httpx, "AsyncClient", forbidden)
    with pytest.raises(EnvironmentConfigurationError):
        asyncio.run(base.request_json("GET", "/invoices"))


def test_main_rejects_invalid_environment_before_creating_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    original_app = main.app
    original_settings = main.settings
    monkeypatch.setattr(config, "settings", cloud_settings())
    try:
        with pytest.raises(EnvironmentConfigurationError):
            importlib.reload(main)
        assert main.app is original_app
    finally:
        main.settings = original_settings
