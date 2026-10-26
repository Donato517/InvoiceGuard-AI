"""僅供本機手機 HTTPS 測試的 ASGI 入口；不能用於 Vercel 或正式發布。"""

import base64
import binascii
import hmac
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI
from starlette.datastructures import Headers
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings, settings
from app.core.environment import EnvironmentConfigurationError, valid_service_url
from app.main import create_app
from app.routers.mobile_dev import create_router


def _unique_origin_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError
        result[name] = value
    return result


def _valid_origin(value: object) -> bool:
    if not isinstance(value, str) or not valid_service_url(value, allow_tunnel=True):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme == "https" and parsed.path == "" and parsed.port in {None, 443}
    except ValueError:
        return False


class MobileAccessGate:
    """固定開發 HTTPS 來源；內部診斷需臨時碼，一般網站沿用原本登入授權。"""

    def __init__(self, app: ASGIApp, configuration: Settings) -> None:
        self.app = app
        self.configuration = configuration
        self.origin = configuration.LOCAL_HTTPS_ORIGIN
        self.host = urlsplit(self.origin).netloc.lower()
        self.access_code = configuration.LOCAL_MOBILE_ACCESS_CODE.get_secret_value().encode("utf-8")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        pending_probe = not self.origin and self._pending_health_request(scope, headers)
        if (not pending_probe and scope.get("scheme") != "https") or (
            self.origin and headers.get("host", "").lower() != self.host
        ):
            response = PlainTextResponse("開發入口來源不正確", status_code=400)
        elif self._diagnostic_request(scope) and not self._authorized(
            headers.get("authorization", "")
        ):
            response = PlainTextResponse(
                "此路徑僅供啟動器內部診斷；請開啟網站登入頁 /login。",
                status_code=403,
            )
        else:
            try:
                self._load_origin_once()
            except (ValueError, OSError, EnvironmentConfigurationError):
                await self._respond(
                    PlainTextResponse("手機 HTTPS 設定尚未就緒", status_code=503),
                    scope,
                    receive,
                    send,
                )
                return
            if not self.origin:
                response = (
                    JSONResponse({"status": "ok", "env": "local", "pending_origin": True})
                    if pending_probe
                    else PlainTextResponse("手機 HTTPS 設定尚未就緒", status_code=503)
                )
                await self._respond(response, scope, receive, send)
                return
            if headers.get("host", "").lower() != self.host or scope.get("scheme") != "https":
                await self._respond(
                    PlainTextResponse("開發入口來源不正確", status_code=400), scope, receive, send
                )
                return

            async def no_store(message: Message) -> None:
                if message["type"] == "http.response.start":
                    response_headers = [
                        item
                        for item in message.get("headers", [])
                        if item[0].lower() != b"cache-control"
                    ]
                    message["headers"] = [*response_headers, (b"cache-control", b"no-store")]
                await send(message)

            await self.app(scope, receive, no_store)
            return
        await self._respond(response, scope, receive, send)

    @staticmethod
    async def _respond(
        response: PlainTextResponse | JSONResponse, scope: Scope, receive: Receive, send: Send
    ) -> None:
        response.headers["Cache-Control"] = "no-store"
        await response(scope, receive, send)

    def _load_origin_once(self) -> None:
        """固定受控單一 origin；完成握手後不再讀取後續檔案變更。"""
        if self.origin:
            return
        path = Path(self.configuration.LOCAL_MOBILE_ORIGIN_FILE)
        if not path.is_absolute() or path.name != "origin.json":
            raise ValueError
        if path.is_symlink() or path.resolve().parent != path.parent.resolve():
            raise ValueError
        if not path.exists():
            return
        if not path.is_file() or path.stat().st_size > 4096:
            raise ValueError
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_origin_object)
        if (
            not isinstance(data, dict)
            or set(data) != {"origin"}
            or not _valid_origin(data["origin"])
        ):
            raise ValueError
        self.configuration.LOCAL_HTTPS_ORIGIN = data["origin"]
        self.configuration.require_environment()
        self.origin = data["origin"]
        self.host = urlsplit(self.origin).netloc.lower()

    @staticmethod
    def _diagnostic_request(scope: Scope) -> bool:
        """診斷不作為使用者入口，也不發送瀏覽器帳密挑戰。"""
        path = scope.get("path", "")
        return path in {"/health", "/platforms", "/mobile", "/api-status"} or path.startswith(
            "/__dev/"
        )

    @staticmethod
    def _pending_health_request(scope: Scope, headers: Headers) -> bool:
        try:
            client = scope.get("client")
            client_host = client[0] if client else ""
            parsed = urlsplit("http://" + headers.get("host", ""))
            return (
                scope.get("method") == "GET"
                and scope.get("path") == "/health"
                and scope.get("scheme") == "http"
                and ipaddress.ip_address(client_host).is_loopback
                and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                and parsed.username is None
                and parsed.password is None
                and parsed.path == ""
                and not parsed.query
                and not parsed.fragment
                and parsed.port is not None
                and 1024 <= parsed.port <= 65535
            )
        except ValueError:
            return False

    def _authorized(self, authorization: str) -> bool:
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "basic" or len(token) > 1024:
            return False
        try:
            decoded = base64.b64decode(token, validate=True)
        except (ValueError, binascii.Error):
            return False
        username, separator, code = decoded.partition(b":")
        return (
            bool(separator)
            and hmac.compare_digest(username, b"dev")
            and hmac.compare_digest(code, self.access_code)
        )


def create_mobile_app(configuration: Settings | None = None) -> FastAPI:
    """本機 HTTPS 顯示原有網站；臨時碼僅供啟動器健康診斷，不是使用者登入。"""
    configuration = configuration if configuration is not None else settings
    configuration.require_environment()
    origin = configuration.LOCAL_HTTPS_ORIGIN
    origin_file = configuration.LOCAL_MOBILE_ORIGIN_FILE
    code = configuration.LOCAL_MOBILE_ACCESS_CODE.get_secret_value()
    if (
        configuration.APP_ENV != "local"
        or configuration.VERCEL
        or configuration.VERCEL_ENV
        or (not origin and not origin_file)
        or (bool(origin) and not _valid_origin(origin))
        or (
            bool(origin_file)
            and (not Path(origin_file).is_absolute() or Path(origin_file).name != "origin.json")
        )
        or len(code) < 24
    ):
        raise EnvironmentConfigurationError("手機開發入口僅接受完整的本機 HTTPS 設定")
    application = create_app(configuration)
    application.state.mobile_development = True
    application.include_router(create_router(configuration))
    application.add_middleware(MobileAccessGate, configuration=configuration)
    return application


app = create_mobile_app()
