"""
模組名稱：app.utils.invoice_list_view
功能說明：把 API 的「我的發票列表」回應整理成列表頁要顯示的資料——狀態文字與色調、號碼、分頁頁碼。
注意事項：
    - 只做顯示轉換，不判斷業務對錯；狀態文字沿用 app.utils.invoice_status（九種簽核狀態），
      不認得的代碼顯示「未知狀態（代碼）」，不報錯。
    - 不使用風險分數（API 與資料庫都沒有這個欄位）。
"""

from typing import Any

from app.utils.invoice_status import APPROVAL_STATUS_LABEL, round_label, status_view

# 狀態代碼 → 既有 components.css 的 badge 色調；未列入者用預設底色
_TONE: dict[str, str] = {
    "approved": "success",
    "pending_department_approval": "warning",
    "pending_accounting_review": "warning",
    "pending_accounting_approval": "warning",
    "returned_to_applicant": "danger",
    "returned_to_accounting": "danger",
    "rejected": "danger",
}

# 頁碼視窗：目前頁前後各顯示幾頁；其餘以 None（省略）取代
_PAGE_WINDOW = 2


def normalize_status(value: str | None) -> str | None:
    """篩選用狀態；不是九種合法代碼的一律視為「全部」，避免把任意字串傳給 API。"""
    return value if value in APPROVAL_STATUS_LABEL else None


def status_options() -> list[tuple[str, str]]:
    """篩選下拉選單：九種簽核狀態（代碼, 顯示文字）。"""
    return list(APPROVAL_STATUS_LABEL.items())


def page_numbers(page: int, total_pages: int) -> list[int | None]:
    """要顯示的頁碼；第 1 頁、最後一頁與目前頁前後各 2 頁，中間斷開處以 None 表示。"""
    wanted = {1, total_pages} | {
        n for n in range(page - _PAGE_WINDOW, page + _PAGE_WINDOW + 1) if 1 <= n <= total_pages
    }
    result: list[int | None] = []
    previous = 0
    for number in sorted(wanted):
        if number - previous > 1:
            result.append(None)
        result.append(number)
        previous = number
    return result


def build_list_view(result: dict[str, Any]) -> dict[str, Any]:
    """整理已通過 client 形狀檢查的列表回應。

    Returns:
        {"rows": [...], "total", "page", "page_size", "total_pages", "pages"}；
        每列含 invoice_id、number（字軌＋號碼，缺值顯示「-」）、status（StatusView）、tone、round_text 與原欄位。
    """
    total = result["total"]
    page_size = result["page_size"]
    total_pages = max(1, (total + page_size - 1) // page_size)
    rows = []
    for item in result["items"]:
        track = item.get("invoice_track") or ""
        number = item.get("invoice_number") or ""
        view = status_view(item.get("status"))
        rows.append(
            {
                "invoice_id": item["invoice_id"],
                "number": f"{track}{number}" or "-",
                "invoice_date": item.get("invoice_date"),
                "seller_name": item.get("seller_name"),
                "total_amount": item.get("total_amount"),
                "submitted_at": item.get("submitted_at"),
                "status": view,
                "tone": _TONE.get(view.code or "", ""),
                "round_text": round_label(item.get("submission_round")),
            }
        )
    return {
        "rows": rows,
        "total": total,
        "page": result["page"],
        "page_size": page_size,
        "total_pages": total_pages,
        "pages": page_numbers(result["page"], total_pages),
    }
