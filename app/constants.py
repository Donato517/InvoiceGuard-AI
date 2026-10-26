"""
模組名稱：app.constants
功能說明：全站共用常數——網站名稱、cookie 名稱、發票狀態顯示文字。
注意事項：
    - INVOICE_STATUS_LABEL 的鍵必須涵蓋 API 專案 app/db/models/invoice.py 中 InvoiceStatus 的所有值。
"""

from app.core.constants import SITE_NAMES

# 網站名稱集中在三站共用的 app/core/constants.py
SITE_NAME = SITE_NAMES["FRONTEND"]

# 存放 API access token 的 cookie（httpOnly，瀏覽器端 JavaScript 讀不到）
SESSION_COOKIE_NAME = "ig_session"

# 發票狀態 → 畫面顯示文字
INVOICE_STATUS_LABEL: dict[str, str] = {
    "pending": "待分析",
    "analyzing": "分析中",
    "passed": "通過",
    "flagged": "有風險",
    "rejected": "異常",
}
