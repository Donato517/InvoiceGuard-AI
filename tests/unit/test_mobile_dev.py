"""僅用合成存取碼、ASGI 請求與 MockTransport 驗證手機入口，不接觸公司服務。"""

import asyncio
import importlib
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core import config, security
from app.core.environment import EnvironmentConfigurationError
from app.core.exceptions import ForbiddenError

ORIGIN = "https://synthetic-mobile.trycloudflare.com"
CODE = "synthetic-mobile-access-code-only"


def mobile_settings(**values: Any) -> config.Settings:
    defaults = {
        "LOCAL_HTTPS_ORIGIN": ORIGIN,
        "LOCAL_MOBILE_ACCESS_CODE": CODE,
        "API_BASE_URL": "http://127.0.0.1:8100/api/v1",
    }
    return config.Settings(_env_prefix="IG_MOBILE_TEST_", **(defaults | values))


@pytest.fixture
def mobile_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    # 專用 entry 在匯入時就檢查設定；先注入合成設定，不改全域程序環境。
    monkeypatch.setattr(config, "settings", mobile_settings())
    return importlib.import_module("app.mobile_dev")


@pytest.fixture
def mobile_client(mobile_module: ModuleType) -> TestClient:
    return TestClient(
        mobile_module.create_mobile_app(mobile_settings()),
        base_url=ORIGIN,
        follow_redirects=False,
    )


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/__dev/mobile",
        "/__dev/api-health",
        "/platforms",
        "/mobile",
        "/api-status",
    ],
)
def test_internal_diagnostics_require_code_without_browser_challenge(
    mobile_client: TestClient, path: str
) -> None:
    response = mobile_client.get(path)
    assert response.status_code == 403
    assert "www-authenticate" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    assert CODE not in response.text


@pytest.mark.parametrize(
    "authorization", ["Bearer synthetic", "Basic !!!", "Basic Og==", "Basic", "Digest bogus"]
)
def test_malformed_or_wrong_authorization_is_rejected(
    mobile_client: TestClient, authorization: str
) -> None:
    response = mobile_client.get("/__dev/api-health", headers={"Authorization": authorization})
    assert response.status_code == 403


def test_valid_code_opens_original_frontend_and_developer_page(mobile_client: TestClient) -> None:
    for path in (
        "/",
        "/login",
        "/health",
        "/__dev/mobile",
        "/static/js/mobile-dev.js",
        "/platforms",
        "/mobile",
    ):
        response = mobile_client.get(path, auth=("dev", CODE))
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert CODE not in response.text
    page = mobile_client.get("/__dev/mobile", auth=("dev", CODE)).text
    assert "不拍照、不保存或上傳影像" in page
    assert "Gemini" in page


def test_gate_does_not_replace_business_login(mobile_client: TestClient) -> None:
    response = mobile_client.get("/invoices", auth=("dev", CODE))
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


@pytest.mark.parametrize(
    "url",
    [
        "http://synthetic-mobile.trycloudflare.com/",
        "https://evil.example.invalid/",
        "http://127.0.0.1:8101/",
    ],
)
def test_gate_rejects_wrong_host_or_http_even_with_code(
    mobile_client: TestClient, url: str
) -> None:
    response = mobile_client.get(url, auth=("dev", CODE), headers={"X-Forwarded-Proto": "https"})
    assert response.status_code == 400


@pytest.mark.parametrize(
    "values",
    [
        {"LOCAL_HTTPS_ORIGIN": ""},
        {"LOCAL_MOBILE_ACCESS_CODE": ""},
        {"LOCAL_MOBILE_ACCESS_CODE": "short"},
        {"LOCAL_HTTPS_ORIGIN": "http://synthetic-mobile.trycloudflare.com"},
        {
            "VERCEL": "1",
            "VERCEL_ENV": "production",
            "APP_ENV": "production",
            "API_BASE_URL": "https://api.example.invalid/api/v1",
        },
    ],
)
def test_mobile_entry_refuses_incomplete_or_cloud_configuration(
    mobile_module: ModuleType, values: dict[str, Any]
) -> None:
    with pytest.raises(EnvironmentConfigurationError):
        mobile_module.create_mobile_app(mobile_settings(**values))


def test_formal_main_has_no_developer_routes_or_gate() -> None:
    from app.main import app

    assert not any(
        route.path.startswith("/__dev") for route in app.routes if hasattr(route, "path")
    )
    assert not app.user_middleware


def test_mobile_cookie_uses_secure_and_clear_cookie_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(security, "settings", mobile_settings())
    response = Response()
    security.set_session_cookie(response, "synthetic-user-token")
    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    cleared = Response()
    security.clear_session_cookie(cleared)
    assert "Secure" in cleared.headers["set-cookie"]


@pytest.mark.parametrize(
    "origin",
    [
        "http://synthetic-mobile.trycloudflare.com",
        "https://synthetic-mobile.trycloudflare.com:444",
        "https://synthetic-mobile.trycloudflare.com:0",
        "https://evil.example.invalid",
        "null",
        "https://user@synthetic-mobile.trycloudflare.com",
    ],
)
def test_mobile_csrf_rejects_other_scheme_host_or_port(
    monkeypatch: pytest.MonkeyPatch, origin: str
) -> None:
    monkeypatch.setattr(security, "settings", mobile_settings())
    request = Request(
        {
            "type": "http",
            "scheme": "https",
            "path": "/login",
            "headers": [(b"host", b"synthetic-mobile.trycloudflare.com")],
            "server": ("synthetic-mobile.trycloudflare.com", 443),
        }
    )
    with pytest.raises(ForbiddenError):
        security.verify_same_origin(request, origin)


def test_mobile_csrf_accepts_exact_https_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "settings", mobile_settings())
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "path": "/login",
            "headers": [(b"host", b"synthetic-mobile.trycloudflare.com")],
            "server": ("127.0.0.1", 8101),
        }
    )
    security.verify_same_origin(request, ORIGIN)
    security.verify_same_origin(request, ORIGIN + ":443")
    security.verify_same_origin(request, None)


def test_mobile_csrf_rejects_every_origin_before_handshake(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 握手檔尚未載入時沒有可信 origin；不可退回「主機:埠等於 Host」的一般規則。
    settings = mobile_settings(
        LOCAL_HTTPS_ORIGIN="", LOCAL_MOBILE_ORIGIN_FILE=str(tmp_path / "origin.json")
    )
    monkeypatch.setattr(security, "settings", settings)
    request = Request(
        {
            "type": "http",
            "scheme": "https",
            "path": "/logout",
            "headers": [(b"host", b"synthetic-mobile.trycloudflare.com")],
            "server": ("127.0.0.1", 8101),
        }
    )
    with pytest.raises(ForbiddenError):
        security.verify_same_origin(request, ORIGIN)
    security.verify_same_origin(request, None)


@pytest.mark.parametrize("path", ["/__dev/api-health", "/api-status"])
def test_api_probe_reads_only_local_health_with_no_credentials_or_proxy(
    mobile_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    from app.routers import mobile_dev

    original = httpx.AsyncClient
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert str(request.url) == "http://127.0.0.1:8100/health"
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        return httpx.Response(
            200,
            headers={"X-InvoiceGuard-Service": "InvoiceGuard-AI-API"},
            json={"status": "ok", "env": "local"},
        )

    def fake_client(**kwargs: Any) -> httpx.AsyncClient:
        assert kwargs == {"timeout": 3.0, "trust_env": False, "follow_redirects": False}
        return original(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(mobile_dev.httpx, "AsyncClient", fake_client)
    response = mobile_client.get(path + "?url=https://ignored.example.invalid", auth=("dev", CODE))
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "InvoiceGuard-AI-API",
        "environment": "local",
        "connectivity_checked": True,
        "business_operations_checked": False,
    }
    assert len(calls) == 1
    assert CODE not in response.text and "127.0.0.1" not in response.text


@pytest.mark.parametrize(
    "status,headers,body",
    [
        (200, {}, {"status": "ok", "env": "local"}),
        (
            200,
            {"X-InvoiceGuard-Service": "InvoiceGuard-AI-API"},
            {"status": "ok", "env": "production"},
        ),
        (302, {"Location": "https://api.example.invalid"}, {}),
        (500, {}, {"secret": CODE}),
    ],
)
def test_api_probe_rejects_wrong_service_environment_and_redirects(
    mobile_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    headers: dict[str, str],
    body: dict[str, Any],
) -> None:
    from app.routers import mobile_dev

    original = httpx.AsyncClient
    monkeypatch.setattr(
        mobile_dev.httpx,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, headers=headers, json=body)
            ),
            **kwargs,
        ),
    )
    response = mobile_client.get("/__dev/api-health", auth=("dev", CODE))
    assert response.status_code == 503
    assert response.json() == {"status": "error", "code": "LOCAL_API_UNAVAILABLE"}
    assert CODE not in response.text


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.invalid/api/v1",
        "http://10.0.0.1:8100/api/v1",
        "http://127.0.0.1:8100/api/v1?token=synthetic",
        "http://user:synthetic@127.0.0.1:8100/api/v1",
    ],
)
def test_probe_target_never_resolves_arbitrary_hosts(url: str) -> None:
    from app.routers.mobile_dev import local_api_health_url

    assert local_api_health_url(url) is None


@pytest.mark.parametrize(
    "base_url,health_url",
    [
        ("http://localhost:8100/api/v1", "http://127.0.0.1:8100/health"),
        ("http://127.0.0.1:8100/api/v1", "http://127.0.0.1:8100/health"),
        ("http://[::1]:8100/api/v1", "http://[::1]:8100/health"),
    ],
)
def test_loopback_health_target_is_normalized_without_dns(base_url: str, health_url: str) -> None:
    from app.routers.mobile_dev import local_api_health_url

    assert local_api_health_url(base_url) == health_url


def test_code_not_in_settings_dump_or_repr() -> None:
    settings = mobile_settings()
    assert CODE not in repr(settings) + settings.model_dump_json()


def test_access_gate_rejects_websocket(mobile_module: ModuleType) -> None:
    messages = []

    async def forbidden(*args: Any) -> None:
        raise AssertionError("開發入口不提供 websocket")

    async def receive() -> dict[str, Any]:
        return {"type": "websocket.connect"}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    gate = mobile_module.MobileAccessGate(forbidden, mobile_settings())
    asyncio.run(gate({"type": "websocket"}, receive, send))
    assert messages == [{"type": "websocket.close", "code": 1008}]


def test_pending_origin_reserves_listener_but_serves_only_authenticated_loopback_health(
    mobile_module: ModuleType,
    tmp_path: Path,
) -> None:
    settings = mobile_settings(
        LOCAL_HTTPS_ORIGIN="", LOCAL_MOBILE_ORIGIN_FILE=str(tmp_path / "origin.json")
    )
    app = mobile_module.create_mobile_app(settings)
    with TestClient(app, base_url="http://127.0.0.1:8101", client=("127.0.0.1", 45678)) as client:
        assert client.get("/health").status_code == 403
        response = client.get("/health", auth=("dev", CODE))
        assert response.json() == {"status": "ok", "env": "local", "pending_origin": True}
        for path in ("/", "/__dev/mobile", "/__dev/api-health", "/static/js/main.js"):
            # HTTP 不給 Basic challenge；只有 loopback readiness 例外。
            response = client.get(path, auth=("dev", CODE))
            assert response.status_code == 400
            assert "www-authenticate" not in response.headers
        assert (
            client.get(
                "https://synthetic-mobile.trycloudflare.com/health", auth=("dev", CODE)
            ).status_code
            == 503
        )


def test_pending_origin_does_not_accept_non_loopback_client(
    mobile_module: ModuleType, tmp_path: Path
) -> None:
    settings = mobile_settings(
        LOCAL_HTTPS_ORIGIN="", LOCAL_MOBILE_ORIGIN_FILE=str(tmp_path / "origin.json")
    )
    with TestClient(
        mobile_module.create_mobile_app(settings),
        base_url="http://127.0.0.1:8101",
        client=("203.0.113.1", 45678),
    ) as client:
        response = client.get("/health", auth=("dev", CODE))
        assert response.status_code == 400
        assert "www-authenticate" not in response.headers


def test_origin_file_is_loaded_once_then_frozen(mobile_module: ModuleType, tmp_path: Path) -> None:
    origin_file = tmp_path / "origin.json"
    settings = mobile_settings(LOCAL_HTTPS_ORIGIN="", LOCAL_MOBILE_ORIGIN_FILE=str(origin_file))
    with TestClient(mobile_module.create_mobile_app(settings), base_url=ORIGIN) as client:
        assert client.get("/", auth=("dev", CODE)).status_code == 503
        origin_file.write_text('{"origin":"' + ORIGIN + '"}', encoding="utf-8")
        assert client.get("/", auth=("dev", CODE)).status_code == 200
        assert settings.cookie_secure
        origin_file.write_text('{"origin":"https://changed.example.invalid"}', encoding="utf-8")
        assert client.get("/", auth=("dev", CODE)).status_code == 200
        assert client.get("https://changed.example.invalid/", auth=("dev", CODE)).status_code == 400
        assert settings.LOCAL_HTTPS_ORIGIN == ORIGIN


@pytest.mark.parametrize(
    "contents",
    [
        "{ synthetic-secret-marker",
        '{"origin":"https://one.example.invalid","origin":"https://two.example.invalid"}',
        '{"origin":"https://one.example.invalid","SECRET":"synthetic-secret-marker"}',
        '{"origin":"http://one.example.invalid"}',
        '{"origin":"https://one.example.invalid/path"}',
        '{"origin":"https://user:synthetic-secret-marker@one.example.invalid"}',
        "[]",
    ],
)
def test_invalid_origin_file_never_exposes_routes_or_contents(
    mobile_module: ModuleType,
    tmp_path: Path,
    contents: str,
) -> None:
    origin_file = tmp_path / "origin.json"
    origin_file.write_text(contents, encoding="utf-8")
    settings = mobile_settings(LOCAL_HTTPS_ORIGIN="", LOCAL_MOBILE_ORIGIN_FILE=str(origin_file))
    with TestClient(mobile_module.create_mobile_app(settings), base_url=ORIGIN) as client:
        response = client.get("/", auth=("dev", CODE))
        assert response.status_code == 503
        assert "synthetic-secret-marker" not in response.text
        assert str(origin_file) not in response.text


def test_oversized_origin_file_is_rejected(mobile_module: ModuleType, tmp_path: Path) -> None:
    origin_file = tmp_path / "origin.json"
    origin_file.write_text(" " * 4097, encoding="utf-8")
    settings = mobile_settings(LOCAL_HTTPS_ORIGIN="", LOCAL_MOBILE_ORIGIN_FILE=str(origin_file))
    with TestClient(mobile_module.create_mobile_app(settings), base_url=ORIGIN) as client:
        assert client.get("/", auth=("dev", CODE)).status_code == 503


def test_origin_file_symlink_is_rejected_before_read(
    mobile_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin_file = tmp_path / "origin.json"
    settings = mobile_settings(LOCAL_HTTPS_ORIGIN="", LOCAL_MOBILE_ORIGIN_FILE=str(origin_file))
    application = mobile_module.create_mobile_app(settings)
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == origin_file or original(path))
    with TestClient(application, base_url=ORIGIN) as client:
        assert client.get("/", auth=("dev", CODE)).status_code == 503


def test_origin_handshake_updates_cookie_and_csrf_settings(
    mobile_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin_file = tmp_path / "origin.json"
    settings = mobile_settings(LOCAL_HTTPS_ORIGIN="", LOCAL_MOBILE_ORIGIN_FILE=str(origin_file))
    monkeypatch.setattr(security, "settings", settings)
    assert settings.cookie_secure
    application = mobile_module.create_mobile_app(settings)
    origin_file.write_text('{"origin":"' + ORIGIN + '"}', encoding="utf-8")
    with TestClient(application, base_url=ORIGIN, follow_redirects=False) as client:
        bad = client.post(
            "/logout", auth=("dev", CODE), headers={"Origin": ORIGIN.replace("https:", "http:")}
        )
        assert bad.status_code == 403
        assert "set-cookie" not in bad.headers
        good = client.post("/logout", auth=("dev", CODE), headers={"Origin": ORIGIN})
        assert good.status_code == 303
        assert "Secure" in good.headers["set-cookie"]
        assert "HttpOnly" in good.headers["set-cookie"]


@pytest.mark.parametrize("path", ["/platforms", "/mobile", "/__dev/mobile"])
def test_mobile_html_has_platform_title_and_same_origin_navigation(
    mobile_client: TestClient,
    path: str,
) -> None:
    response = mobile_client.get(path, auth=("dev", CODE))
    assert response.status_code == 200
    assert "FRONTEND｜手機開發｜" in response.text
    assert 'aria-label="手機開發平台導覽"' in response.text
    for route in ("/platforms", "/frontend", "/mobile", "/api-status"):
        assert f'href="{route}"' in response.text
    assert "localhost:" not in response.text
    assert "127.0.0.1:" not in response.text
    assert CODE not in response.text


def test_platform_hub_keeps_admin_on_computer_without_public_link(
    mobile_client: TestClient,
) -> None:
    response = mobile_client.get("/platforms", auth=("dev", CODE))
    assert response.status_code == 200
    assert "FRONTEND｜採購手機前端" in response.text
    assert "MOBILE｜手機開發檢查" in response.text
    assert "API｜本機 API 狀態" in response.text
    assert "ADMIN｜管理後台" in response.text
    assert "僅在電腦開啟" in response.text
    assert "不公開管理後台" in response.text
    assert 'href="/admin' not in response.text
    assert 'href="http:' not in response.text
    assert 'href="https:' not in response.text


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?next=https://evil.example.invalid",
        "?url=//evil.example.invalid&role=admin",
        "?next=/invoices",
    ],
)
def test_frontend_alias_is_fixed_redirect_without_forwarding_query(
    mobile_client: TestClient,
    query: str,
) -> None:
    response = mobile_client.get("/frontend" + query, auth=("dev", CODE))
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "set-cookie" not in response.headers
    protected = mobile_client.get("/invoices", auth=("dev", CODE))
    assert protected.status_code == 303
    assert protected.headers["location"].startswith("/login")


@pytest.mark.parametrize("path", ["/platforms", "/frontend", "/mobile", "/api-status"])
@pytest.mark.parametrize(
    "base", ["http://synthetic-mobile.trycloudflare.com", "https://other.example.invalid"]
)
def test_mobile_aliases_still_reject_http_or_wrong_host(
    mobile_client: TestClient,
    path: str,
    base: str,
) -> None:
    response = mobile_client.get(base + path, auth=("dev", CODE))
    assert response.status_code == 400
    assert "www-authenticate" not in response.headers


@pytest.mark.parametrize("path", ["/platforms", "/frontend", "/mobile", "/api-status"])
def test_normal_entry_does_not_register_mobile_aliases(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 404
    assert "FRONTEND｜手機開發" not in response.text


@pytest.mark.parametrize("path", ["/", "/login"])
def test_normal_entry_has_no_mobile_banner_or_assets(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert "FRONTEND｜手機開發" not in response.text
    assert 'aria-label="手機開發平台導覽"' not in response.text
    assert "mobile-dev.css" not in response.text


@pytest.mark.parametrize("path", ["/", "/login"])
def test_mobile_original_pages_match_normal_app_without_extra_login(
    mobile_client: TestClient, client: TestClient, path: str
) -> None:
    response = mobile_client.get(path)
    assert response.status_code == 200
    assert "www-authenticate" not in response.headers
    assert response.text == client.get(path).text
    assert "手機開發平台導覽" not in response.text
    assert "mobile-dev.css" not in response.text
    assert 'href="/platforms"' not in response.text
    if path == "/login":
        assert 'action="/login"' in response.text
        assert 'name="email"' in response.text
        assert 'name="password"' in response.text


@pytest.mark.parametrize(
    "path", ["/static/css/main.css", "/static/js/main.js", "/static/icons/favicon.svg"]
)
def test_mobile_original_assets_do_not_trigger_browser_login(
    mobile_client: TestClient, path: str
) -> None:
    for _ in range(3):
        response = mobile_client.get(path)
        assert response.status_code == 200
        assert "www-authenticate" not in response.headers


def test_unauthenticated_invoice_page_still_uses_site_login(mobile_client: TestClient) -> None:
    response = mobile_client.get("/invoices")
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")
    assert "www-authenticate" not in response.headers


def test_wrong_site_login_stays_in_original_form_without_popup(
    mobile_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.clients import auth
    from app.clients.base import ApiError

    async def rejected_login(email: str, password: str) -> dict[str, str]:
        raise ApiError(401, "synthetic_auth_error", "合成帳密錯誤")

    monkeypatch.setattr(auth, "login", rejected_login)
    response = mobile_client.post(
        "/login",
        data={"email": "synthetic@example.invalid", "password": "synthetic-only"},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 400
    assert "合成帳密錯誤" in response.text
    assert "www-authenticate" not in response.headers
    assert "synthetic-only" not in response.text


def test_mobile_dev_upload_redirect(mobile_client: TestClient) -> None:
    response = mobile_client.get("/mobile/upload", auth=("dev", CODE))
    assert response.status_code == 303
    assert response.headers["location"] == "/invoices/mobile-upload"
