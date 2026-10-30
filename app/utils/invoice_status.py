"""
模組名稱：app.utils.invoice_status
功能說明：簽核狀態（Schema v1.5 草案的 9 種 invoices.status）與提交輪次（submission_round）的唯讀顯示文字。
注意事項：
    - 只負責顯示；不決定狀態轉換，也不寫入 status／submission_round。
    - 9 種代碼取自 PostgreSQL Schema v1.5 草案（尚未執行），與目前 app.constants.INVOICE_STATUS_LABEL
      （舊 5 種）不同；後者是共用常數，本輪不修改，兩者的整合待團隊決議。
    - 不認得的狀態代碼原樣顯示並標示「未知狀態」，不報錯、不猜測。
    - submission_round：0＝草稿（尚未正式提交）；≥1＝第 N 輪；缺值或型別不符顯示「-」，不推算。
"""

from dataclasses import dataclass
from typing import Any

# v1.5 草案：invoices.status 的 9 種代碼 → 顯示文字
APPROVAL_STATUS_LABEL: dict[str, str] = {
    "draft": "待申請中",
    "pending_department_approval": "待單位核准",
    "pending_accounting_review": "待會計覆核",
    "pending_accounting_approval": "待會計核准",
    "approved": "已核准",
    "returned_to_applicant": "退回申請單位補正",
    "returned_to_accounting": "退回會計補正",
    "rejected": "已駁回",
    "voided": "已作廢",
}


@dataclass(frozen=True)
class StatusView:
    """狀態的顯示資料；known 為 False 時 label 是「未知狀態（原代碼）」或「-」。"""

    code: str | None
    label: str
    known: bool


def status_view(value: Any) -> StatusView:
    """將狀態代碼轉成顯示資料；None／空白顯示「-」，未知代碼保留原文。"""
    code = value.strip() if isinstance(value, str) else ""
    if not code:
        return StatusView(None, "-", False)
    if code in APPROVAL_STATUS_LABEL:
        return StatusView(code, APPROVAL_STATUS_LABEL[code], True)
    return StatusView(code, f"未知狀態（{code}）", False)


def round_label(value: Any) -> str:
    """提交輪次的顯示文字；僅接受非負整數（bool 不算）。"""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return "-"
    return "草稿（尚未提交）" if value == 0 else f"第 {value} 輪"
