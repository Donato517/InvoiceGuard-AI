"""測試目標：前台必填欄位清單與格式常數，須與 API InvoiceSubmitRequest（app/schemas/invoice_upload.py）相同。

注意：
    - 只讀 API 的原始碼文字（ast／文字比對），不匯入 API、不連任何服務。
    - 單站 clone 沒有兄弟專案時略過（pytest skip，不算通過）；三站在同一根目錄時才會比對。
    - 這是靜態一致性檢查，不代表 API 與前台的整合行為已實測。
"""

import ast
import re
from pathlib import Path

import pytest

API_SCHEMA = (
    Path(__file__).resolve().parents[3] / "InvoiceGuard-AI-API" / "app/schemas/invoice_upload.py"
)
RULES_JS = Path("app/static/js/invoice-field-rules.js").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(
    not API_SCHEMA.is_file(), reason="找不到兄弟專案 InvoiceGuard-AI-API，略過跨站規則比對"
)


def _required_fields(source: str, class_name: str) -> set[str]:
    """類別中沒有預設值的欄位（含 Field(...) 沒有 default 者）。"""
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    required: set[str] = set()
    for item in node.body:
        if not isinstance(item, ast.AnnAssign) or not isinstance(item.target, ast.Name):
            continue
        value = item.value
        has_no_default = (
            isinstance(value, ast.Call)
            and getattr(value.func, "id", None) == "Field"
            and not value.args
            and not any(kw.arg in ("default", "default_factory") for kw in value.keywords)
        )
        if value is None or has_no_default:
            required.add(item.target.id)
    return required


def _js_list(name: str) -> set[str]:
    match = re.search(rf"var {name} = \[(.*?)\];", RULES_JS, re.S)
    assert match, name
    return set(re.findall(r"'([a-z_]+)'", match.group(1)))


def _js_regex(name: str) -> str:
    match = re.search(rf"var {name} = /(.*)/;", RULES_JS)
    assert match, name
    return match.group(1)


def test_required_header_fields_match_api_model() -> None:
    source = API_SCHEMA.read_text(encoding="utf-8")
    required = _required_fields(source, "InvoiceSubmitRequest")

    # recognition_id 是前台程式帶的內部欄位，使用者無法補填；items 由前台另外處理明細整體
    assert required - {"recognition_id", "items"} == _js_list("REQUIRED_HEADER_FIELDS")
    assert "items" in required


def test_required_item_fields_match_api_model() -> None:
    source = API_SCHEMA.read_text(encoding="utf-8")

    assert _required_fields(source, "InvoiceItemSubmit") == _js_list("REQUIRED_ITEM_FIELDS")


def test_code_formats_match_api_patterns() -> None:
    source = API_SCHEMA.read_text(encoding="utf-8")

    assert 'pattern=r"^[A-Z]{2}$"' in source
    assert 'pattern=r"^[0-9]{8}$"' in source
    assert _js_regex("TRACK_RE") == "^[A-Z]{2}$"
    assert _js_regex("NUMBER_RE") == "^[0-9]{8}$"
    assert _js_regex("TAX_ID_RE") == "^[0-9]{8}$"


def test_amount_and_quantity_formats_match_api_digits() -> None:
    source = API_SCHEMA.read_text(encoding="utf-8")
    amount = re.search(r"Amount = Annotated\[Decimal, Field\(([^)]*)\)\]", source)
    quantity = re.search(r"Quantity = Annotated\[Decimal, Field\(([^)]*)\)\]", source)
    assert amount and quantity

    def expected(field_args: str) -> str:
        digits = int(re.search(r"max_digits=(\d+)", field_args).group(1))  # type: ignore[union-attr]
        places = int(re.search(r"decimal_places=(\d+)", field_args).group(1))  # type: ignore[union-attr]
        return rf"^\d{{1,{digits - places}}}(\.\d{{1,{places}}})?$"

    assert _js_regex("AMOUNT_RE") == expected(amount.group(1))
    assert _js_regex("QUANTITY_RE") == expected(quantity.group(1))


def test_optional_fields_have_no_required_mark() -> None:
    source = API_SCHEMA.read_text(encoding="utf-8")
    optional = {
        "seller_name",
        "buyer_tax_id",
        "buyer_name",
        "total_amount_zh",
        "quantity",
        "unit_price",
        "source_line_no",
    }

    assert not optional & (_required_fields(source, "InvoiceSubmitRequest"))
    assert not optional & (_required_fields(source, "InvoiceItemSubmit"))
    assert not optional & (_js_list("REQUIRED_HEADER_FIELDS") | _js_list("REQUIRED_ITEM_FIELDS"))
