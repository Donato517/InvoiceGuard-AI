"""
模組名稱：app.utils.validation_view
功能說明：將規則檢核的 issues 整理成畫面用的呈現資料——正規化 severity、依欄位分組、判斷是否有阻擋提交的 error。
注意事項：
    - 只負責畫面呈現，不決定案件流程（workflow）狀態；validation 與 workflow 是不同層次。
    - 同一欄位的多筆 issue 全部保留；無法對應到畫面欄位的 issue 放入 general_issues，不會被丟棄。
    - 不認得的 severity 不視為 error 也不視為 warning，標示為「未知等級」並保留顯示，另計入 unknown_count；
      unknown 不阻擋提交（has_blocking_error 只看 error），摘要須另外顯示，不能讓使用者誤以為全部通過。
    - line_no／field_path／expected／actual／difference 為選用欄位：來源沒給就是 None，
      本模組不推算、不從 message 文字解析；目前 API 的 FieldWarning 只有 field／code／message。
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_UNKNOWN = "unknown"

# severity → 畫面顯示文字
SEVERITY_LABEL: dict[str, str] = {
    SEVERITY_ERROR: "錯誤",
    SEVERITY_WARNING: "警告",
    SEVERITY_UNKNOWN: "未知等級",
}

# warning 在畫面上的狀態提示
WARNING_NOTICE = "待人工確認"


@dataclass(frozen=True)
class IssueView:
    """單筆 issue 的畫面資料。"""

    code: str
    severity: str
    message: str
    raw_field: str
    field_path: str | None = None
    line_no: int | None = None
    expected: str | None = None
    actual: str | None = None
    difference: str | None = None

    @property
    def has_comparison(self) -> bool:
        """來源是否提供預期值或實際值（任一即可顯示對照）；沒提供就不顯示。"""
        return self.expected is not None or self.actual is not None

    @property
    def severity_label(self) -> str:
        """severity 的中文顯示文字。"""
        return SEVERITY_LABEL[self.severity]

    @property
    def is_blocking(self) -> bool:
        """是否為阻擋提交的 error。"""
        return self.severity == SEVERITY_ERROR

    @property
    def notice(self) -> str | None:
        """warning 顯示「待人工確認」；其他等級沒有。"""
        return WARNING_NOTICE if self.severity == SEVERITY_WARNING else None


@dataclass(frozen=True)
class ValidationView:
    """整張發票的 validation 呈現結果。"""

    issues_by_field: Mapping[str, tuple[IssueView, ...]]
    general_issues: tuple[IssueView, ...]
    error_count: int
    warning_count: int
    unknown_count: int = 0

    @property
    def has_blocking_error(self) -> bool:
        """是否存在阻擋提交的 error（只有 error 才會阻擋，warning 不會）。"""
        return self.error_count > 0

    @property
    def has_warning(self) -> bool:
        """是否存在需人工確認的 warning。"""
        return self.warning_count > 0


def normalize_severity(value: Any) -> str:
    """正規化 severity。

    Returns:
        "error"、"warning"，或不認得時的 "unknown"（大小寫與前後空白不影響判斷）。
    """
    text = value.strip().lower() if isinstance(value, str) else ""
    return text if text in (SEVERITY_ERROR, SEVERITY_WARNING) else SEVERITY_UNKNOWN


def _optional_text(value: Any) -> str | None:
    """選用文字欄位：None 與空白字串視為未提供；bool 不當作文字；其餘轉成字串。"""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _optional_line_no(value: Any) -> int | None:
    """明細序號（從 1 起算）：只接受正整數；其他一律視為未提供，不猜測列位置。"""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _to_issue_view(raw: Any) -> IssueView:
    """將單筆原始 issue 轉為 IssueView；格式不符時仍保留，訊息退回為原內容文字。"""
    if not isinstance(raw, Mapping):
        return IssueView("", SEVERITY_UNKNOWN, str(raw), "")
    return IssueView(
        code=str(raw.get("code") or ""),
        severity=normalize_severity(raw.get("severity")),
        message=str(raw.get("message") or ""),
        raw_field=str(raw.get("field") or ""),
        field_path=_optional_text(raw.get("field_path")),
        line_no=_optional_line_no(raw.get("line_no")),
        expected=_optional_text(raw.get("expected")),
        actual=_optional_text(raw.get("actual")),
        difference=_optional_text(raw.get("difference")),
    )


def present_issues(issues: Iterable[Any] | None, field_map: Mapping[str, str]) -> ValidationView:
    """整理 issues 供畫面顯示。

    Args:
        issues: 規則檢核回傳的 issue 清單；None 視為沒有 issue。
        field_map: issue 的 field 值 → 畫面欄位識別碼。

    Returns:
        ValidationView。issue 依原順序保留；field 無法對應者放入 general_issues。
    """
    grouped: dict[str, list[IssueView]] = {}
    general: list[IssueView] = []
    errors = warnings = unknowns = 0
    for raw in issues or ():
        issue = _to_issue_view(raw)
        errors += issue.severity == SEVERITY_ERROR
        warnings += issue.severity == SEVERITY_WARNING
        unknowns += issue.severity == SEVERITY_UNKNOWN
        ui_field_id = field_map.get(issue.raw_field)
        if ui_field_id is None:
            general.append(issue)
        else:
            grouped.setdefault(ui_field_id, []).append(issue)
    return ValidationView(
        issues_by_field={key: tuple(value) for key, value in grouped.items()},
        general_issues=tuple(general),
        error_count=errors,
        warning_count=warnings,
        unknown_count=unknowns,
    )
