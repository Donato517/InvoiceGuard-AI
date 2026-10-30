"""
模組名稱：app.utils.image_validation
功能說明：發票圖片（JPG／PNG）的基本檔案驗證——大小、副檔名、宣告的 MIME 與檔案內容特徵（magic bytes）。
注意事項：
    - 純函式，不讀寫檔案、不連網路、不保存圖片內容；呼叫端傳入已取得的位元組。
    - max_bytes 由呼叫端明確傳入，本模組不決定正式上限（API 契約的上限見其 app/schemas/files.py）。
    - 這是前台的初步檢查；正式上傳時 API 仍須以串流長度與內容特徵再驗證一次。
    - 內容檢查只比對檔頭特徵，不代表圖片可完整解碼。
"""

from dataclasses import dataclass
from pathlib import PurePath

# 副檔名（小寫、含點）→ 內容類型
EXTENSION_TO_TYPE: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(EXTENSION_TO_TYPE.values())

_JPEG_SIGNATURE = b"\xff\xd8\xff"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# 錯誤代碼（前端 JS 使用同一組代碼）
ERROR_NO_FILE = "no_file"
ERROR_EMPTY = "empty"
ERROR_TOO_LARGE = "too_large"
ERROR_EXTENSION = "unsupported_extension"
ERROR_MIME = "unsupported_mime"
ERROR_CONTENT = "content_mismatch"

ERROR_MESSAGES: dict[str, str] = {
    ERROR_NO_FILE: "請選擇發票圖片",
    ERROR_EMPTY: "檔案是空的，請重新選擇",
    ERROR_TOO_LARGE: "檔案過大，請選擇小於 {limit} 的圖片",
    ERROR_EXTENSION: "只支援 JPG、JPEG、PNG 圖片",
    ERROR_MIME: "檔案類型不符，只支援 JPG、JPEG、PNG 圖片",
    ERROR_CONTENT: "檔案內容不是有效的 JPG 或 PNG 圖片，請重新選擇",
}


@dataclass(frozen=True)
class ImageValidation:
    """驗證結果。

    Attributes:
        ok: 是否通過。
        error_code: 失敗時的錯誤代碼；通過時為 None。
        message: 失敗時給使用者看的繁中訊息；通過時為空字串。
        detected_type: 由檔案內容判斷出的類型（"image/jpeg"／"image/png"）；無法判斷為 None。
    """

    ok: bool
    error_code: str | None = None
    message: str = ""
    detected_type: str | None = None


def format_size(num_bytes: int) -> str:
    """將位元組數轉為易讀文字，例如 4194304 → "4 MB"。"""
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):g} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:g} KB"
    return f"{num_bytes} 位元組"


def detect_image_type(content: bytes) -> str | None:
    """由檔頭特徵判斷圖片類型。

    Returns:
        "image/jpeg"、"image/png"；兩者皆不符回傳 None。
    """
    if content.startswith(_JPEG_SIGNATURE):
        return "image/jpeg"
    # PNG：8 位元組簽章後第一個區塊必為 IHDR
    if content.startswith(_PNG_SIGNATURE) and content[12:16] == b"IHDR":
        return "image/png"
    return None


def _fail(code: str, max_bytes: int, detected: str | None = None) -> ImageValidation:
    """組出失敗結果。"""
    message = ERROR_MESSAGES[code].format(limit=format_size(max_bytes))
    return ImageValidation(False, code, message, detected)


def validate_image(
    content: bytes | None,
    *,
    filename: str | None,
    declared_type: str | None,
    max_bytes: int,
) -> ImageValidation:
    """驗證單一發票圖片。

    檢查順序：是否有檔案 → 是否為空 → 大小 → 副檔名 → 宣告的 MIME → 檔案內容，
    內容類型還須與副檔名、宣告 MIME 一致。

    Args:
        content: 檔案位元組；None 代表沒有選取檔案。
        filename: 原始檔名（只取副檔名判斷，不用於任何路徑）。
        declared_type: 瀏覽器或請求宣告的 Content-Type；可含參數（如 "; charset"）。
        max_bytes: 允許的最大位元組數，須為正整數，由呼叫端依規格決定。

    Returns:
        ImageValidation。

    Raises:
        ValueError: max_bytes 不是正整數（屬程式設定錯誤，不是使用者輸入錯誤）。
    """
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes 須為正整數")
    if content is None or not filename:
        return _fail(ERROR_NO_FILE, max_bytes)
    if len(content) == 0:
        return _fail(ERROR_EMPTY, max_bytes)
    if len(content) > max_bytes:
        return _fail(ERROR_TOO_LARGE, max_bytes)

    extension_type = EXTENSION_TO_TYPE.get(PurePath(filename).suffix.lower())
    if extension_type is None:
        return _fail(ERROR_EXTENSION, max_bytes)

    mime = (declared_type or "").split(";", 1)[0].strip().lower()
    if mime not in ALLOWED_CONTENT_TYPES:
        return _fail(ERROR_MIME, max_bytes)

    detected = detect_image_type(content)
    if detected is None or detected != extension_type or detected != mime:
        return _fail(ERROR_CONTENT, max_bytes, detected)
    return ImageValidation(True, detected_type=detected)
