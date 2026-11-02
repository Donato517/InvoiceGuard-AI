"""
測試目標：提交成功頁的樣板與腳本不再硬編碼舊流程（字面值檢查）。
範圍：只讀原始檔文字，不執行 JS、不渲染頁面、不連 API；成功頁實際顯示由 tests/js/mobile_camera_success_status.test.mjs
（假 DOM）驗證。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = (ROOT / "app/templates/pages/invoices/_upload_review_steps.html").read_text("utf-8")
SCRIPT = (ROOT / "app/static/js/mobile-camera.js").read_text("utf-8")


def test_success_page_default_status_is_neutral() -> None:
    match = re.search(r'<strong id="success-status">([^<]*)</strong>', TEMPLATE)
    assert match is not None
    assert match.group(1) == "已送出"
    assert "待單位核准" not in TEMPLATE  # 不再把舊流程寫死在樣板


def test_success_page_points_to_my_invoices_instead_of_a_specific_approver() -> None:
    assert "等待請款單位核准" not in TEMPLATE
    assert "可至「我的發票」查看最新審核狀態" in TEMPLATE


def test_status_labels_cover_new_and_legacy_first_submit_statuses() -> None:
    block = re.search(r"const STATUS_LABELS = \{(.*?)\};", SCRIPT, re.S)
    assert block is not None
    labels = dict(re.findall(r"(\w+):\s*'([^']+)'", block.group(1)))
    assert labels == {
        "pending_accounting_review": "待會計覆核",
        "pending_department_approval": "待單位核准",
    }
