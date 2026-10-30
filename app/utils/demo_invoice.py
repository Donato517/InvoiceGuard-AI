"""
模組名稱：app.utils.demo_invoice
功能說明：發票詳情頁的本機虛構展示資料（測試資料／非正式案件），用來展示狀態、提交輪次、AI 原值差異與欄位／明細問題提示。
注意事項：
    - 全部是虛構資料（假 UUID、假統編、假公司），不來自 API 或資料庫，也不代表任何正式案件。
    - 其中的 validation issue 含 line_no／expected／actual／difference，是展示「來源若提供這些欄位時畫面如何呈現」；
      目前 API 的 FieldWarning 沒有這些欄位，請勿當成 API Contract。
    - 只由本機展示路由使用；正式詳情失敗時不得改用此資料。
"""

from typing import Any

# 固定的假 UUID（全零前綴，明顯不是正式案件）
DEMO_INVOICE_ID = "00000000-0000-4000-8000-00000000d3a0"


def build_demo_invoice() -> dict[str, Any]:
    """回傳一份新的虛構發票（每次呼叫都是獨立副本，呼叫端修改不影響下次）。"""
    return {
        "invoice_id": DEMO_INVOICE_ID,
        "status": "returned_to_applicant",
        "submission_round": 2,
        "form_type": "三聯式",
        "track_number": "ZZ00000001",
        "invoice_date": "2026-10-20",
        "buyer_name": "甲乙示範股份有限公司",
        "buyer_tax_id": "00000000",
        "items": [
            {"item_name": "文具", "quantity": "2", "unit_price": "50", "amount": "100"},
            {"item_name": "影印紙", "quantity": "1", "unit_price": "250", "amount": "250"},
            {"item_name": "墨水", "quantity": "1", "unit_price": "30", "amount": "30"},
        ],
        "sales_amount": "400",
        "tax_type": "應稅",
        "tax_amount": "20",
        "total_amount": "420",
        "total_amount_zh": "肆佰貳拾元整",
        "remark": "示範備註",
        "seller_name": "示範商行",
        # AI 原始快照（部分欄位刻意缺少或為空，展示各種原值狀態）
        "original_values": {
            "form_type": "三聯式",
            "track_number": "ZZ00000001",
            "invoice_date": "2026-10-20",
            "buyer_name": "甲乙公司",  # 與目前值不同 → 已修改
            "buyer_tax_id": "00000000",  # 一致 → 未修改
            "remark": None,  # 有快照但原值為空
            "seller_name": "示範商行",
            # tax_type、tax_amount… 沒有這些 key → 無 AI 原值
            "items": [
                {"item_name": "文具", "quantity": "2", "unit_price": "50", "amount": "100"},
                {"item_name": "影印紙", "quantity": "1", "unit_price": "200", "amount": "200"},
            ],  # 第 2 列已修改、第 3 列為新增
        },
        "validation": {
            "rule_version": "demo",
            "checked_at": "2026-10-29T00:00:00Z",
            "issues": [
                {
                    "field": "amount",
                    "code": "demo_line_amount",
                    "message": "（展示）第 2 筆明細金額與數量×單價不符",
                    "line_no": 2,
                    "expected": "250",
                    "actual": "300",
                    "difference": "50",
                },
                {
                    "field": "items",
                    "code": "items_total_mismatch",
                    "message": "明細金額合計與銷售額不符，請確認",
                },
                {"field": "future_field", "code": "new_code", "message": "（展示）未知欄位的提醒"},
            ],
        },
    }
