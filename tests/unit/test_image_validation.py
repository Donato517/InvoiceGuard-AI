"""測試目標：app.utils.image_validation 的 JPG／PNG 基本驗證（純 Python，不涉及瀏覽器與上傳）"""

import socket
from pathlib import Path

import pytest

from app.utils.image_validation import (
    ERROR_CONTENT,
    ERROR_EMPTY,
    ERROR_EXTENSION,
    ERROR_MIME,
    ERROR_NO_FILE,
    ERROR_TOO_LARGE,
    detect_image_type,
    format_size,
    validate_image,
)

LIMIT = 1024  # 測試用上限，不代表正式規格

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 20


def _check(content, filename, mime, max_bytes=LIMIT):
    return validate_image(content, filename=filename, declared_type=mime, max_bytes=max_bytes)


@pytest.mark.parametrize(
    ("content", "filename", "mime", "expected"),
    [
        (JPEG, "a.jpg", "image/jpeg", "image/jpeg"),
        (JPEG, "a.JPEG", "image/jpeg", "image/jpeg"),
        (PNG, "b.png", "image/png", "image/png"),
        (PNG, "b.PNG", "IMAGE/PNG; charset=binary", "image/png"),
        (JPEG, "發票 1.jpg", "image/jpeg", "image/jpeg"),
    ],
)
def test_valid_images_pass(content, filename, mime, expected):
    result = _check(content, filename, mime)
    assert result.ok
    assert result.error_code is None
    assert result.detected_type == expected


@pytest.mark.parametrize(
    ("content", "filename"),
    [(None, "a.jpg"), (JPEG, None), (JPEG, "")],
)
def test_no_file_is_rejected(content, filename):
    result = _check(content, filename, "image/jpeg")
    assert not result.ok
    assert result.error_code == ERROR_NO_FILE


def test_empty_file_is_rejected():
    assert _check(b"", "a.jpg", "image/jpeg").error_code == ERROR_EMPTY


def test_size_limit_boundary():
    assert _check(JPEG + b"\x00" * (LIMIT - len(JPEG)), "a.jpg", "image/jpeg").ok
    over = _check(JPEG + b"\x00" * (LIMIT - len(JPEG) + 1), "a.jpg", "image/jpeg")
    assert over.error_code == ERROR_TOO_LARGE
    assert "1 KB" in over.message


@pytest.mark.parametrize(
    "filename", ["a.gif", "a.pdf", "a.webp", "a", "a.", ".jpg.exe", "a.jpg.txt"]
)
def test_unsupported_extension(filename):
    assert _check(JPEG, filename, "image/jpeg").error_code == ERROR_EXTENSION


@pytest.mark.parametrize("mime", ["application/pdf", "text/plain", "image/gif", "", None])
def test_unsupported_mime(mime):
    assert _check(JPEG, "a.jpg", mime).error_code == ERROR_MIME


@pytest.mark.parametrize(
    ("content", "filename", "mime"),
    [
        (b"not an image at all", "a.jpg", "image/jpeg"),  # 副檔名與 MIME 正確、內容不是圖片
        (b"%PDF-1.7 fake", "a.png", "image/png"),
        (PNG, "a.jpg", "image/jpeg"),  # PNG 內容偽裝成 JPG
        (JPEG, "a.png", "image/png"),
        (JPEG, "a.jpg", "image/png"),  # 宣告 MIME 與內容不一致
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 20, "a.png", "image/png"),  # 缺 IHDR
        (b"\xff\xd8", "a.jpg", "image/jpeg"),  # 檔頭被截斷
    ],
)
def test_content_must_match_extension_and_mime(content, filename, mime):
    assert _check(content, filename, mime).error_code == ERROR_CONTENT


def test_detect_image_type():
    assert detect_image_type(JPEG) == "image/jpeg"
    assert detect_image_type(PNG) == "image/png"
    assert detect_image_type(b"") is None


@pytest.mark.parametrize("bad", [0, -1, None, True, 1.5])
def test_max_bytes_must_be_positive_int(bad):
    with pytest.raises(ValueError, match="max_bytes"):
        validate_image(JPEG, filename="a.jpg", declared_type="image/jpeg", max_bytes=bad)


def test_revalidating_after_failure_is_independent():
    """驗證不保留狀態：失敗後驗證有效圖片仍會通過。"""
    assert not _check(b"", "a.jpg", "image/jpeg").ok
    assert _check(PNG, "b.png", "image/png").ok


def test_validation_does_not_touch_network(monkeypatch: pytest.MonkeyPatch):
    def deny(*args, **kwargs):
        raise AssertionError("驗證不應建立網路連線")

    monkeypatch.setattr(socket.socket, "connect", deny)
    assert _check(JPEG, "a.jpg", "image/jpeg").ok


@pytest.mark.parametrize(
    ("size", "text"), [(10, "10 位元組"), (1536, "1.5 KB"), (4 * 1024 * 1024, "4 MB")]
)
def test_format_size(size, text):
    assert format_size(size) == text


def test_python_and_js_messages_share_error_codes():
    """JS 的錯誤代碼須與 Python 相同（只比對代碼字串，不代表瀏覽器行為已測）。"""
    source = Path("app/static/js/image-picker.js").read_text(encoding="utf-8")
    for code in (
        ERROR_NO_FILE,
        ERROR_EMPTY,
        ERROR_TOO_LARGE,
        ERROR_EXTENSION,
        ERROR_MIME,
        ERROR_CONTENT,
    ):
        assert f"'{code}'" in source
