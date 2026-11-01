"""測試目標：app.clients.invoices.fetch_invoice 的回應驗證（Mock：以 MockTransport 替換 HTTP 傳輸，不連任何服務）。

驗證範圍：2xx 但非 JSON／空本文／型別或巢狀形狀不符／回傳的案件 UUID 與請求不同，一律 502
INVALID_UPSTREAM_RESPONSE 且不含原始本文；合法的 Stage 1 回應原樣通過。這是離線契約檢查，
不代表與真實 API 整合通過。
"""

import copy
from typing import Any

import httpx
import pytest
from stage1_detail import API_DETAIL_ID, STAGE1_DETAIL_KEYS, build_api_detail

from app.clients import invoices as invoices_client
from app.clients.base import ApiError

SECRET_BODY = "<html>gateway SECRET-RAW-BODY</html>"


@pytest.fixture
def api_returns(monkeypatch: pytest.MonkeyPatch) -> Any:
    """讓真實的 fetch_invoice 與 request_json 收到指定的 HTTP 回應（不連任何服務）。"""
    real_async_client = httpx.AsyncClient
    seen: list[httpx.Request] = []

    def install(responder: Any) -> list[httpx.Request]:
        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return responder(request)

        def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_async_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        return seen

    return install


def _fetch(requested: str = API_DETAIL_ID) -> Any:
    import asyncio

    return asyncio.run(invoices_client.fetch_invoice("token", requested))


def _json(body: Any, status: int = 200) -> Any:
    return lambda request: httpx.Response(status, json=body)


def _invalid(exc: pytest.ExceptionInfo[ApiError]) -> None:
    assert exc.value.status_code == 502
    assert exc.value.code == "INVALID_UPSTREAM_RESPONSE"
    assert SECRET_BODY not in exc.value.message
    assert "SECRET" not in str(exc.value)


# ---- Mock 契約快照本身 ----


def test_mock_snapshot_matches_stage1_top_level_keys_and_types() -> None:
    detail = build_api_detail()

    assert set(detail) == STAGE1_DETAIL_KEYS
    assert isinstance(detail["submission_round"], int)
    for key in ("sales_amount", "tax_amount", "total_amount"):
        assert isinstance(detail[key], str)  # 金額為字串，保留小數位
    assert set(detail["items"][0]) == {
        "line_no",
        "item_name",
        "quantity",
        "unit_price",
        "line_amount",
    }
    assert set(detail["file"]) == {"mime_type", "original_filename", "size_bytes", "version_no"}


def test_mock_snapshot_covers_nullable_fields_and_nested_modified_fields() -> None:
    nullable = {
        key: None for key in STAGE1_DETAIL_KEYS - {"invoice_id", "status", "submission_round"}
    }
    nullable.update(items=[], modified_fields=[], warnings=[])
    detail = build_api_detail(**nullable)

    assert set(detail) == STAGE1_DETAIL_KEYS
    assert detail["file"] is None and detail["sales_amount"] is None


def test_mock_snapshot_is_independent_copy() -> None:
    first = build_api_detail()
    first["items"].append({})
    assert len(build_api_detail()["items"]) == 2


# ---- 合法回應 ----


def test_valid_stage1_response_passes_unchanged(api_returns: Any) -> None:
    body = build_api_detail()
    seen = api_returns(_json(body))

    assert _fetch() == body
    assert seen[0].method == "GET"
    assert seen[0].url.path.endswith(f"/invoices/{API_DETAIL_ID}")
    assert seen[0].headers["authorization"] == "Bearer token"


def test_nullable_fields_nested_modified_fields_and_file_null_pass(api_returns: Any) -> None:
    body = build_api_detail(
        invoice_track=None,
        invoice_number=None,
        sales_amount=None,
        tax_type=None,
        file=None,
        modified_fields=[
            {
                "field_scope": "header",
                "line_no": None,
                "field_name": "deleted_item_3",
                "ai_original_value": {"item_name": "舊品名", "quantity": None},
                "submitted_value": None,
            },
            {
                "field_scope": "item",
                "line_no": 2,
                "field_name": "line_amount",
                "ai_original_value": "4000",
                "submitted_value": "4000.5",
            },
            # 未知的 scope／name 不在 client 拒絕，交給 Adapter 顯示
            {"field_scope": "future", "line_no": None, "field_name": "x", "ai_original_value": [1]},
        ],
    )
    api_returns(_json(body))

    assert _fetch() == body


def test_extra_unknown_fields_are_accepted(api_returns: Any) -> None:
    body = build_api_detail(brand_new_field={"a": 1})
    api_returns(_json(body))

    assert _fetch()["brand_new_field"] == {"a": 1}


def test_same_uuid_with_different_case_passes(api_returns: Any) -> None:
    api_returns(_json(build_api_detail(invoice_id=API_DETAIL_ID.upper())))

    assert _fetch()["invoice_id"] == API_DETAIL_ID.upper()


def test_duplicate_line_numbers_are_not_rejected_by_client(api_returns: Any) -> None:
    items = build_api_detail()["items"]
    items[1]["line_no"] = 1
    api_returns(_json(build_api_detail(items=items)))

    assert [i["line_no"] for i in _fetch()["items"]] == [1, 1]


# ---- 2xx 但內容不可用：一律 502，不含原始本文 ----


@pytest.mark.parametrize(
    ("status", "content"),
    [
        (200, SECRET_BODY.encode()),
        (200, b""),
        (204, b""),
        (200, b"{not valid json"),
        (200, b"\x80\x81\x82"),
        (200, b"\xff\xfe\x00{"),
    ],
    ids=["html", "empty", "no-content", "invalid-json", "non-utf8", "bom-garbage"],
)
def test_2xx_without_valid_json_is_502(api_returns: Any, status: int, content: bytes) -> None:
    api_returns(lambda request: httpx.Response(status, content=content))

    with pytest.raises(ApiError) as exc:
        _fetch()

    _invalid(exc)


@pytest.mark.parametrize("body", [[], [build_api_detail()], "text", 7, None, True])
def test_non_object_json_is_502(api_returns: Any, body: Any) -> None:
    api_returns(_json(body))

    with pytest.raises(ApiError) as exc:
        _fetch()

    _invalid(exc)


@pytest.mark.parametrize(
    "key",
    sorted(
        STAGE1_DETAIL_KEYS
        & {"invoice_id", "status", "submission_round", "items", "modified_fields", "warnings"}
    ),
)
def test_missing_required_key_is_502(api_returns: Any, key: str) -> None:
    body = build_api_detail()
    del body[key]
    api_returns(_json(body))

    with pytest.raises(ApiError) as exc:
        _fetch()

    _invalid(exc)


def test_fixture_shaped_payload_cannot_pass_as_api_response(api_returns: Any) -> None:
    from app.utils.demo_invoice import build_demo_invoice

    api_returns(_json(build_demo_invoice()))

    with pytest.raises(ApiError) as exc:
        _fetch()

    _invalid(exc)


@pytest.mark.parametrize(
    "overrides",
    [
        {"invoice_id": 123},
        {"invoice_id": "not-a-uuid"},
        {"invoice_id": "123e4567-e89b-42d3-a456-426614174999"},  # 另一張案件
        {"status": None},
        {"status": 5},
        {"submission_round": True},
        {"submission_round": False},
        {"submission_round": "1"},
        {"submission_round": 1.0},
        {"submission_round": None},
        {"invoice_track": 5},
        {"invoice_date": 20261015},
        {"sales_amount": 6000.0},
        {"tax_amount": 300},
        {"total_amount": 6300.5},
        {"submitted_at": 1},
        {"items": None},
        {"items": {}},
        {"items": "x"},
        {"items": ["x"]},
        {"items": [{"item_name": "無序號"}]},
        {"items": [{"line_no": True, "item_name": "x"}]},
        {"items": [{"line_no": "1", "item_name": "x"}]},
        {"items": [{"line_no": 1.0, "item_name": "x"}]},
        {"items": [{"line_no": 1, "line_amount": 2000.0}]},
        {"items": [{"line_no": 1, "quantity": 2}]},
        {"modified_fields": None},
        {"modified_fields": {}},
        {"modified_fields": ["x"]},
        {"modified_fields": [{"field_scope": "header", "line_no": None}]},
        {"modified_fields": [{"field_scope": None, "line_no": None, "field_name": "x"}]},
        {"modified_fields": [{"field_scope": "item", "line_no": True, "field_name": "x"}]},
        {"modified_fields": [{"field_scope": "item", "line_no": "2", "field_name": "x"}]},
        {"warnings": None},
        {"warnings": {}},
        {"warnings": ["x"]},
        {"warnings": [{"field": "items", "code": "c"}]},
        {"warnings": [{"field": "items", "code": "c", "message": 5}]},
        {"file": "x"},
        {"file": []},
    ],
)
def test_wrong_types_or_nested_shape_is_502(api_returns: Any, overrides: dict[str, Any]) -> None:
    api_returns(_json(build_api_detail(**overrides)))

    with pytest.raises(ApiError) as exc:
        _fetch()

    _invalid(exc)


def test_response_is_not_mutated_by_validation(api_returns: Any) -> None:
    body = build_api_detail(
        modified_fields=[
            {
                "field_scope": "item",
                "line_no": 1,
                "field_name": "item_name",
                "ai_original_value": {"a": [1]},
                "submitted_value": None,
            }
        ]
    )
    snapshot = copy.deepcopy(body)
    api_returns(_json(body))

    assert _fetch() == snapshot


def test_invalid_requested_id_fails_closed(api_returns: Any) -> None:
    api_returns(_json(build_api_detail()))

    with pytest.raises(ApiError) as exc:
        _fetch("7")

    _invalid(exc)


# ---- API 的錯誤回應原樣轉成 ApiError（由全域處理器決定畫面） ----


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "UNAUTHORIZED"),
        (404, "NOT_FOUND"),
        (422, "VALIDATION_ERROR"),
        (500, "INVOICE_DATA_INVALID"),
        (500, "INTERNAL_ERROR"),
        (503, "SERVICE_UNAVAILABLE"),
    ],
)
def test_api_error_contract_is_preserved(api_returns: Any, status: int, code: str) -> None:
    body = {"error": {"code": code, "message": "後端訊息", "details": None}}
    api_returns(_json(body, status))

    with pytest.raises(ApiError) as exc:
        _fetch()

    assert (exc.value.status_code, exc.value.code, exc.value.message) == (status, code, "後端訊息")


def test_connection_failure_and_timeout_become_503_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_async_client = httpx.AsyncClient

    for exception in (httpx.ConnectError("x"), httpx.ReadTimeout("x")):

        def handler(request: httpx.Request, exception: Exception = exception) -> httpx.Response:
            raise exception

        def factory(*args: Any, handler: Any = handler, **kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_async_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        with pytest.raises(ApiError) as exc:
            _fetch()
        assert (exc.value.status_code, exc.value.code) == (503, "NETWORK_ERROR")
