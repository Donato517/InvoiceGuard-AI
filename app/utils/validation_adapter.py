"""
模組名稱：app.utils.validation_adapter
功能說明：把 API 回傳的檢核資料（invoices.validation_results 的 {"warnings": [...]}）轉成畫面用的 {"issues": [...]} 格式。
相依模組：無（純函式）
注意事項：
    - 只做資料格式轉接：不產生 API 沒給的 severity、規則代碼、預期值或差異金額；
      API 目前的 FieldWarning 只有 field／code／message，沒有 severity 就維持沒有，由 validation_view 標示為「未知等級」。
    - 來源已經是 {"issues": [...]}（前台 fixture）時原樣保留；兩者都沒有時回傳空的 issues。
    - 轉接不判斷阻擋與否，也不決定案件流程；warnings 是否阻擋送出須由團隊核定。
    - 純函式，不修改輸入、不連網路。
"""

from collections.abc import Mapping
from typing import Any

# 轉接時保留的 issue key；其他 key 不帶入，避免把未核定的欄位當成契約
_ISSUE_KEYS: tuple[str, ...] = (
    "field",
    "code",
    "message",
    "severity",
    "field_path",
    "line_no",
    "expected",
    "actual",
    "difference",
)


def _copy_issue(raw: Any) -> Any:
    """Mapping 只複製核定的 key（缺少的 key 不補）；其他型別原樣交給 validation_view 處理。"""
    if not isinstance(raw, Mapping):
        return raw
    return {key: raw[key] for key in _ISSUE_KEYS if key in raw}


def normalize_validation(raw: Any) -> dict[str, Any]:
    """將 API 的 validation_results 或前台 fixture 的 validation 轉成 {"issues", ...} 格式。

    Args:
        raw: validation_results（{"warnings": [...]}）或 validation（{"issues": [...]}）；
            其他型別視為沒有檢核資料。

    Returns:
        含 issues（list）的 dict；rule_version、checked_at 有給才帶入。
    """
    if not isinstance(raw, Mapping):
        return {"issues": []}
    source = raw.get("issues")
    if not isinstance(source, list | tuple):
        source = raw.get("warnings")
    issues = [_copy_issue(item) for item in source] if isinstance(source, list | tuple) else []
    result: dict[str, Any] = {"issues": issues}
    for key in ("rule_version", "checked_at"):
        if key in raw:
            result[key] = raw[key]
    return result
