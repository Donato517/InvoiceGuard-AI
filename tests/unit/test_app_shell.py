"""測試目標：前台登入後的外框（2026-11-06 對齊後台）——側欄群組與目前頁面、手機底部分頁、未登入沿用原頁首、
上傳頁步驟卡片。全部離線（API 替身由 conftest 提供）。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.utils.app_nav import sidebar_groups, tab_items

ROOT = Path(__file__).resolve().parents[2]


def _active(path: str) -> list[str]:
    return [item.name for group in sidebar_groups(path) for item in group.items if item.active]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/invoices/upload", ["上傳發票"]),
        ("/invoices/mobile-upload", ["拍照上傳"]),
        ("/invoices", ["我的發票"]),
        ("/invoices/3f1c0a52-0000-4000-8000-000000000000", ["我的發票"]),
        ("/invoices/showcase-reference", ["範例發票參考"]),
        ("/qa", ["知識庫問答"]),
        ("/", []),
        ("/invoices-x", []),
    ],
)
def test_sidebar_marks_only_the_longest_matching_item(path: str, expected: list[str]) -> None:
    assert _active(path) == expected


def test_sidebar_groups_follow_the_approved_order_and_open_the_current_group() -> None:
    groups = sidebar_groups("/qa")
    assert [(g.title, [i.name for i in g.items]) for g in groups] == [
        ("發票作業", ["上傳發票", "拍照上傳", "我的發票", "範例發票參考"]),
        ("RAG 知識庫", ["知識庫問答"]),
    ]
    assert [g.current for g in groups] == [False, True]


@pytest.mark.parametrize(
    ("path", "active"),
    [
        ("/invoices/upload", "拍照上傳"),  # 電腦上傳頁也算在「拍照上傳」分頁
        ("/invoices/mobile-upload", "拍照上傳"),
        ("/invoices", "我的發票"),
        ("/qa", "問答"),
    ],
)
def test_tabbar_marks_the_current_tab(path: str, active: str) -> None:
    items = tab_items(path)
    assert [i.name for i in items] == ["拍照上傳", "我的發票", "問答"]
    assert [i.name for i in items if i.active] == [active]


def test_logged_in_pages_use_the_sidebar_shell(logged_in_client: TestClient) -> None:
    html = logged_in_client.get("/invoices/upload").text
    assert 'class="app-shell"' in html and 'class="app-sidebar"' in html
    assert 'class="app-tabbar"' in html and "data-sidebar-collapse" in html
    assert html.count("app-sidebar__link--active") == 1  # 只有「上傳發票」標示為目前頁面
    assert 'action="/logout"' in html
    assert 'class="app-header"' not in html


def test_logged_out_pages_keep_the_original_header(client: TestClient) -> None:
    html = client.get("/").text
    assert 'class="app-header"' in html
    assert 'class="app-sidebar"' not in html and 'class="app-tabbar"' not in html


@pytest.mark.parametrize(
    ("path", "first"), [("/invoices/upload", "選擇檔案"), ("/invoices/mobile-upload", "拍攝")]
)
def test_upload_pages_show_step_cards(logged_in_client: TestClient, path: str, first: str) -> None:
    html = logged_in_client.get(path).text
    assert "data-upload-stepper" in html and "js/upload-stepper.js" in html
    assert "css/pages/upload-layout.css" in html
    assert f'<span class="upload-stepper__label">{first}</span>' in html
    assert '<span class="upload-stepper__label">核對修正</span>' in html
    assert "→ 預覽 →" not in html  # 舊的文字步驟已換成卡片


def test_main_js_keeps_sidebar_preferences_optional() -> None:
    script = (ROOT / "app/static/js/main.js").read_text(encoding="utf-8")
    assert "ig-front-sidebar-collapsed" in script and "ig-front-sidebar-open-groups" in script
    # 讀寫瀏覽器儲存都包在 try／catch：無痕或封鎖時照預設顯示
    assert script.count("window.localStorage") == 2
    assert script.count("} catch {") >= 2


def test_shell_css_is_loaded_and_uses_admin_sidebar_tokens() -> None:
    main = (ROOT / "app/static/css/main.css").read_text(encoding="utf-8")
    variables = (ROOT / "app/static/css/variables.css").read_text(encoding="utf-8")
    assert "@import url('./app-shell.css');" in main
    for token in ("--sidebar-width: 220px", "--color-sidebar-active: #244e80"):
        assert token in variables
