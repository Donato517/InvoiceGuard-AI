"""測試目標：上傳核對頁的必填標示／格式提示／缺漏摘要接線（樣板、指令碼載入順序、共用整理 helper）。

注意：這裡只檢查樣板與原始碼的接線，不是真實瀏覽器行為；畫面互動、版面與捲動須另行手動驗收。
JS 邏輯本身的測試在 tests/js/invoice_field_rules.test.mjs（node --test tests/js/）。
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

JS = Path("app/static/js/mobile-camera.js").read_text(encoding="utf-8")
RULES_JS = Path("app/static/js/invoice-field-rules.js").read_text(encoding="utf-8")
CSS = Path("app/static/css/pages/mobile-camera.css").read_text(encoding="utf-8")


@pytest.mark.parametrize("path", ["/invoices/upload", "/invoices/mobile-upload"])
def test_pages_load_rules_before_camera_script_and_start_clean(
    logged_in_client: TestClient, path: str
) -> None:
    html = logged_in_client.get(path).text

    rules = html.index("js/invoice-field-rules.js")
    camera = html.index("js/mobile-camera.js")
    assert rules < camera
    # 初次載入：缺漏摘要存在但隱藏、沒有任何預先渲染的缺漏提示或格式提示
    assert re.search(r'<div id="required-summary"[^>]*\bhidden\b', html)
    assert "field-missing" not in html
    assert "field-hint--" not in html
    assert "is-missing" not in html


def test_build_payload_uses_shared_normalizers_not_inline_expressions() -> None:
    assert "Rules.normalizeTrack(d.invoice_track)" in JS
    assert "Rules.normalizeNumber(d.invoice_number)" in JS
    assert "Rules.cleanNumber(value)" in JS
    assert "d.invoice_track.toUpperCase()" not in JS
    # 整理函式只有一份定義
    assert RULES_JS.count("function normalizeTrack") == 1
    assert RULES_JS.count("function cleanNumber") == 1
    assert "const AMOUNT_RE = Rules.AMOUNT_RE" in JS
    assert "const QUANTITY_RE = Rules.QUANTITY_RE" in JS


def test_confirm_button_checks_required_through_the_proxy_before_original_checks() -> None:
    assert "postJson('/invoices/check-required'" in JS
    start = JS.index("Rules.runConfirm({")
    handler = JS[start : start + 1800]
    assert "proceed: continueAfterRequired" in handler
    # 原有的格式檢查 buildPayload 只在必填通過後的 continueAfterRequired 中呼叫
    assert JS.count("= buildPayload()") == 1
    proceed = JS[JS.index("function continueAfterRequired") :]
    assert proceed.index("= buildPayload()") < proceed.index("showStep('step-confirm')")


def test_format_hints_are_not_driven_by_keystrokes_or_api_calls() -> None:
    feedback = JS[JS.index("function attachFeedback") : JS.index("function headerField")]
    assert "addEventListener('blur'" in feedback
    assert "fetch(" not in feedback
    assert "postJson" not in feedback
    # input 事件只收起舊提示與清除已補齊的缺漏，不顯示新提示
    input_handler = feedback[feedback.index("addEventListener('input'") :]
    input_handler = input_handler[: input_handler.index("});")]
    assert "showHint" not in input_handler


def test_required_mark_is_a_red_tight_star_required_label() -> None:
    assert "make('span', { class: 'field-required' }, '*必填')" in JS
    block = CSS[CSS.index(".field-required") :]
    block = block[: block.index("}")]
    assert "var(--color-danger" in block
    assert "letter-spacing: 0" in block


def test_existing_ai_warnings_are_still_rendered_after_new_feedback() -> None:
    field = JS[JS.index("function headerField") : JS.index("function markItemRow")]
    assert "warningsFor(field).forEach" in field
    assert "field-warning" in field


def test_unmapped_missing_fields_stay_in_the_summary() -> None:
    assert "missingUnmapped" in JS
    assert "尚缺 ' + names.length + ' 個必填欄位" in JS


def test_check_failure_clears_stale_missing_keeps_inputs_and_shows_fixed_message() -> None:
    start = JS.index("function showCheckFailure")
    body = JS[start : JS.index("\n  function ", start)]

    assert "clearMissing()" in body  # 上一次已過期的缺漏提示一併清除
    assert ".value" not in body  # 不動使用者填寫的欄位值
    assert "showCheckFailure," in JS and "Rules.CHECK_FAILURE_MESSAGE" in JS
    assert "目前無法完成必填欄位檢查，請稍後再試。資料尚未送出。" in RULES_JS


def test_missing_display_and_request_use_the_shared_pure_helpers() -> None:
    assert "Rules.placeMissing(" in JS  # 找不到畫面欄位的缺漏改列摘要，由可測試的純函式決定
    assert "Rules.buildCheckRequest(currentDraft" in JS
    assert "function buildCheckRequest" not in JS  # 只有一份實作（invoice-field-rules.js）
    assert RULES_JS.count("function buildCheckRequest") == 1
